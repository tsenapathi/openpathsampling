'''
Created on 06.07.2014

@author: JDC Chodera
@author: JH Prinz
'''

import netCDF4 as netcdf # for netcdf interface provided by netCDF4 in enthought python
import pickle
import os.path

import numpy
import simtk.unit as units
import simtk.openmm.app
from simtk.unit import amu
import mdtraj as md

import json
import yaml


from object_storage import ObjectStorage
from trajectory_store import TrajectoryStorage, SampleStorage
from snapshot_store import SnapshotStorage, ConfigurationStorage, MomentumStorage
from ensemble_store import EnsembleStorage
from opentis.shooting import ShootingPointSelector, ShootingPoint
from opentis.pathmover import PathMover, MoveDetails
from opentis.globalstate import GlobalState
from orderparameter_store import ObjectDictStorage
from opentis.orderparameter import OrderParameter
from opentis.snapshot import Snapshot
from opentis.trajectory import Trajectory


#=============================================================================================
# SOURCE CONTROL
#=============================================================================================

__version__ = "$Id: NoName.py 1 2014-07-06 07:47:29Z jprinz $"

#=============================================================================================
# NetCDF Storage for multiple forked trajectories
#=============================================================================================

class Storage(netcdf.Dataset):
    '''
    A netCDF4 wrapper to store trajectories based on snapshots of an OpenMM simulation. This allows effective storage of shooting trajectories
    '''

    def __init__(self, filename = 'trajectory.nc', mode = None, topology_file = None, unit_system = None):
        '''
        Create a storage for complex objects in a netCDF file
        
        Parameters
        ----------        
        topology : openmm.app.Topology
            the topology of the system to be stored. Needed for 
        filename : string
            filename of the netcdf file
        mode : string, default: None
            the mode of file creation, one of 'w' (write), 'a' (append) or None, which will append any existing files.
        '''

        if mode == None:
            if os.path.isfile(filename):
                mode = 'a'
            else:
                mode = 'w'

        self.filename = filename
        self.links = []

        if unit_system is not None:
            self.unit_system = unit_system
        else:
            self.unit_system = units.md_unit_system

        super(Storage, self).__init__(filename, mode)

        self.trajectory = TrajectoryStorage(self).register()
        self.snapshot = SnapshotStorage(self).register()
        self.configuration = ConfigurationStorage(self).register()
        self.momentum = MomentumStorage(self).register()
        self.ensemble = EnsembleStorage(self).register()
        self.sample = SampleStorage(self).register()
        self.pathmover = ObjectStorage(self, PathMover, named=True, json=True, identifier='json').register()
        self.movedetails = ObjectStorage(self, MoveDetails, named=False, json=True, identifier='json').register()
        self.shootingpoint = ObjectStorage(self, ShootingPoint, named=True, json=True).register()
        self.shootingpointselector = ObjectStorage(self, ShootingPointSelector, named=True, json=True, identifier='json').register()
        self.globalstate = ObjectStorage(self, GlobalState, named=True, json=True, identifier='json').register()
        self.collectivevariable = ObjectDictStorage(self, OrderParameter, Snapshot).register()
        self.cv = self.collectivevariable
        self.trajectoryparameter = ObjectDictStorage(self, OrderParameter, Trajectory).register()

        if mode == 'w':
            self._init()

            if isinstance(topology_file, md.Topology):
                self.topology = topology_file
                self._store_single_option(self, 'md_topology', self.topology)
                self.variables['pdb'][0] = ''
                elements = {key: tuple(el) for key, el in md.element.Element._elements_by_symbol.iteritems()}
                self._store_single_option(self, 'md_elements', elements)

            elif isinstance(topology_file, simtk.openmm.app.Topology):
                self.topology = md.Topology.from_openmm(topology_file)
                self._store_single_option(self, 'om_topology', topology_file)
                self.variables['pdb'][0] = ''
                elements = {key: tuple(el) for key, el in md.element.Element._elements_by_symbol.iteritems()}
                self._store_single_option(self, 'md_elements', elements)

            elif type(topology_file) is str:
                self.topology = md.load(topology_file).topology

                with open (topology_file, "r") as myfile:
                    pdb_string=myfile.read()

                self.variables['pdb'][0] = pdb_string


            self.atoms = self.topology.n_atoms

            self._init_classes()
            self.sync()

        elif mode == 'a':
            self.pdb = self.variables['pdb'][0]

            if len(self.pdb) > 0:
                if os.path.isfile('tempXXX.pdb'):
                    print "File tempXXX.pdb exists - no overwriting! Quitting"

                # Create a temporary file since mdtraj cannot read from string
                with open ('tempXXX.pdb', "w") as myfile:
                    myfile.write(self.pdb)

                self.topology = md.load('tempXXX.pdb').topology
                os.remove('tempXXX.pdb')
            else:
                # there is no pdb file stored
                elements = self._restore_single_option(self, 'md_elements')
                for key, el in elements.iteritems():
                    try:
                        md.element.Element(
                                    number=int(el[0]), name=el[1], symbol=el[2], mass=float(el[3])
                                 )
                        simtk.openmm.app.Element(
                                    number=int(el[0]), name=el[1], symbol=el[2], mass=float(el[3])*amu
                                 )
                    except(AssertionError):
                        pass

                self.topology = md.Topology.from_openmm(self._restore_single_option(self, 'om_topology'))

            self._restore_classes()


    def __getattr__(self, item):
        return self.__dict__[item]

    def __setattr__(self, key, value):
        self.__dict__[key] = value

    def _init_classes(self):
        '''
        Run the initialization on all added classes, when the storage is created only!

        Notes
        -----
        Only runs when the storage is created.
        '''

        for storage in self.links:
            # create a member variable which is the associated Class itself
            storage._init()

    def _restore_classes(self):
        '''
        Run restore on all added classes. Usually there is nothing to do.
        '''
#        for storage in self.links:
#            storage._restore()
        pass


    def _init(self):
        """
        Initialize the netCDF file for storage itself.
        """

        # add shared dimension for everyone. scalar and spatial
        if 'scalar' not in self.dimensions:
            self.createDimension('scalar', 1) # scalar dimension
            
        if 'spatial' not in self.dimensions:
            self.createDimension('spatial', 3) # number of spatial dimensions
        
        # Set global attributes.
        setattr(self, 'title', 'Open-Transition-Interface-Sampling')
        setattr(self, 'application', 'Host-Guest-System')
        setattr(self, 'program', 'run.py')
        setattr(self, 'programVersion', __version__)
        setattr(self, 'Conventions', 'Multi-State Transition Interface TPS')
        setattr(self, 'ConventionVersion', '0.1')

        # Create a string to hold the topology
        self.init_str('pdb')
        self.write_str('pdf', '')

        # Force sync to disk to avoid data loss.
        self.sync()

    def init_object(self, name):
        self.init_str(name)

    def store_object(self, name, obj):
        self.write_str(name, self.simplifier.to_json(obj))

    def restore_object(self, name, obj):
        json_string = self.variables[name][0]
        return self.simplifier.from_json(json_string)

    def write_str(self, name, string):
        packed_data = numpy.empty(1, 'O')
        packed_data[0] = string
        self.variables[name][:] = packed_data

    def init_str(self, name):
        self.createVariable(name, 'str', 'scalar')


class Simplifier(object):
    def __init__(self):
        self.excluded_keys = []

    def simplify(self,obj):
        if type(obj).__module__ != '__builtin__':
            if type(obj) is units.Quantity:
                # This is number with a unit so turn it into a list
                return { 'value' : obj / obj.unit, 'units' : self.unit_to_dict(obj.unit) }
            else:
                return None
        elif type(obj) is list:
            return [self.simplify(o) for o in obj]
        elif type(obj) is dict:
            return {key : self.simplify(o) for key, o in obj.iteritems() if type(key) is str and key not in self.excluded_keys}
        else:
            return obj

    def build(self,obj):
        if type(obj) is dict:
            if 'units' in obj and 'value' in obj:
                return obj['value'] * self.dict_to_unit(obj['units'])
            else:
                return {key : self._build_var(o) for key, o in obj.iteritems()}
        elif type(obj) is list:
            return [self._build_var(o) for o in obj]
        else:
            return obj

    def to_json(self, obj):
        simplified = self.simplify(obj)
        return json.dumps(simplified)

    def from_json(self, json_string):
        simplified = yaml.load(json_string)
        return self.build(simplified)

    def unitsytem_to_list(self, unit_system):
        '''
        Turn a simtk.UnitSystem() into a list of strings representing the unitsystem for serialization
        '''
        return [ u.name  for u in unit_system.units ]

    def unit_system_from_list(self, unit_system_list):
        '''
        Create a simtk.UnitSystem() from a serialialized list of strings representing the unitsystem
        '''
        return units.UnitSystem([ getattr(units, unit_name).iter_all_base_units().next()[0] for unit_name in unit_system_list])

    def unit_to_symbol(self, unit):
        return str(1.0 * unit).split()[1]

    def unit_to_dict(self, unit):
        d = {p.name : int(fac) for p, fac in unit.iter_all_base_units()}
        return d

    def dict_to_unit(self, unit_dict):
        unit = units.Unit({})
        for unit_name, unit_multiplication in unit_dict.iteritems():
            unit *= getattr(units, unit_name)**unit_multiplication

        return unit

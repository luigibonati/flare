import pytest
import numpy as np
from flare.struc import Structure
from flare.utils.parameter_helper import ParameterHelper
from flare.parameters import Parameters
from .test_gp import dumpcompare


def test_generate_by_line():

    pm = ParameterHelper()
    pm.define_group('specie', 'O', ['O'])
    pm.define_group('specie', 'C', ['C'])
    pm.define_group('specie', 'H', ['H'])
    pm.define_group('bond', '**', ['C', 'H'])
    pm.define_group('bond', 'OO', ['O', 'O'])
    pm.define_group('triplet', '***', ['O', 'O', 'C'])
    pm.define_group('triplet', 'OOO', ['O', 'O', 'O'])
    pm.define_group('mb', '1.5', ['C', 'H'])
    pm.define_group('mb', '1.5', ['C', 'O'])
    pm.define_group('mb', '1.5', ['O', 'H'])
    pm.define_group('mb', '2', ['O', 'O'])
    pm.define_group('mb', '2', ['H', 'O'])
    pm.define_group('mb', '2.8', ['O', 'O'])
    pm.set_parameters('**', [1, 0.5])
    pm.set_parameters('OO', [1, 0.5])
    pm.set_parameters('***', [1, 0.5])
    pm.set_parameters('OOO', [1, 0.5])
    pm.set_parameters('1.5', [1, 0.5, 1.5])
    pm.set_parameters('2', [1, 0.5, 2])
    pm.set_parameters('2.8', [1, 0.5, 2.8])
    pm.set_parameters('cutoff2b', 5)
    pm.set_parameters('cutoff3b', 4)
    pm.set_parameters('cutoffmb', 3)
    hm = pm.as_dict()
    print(hm)
    Parameters.check_instantiation(hm)
    Parameters.check_matching(hm, hm['hyps'], hm['cutoffs'])

def test_generate_by_line2():

    pm = ParameterHelper()
    pm.define_group('specie', 'O', ['O'])
    pm.define_group('specie', 'rest', ['C', 'H'])
    pm.define_group('bond', '**', ['*', '*'])
    pm.define_group('bond', 'OO', ['O', 'O'])
    pm.define_group('triplet', '***', ['*', '*', '*'])
    pm.define_group('triplet', 'Oall', ['O', 'O', 'O'])
    pm.set_parameters('**', [1, 0.5])
    pm.set_parameters('OO', [1, 0.5])
    pm.set_parameters('Oall', [1, 0.5])
    pm.set_parameters('***', [1, 0.5])
    pm.set_parameters('cutoff2b', 5)
    pm.set_parameters('cutoff3b', 4)
    hm = pm.as_dict()
    print(hm)
    Parameters.check_instantiation(hm)
    Parameters.check_matching(hm, hm['hyps'], hm['cutoffs'])

def test_generate_by_list():

    pm = ParameterHelper()
    pm.list_groups('specie', ['O', 'C', 'H'])
    pm.list_groups('bond', [['*', '*'], ['O','O']])
    pm.list_groups('triplet', [['*', '*', '*'], ['O','O', 'O']])
    pm.list_parameters({'bond0':[1, 0.5], 'bond1':[2, 0.2],
                        'triplet0':[1, 0.5], 'triplet1':[2, 0.2],
                        'cutoff2b':2, 'cutoff3b':1})
    hm = pm.as_dict()
    print(hm)
    Parameters.check_instantiation(hm)
    Parameters.check_matching(hm, hm['hyps'], hm['cutoffs'])

def test_initialization():
    pm = ParameterHelper(species=['O', 'C', 'H'],
                         kernels={'bond':[['*', '*'], ['O','O']],
                                  'triplet':[['*', '*', '*'], ['O','O', 'O']]},
                          parameters={'bond0':[1, 0.5], 'bond1':[2, 0.2],
                                'triplet0':[1, 0.5], 'triplet1':[2, 0.2],
                                'cutoff2b':2, 'cutoff3b':1})
    hm = pm.hyps_mask
    print(hm)
    Parameters.check_instantiation(hm)
    Parameters.check_matching(hm, hm['hyps'], hm['cutoffs'])

def test_opt():
    pm = ParameterHelper(species=['O', 'C', 'H'],
                          kernels={'bond':[['*', '*'], ['O','O']],
                                   'triplet':[['*', '*', '*'], ['O','O', 'O']]},
                          parameters={'bond0':[1, 0.5, 1], 'bond1':[2, 0.2, 2],
                                'triplet0':[1, 0.5], 'triplet1':[2, 0.2],
                                'cutoff2b':2, 'cutoff3b':1},
                          constraints={'bond0':[False, True]})
    hm = pm.hyps_mask
    print(hm)
    Parameters.check_instantiation(hm)
    Parameters.check_matching(hm, hm['hyps'], hm['cutoffs'])

def test_randomization():
    pm = ParameterHelper(species=['O', 'C', 'H'],
                          kernels=['bond', 'triplet'],
                          allseparate=True,
                          random=True,
                          parameters={'cutoff2b': 7,
                              'cutoff3b': 4.5,
                              'cutoffmb': 3},
                          verbose="debug")
    hm = pm.hyps_mask
    print(hm)
    Parameters.check_instantiation(hm)
    Parameters.check_matching(hm, hm['hyps'], hm['cutoffs'])
    name = pm.find_group('specie', 'O')
    print("find group name for O", name)
    name = pm.find_group('bond', ['O', 'C'])
    print("find group name for O-C", name)

def test_from_dict():
    pm = ParameterHelper(species=['O', 'C', 'H'],
                         kernels=['bond', 'triplet'],
                         allseparate=True,
                         random=True,
                         parameters={'cutoff2b': 7,
                             'cutoff3b': 4.5,
                             'cutoffmb': 3},
                         verbose="debug")
    hm = pm.hyps_mask
    Parameters.check_instantiation(hm)
    Parameters.check_matching(hm, hm['hyps'], hm['cutoffs'])
    print(hm['hyps'])
    print("obtain test hm", hm)

    pm1 = ParameterHelper.from_dict(hm, verbose="debug", init_spec=['O', 'C', 'H'])
    print("from_dict")
    hm1 = pm1.as_dict()
    print(hm['hyps'])
    print(hm1['hyps'][:33], hm1['hyps'][33:])

    Parameters.compare_dict(hm, hm1)

import numpy as np
from numba import njit
from math import exp, floor
from typing import Callable

from flare.kernels.cutoffs import quadratic_cutoff

from time import time

def grid_kernel_2b_sephyps(
    kern_type,
    data,
    grids,
    fj,
    fdj,
    c2,
    etypes2,
    cutoff_2b,
    cutoff_3b,
    cutoff_mb,
    nspec,
    spec_mask,
    nbond,
    bond_mask,
    ntriplet,
    triplet_mask,
    ncut3b,
    cut3b_mask,
    nmb,
    mb_mask,
    sig2,
    ls2,
    sig3,
    ls3,
    sigm,
    lsm,
    cutoff_func=quadratic_cutoff,
):
    """
    Args:
        data: a single env of a list of envs
    """

    bc1 = spec_mask[c2]
    bc2 = spec_mask[etypes2[0]]
    btype = bond_mask[nspec * bc1 + bc2]
    ls = ls2[btype]
    sig = sig2[btype]
    cutoffs = [cutoff_2b[btype]]
    hyps = [sig, ls]

    return grid_kernel_2b(
        bodies, kern_type, get_bonds_func, bonds_cutoff_func, 
        data, grids, fj, fdj, c2, etypes2, hyps, cutoffs, cutoff_func
    )


def grid_kernel_2b(
    kern_type,
    struc,
    grids,
    fj,
    fdj,
    c2,
    etypes2,
    hyps: "ndarray",
    cutoffs,
    cutoff_func: Callable = quadratic_cutoff,
):

    r_cut = cutoffs[0]

    if not isinstance(struc, list):
        struc = [struc]

    kern = 0
    for env in struc:
        kern += grid_kernel_env(
            bodies, kern_type, get_bonds_func, bonds_cutoff_func, 
            env, grids, fj, fdj, c2, etypes2, hyps, r_cut, cutoff_func
        )

    return kern



def grid_kernel_3b_sephyps(
    kern_type,
    data,
    grids,
    fj,
    fdj,
    c2,
    etypes2,
    cutoff_2b,
    cutoff_3b,
    cutoff_mb,
    nspec,
    spec_mask,
    nbond,
    bond_mask,
    ntriplet,
    triplet_mask,
    ncut3b,
    cut3b_mask,
    nmb,
    mb_mask,
    sig2,
    ls2,
    sig3,
    ls3,
    sigm,
    lsm,
    cutoff_func=quadratic_cutoff,
):
    """
    Args:
        data: a single env of a list of envs
    """

    bc1 = spec_mask[c2]
    bc2 = spec_mask[etypes2[0]]
    bc3 = spec_mask[etypes2[1]]
    ttype = triplet_mask[nspec * nspec * bc1 + nspec * bc2 + bc3]
    ls = ls3[ttype]
    sig = sig3[ttype]
    cutoffs = [cutoff_2b, cutoff_3b]  # TODO: check if this is correct

    hyps = [sig, ls]
    return grid_kernel_3b(
        bodies, kern_type, get_bonds_func, bonds_cutoff_func, 
        data, grids, fj, fdj, c2, etypes2, hyps, r_cut, cutoff_func
    )


def grid_kernel_3b(
    bodies,
    kern_type,

    struc,
    grids,
    fj,
    fdj,
    c2,
    etypes2,
    hyps: "ndarray",
    cutoffs,
    cutoff_func: Callable = quadratic_cutoff,
):

    r_cut = cutoffs[1]

    if not isinstance(struc, list):
        struc = [struc]

    kern = 0
    for env in struc:
        kern += grid_kernel_env(
            bodies, kern_type, get_bonds_func, bonds_cutoff_func, 
            env, grids, fj, fdj, c2, etypes2, hyps, r_cut, cutoff_func
        )

    return kern


def grid_kernel_env(
    bodies,
    kern_type,
    get_bonds_func,
    bonds_cutoff_func,
    env1,
    grids,
    fj,
    fdj,
    c2,
    etypes2,
    hyps: "ndarray",
    r_cut: float,
    cutoff_func: Callable = quadratic_cutoff,
):

    # pre-compute constants that appear in the inner loop
    sig = hyps[0]
    ls = hyps[1]
    derivative = derv_dict[kern_type]
    grid_dim = grids.shape[1]

    # collect all the triplets in this training env
    bond_coord_list = get_bonds_func(env1)
#    triplet_coord_list = get_triplets_for_kern(
#        env1.bond_array_3,
#        env1.ctype,
#        env1.etypes,
#        env1.cross_bond_inds,
#        env1.cross_bond_dists,
#        env1.triplet_counts,
#        c2,
#        etypes2,
#    )

    if len(bond_coord_list) == 0:  # no triplets
        if derivative:
            return np.zeros((3, grids.shape[0]), dtype=np.float64)
        else:
            return np.zeros(grids.shape[0], dtype=np.float64)

    bond_coord_list = np.array(bond_coord_list)
    bond_list = bond_coord_list[:, :grid_dim]
    coord_list = bond_coord_list[:, grid_dim:]
    del bond_coord_list

    # calculate distance difference & exponential part
    ls1 = 1 / (2 * ls * ls)
    D = 0
    rij_list = []
    for r in range(grid_dim):
        rj, ri = np.meshgrid(grids[:, r], bond_list[:, r])
        rij = ri - rj
        D += rij * rij  # (n_triplets, n_grids)
        rij_list.append(rij)

    kern_exp = (sig * sig) * np.exp(-D * ls1)
    del D

    # calculate cutoff of the triplets
    fi, fdi = bonds_cutoff_func(
        bond_list, r_cut, coord_list, derivative, cutoff_func
    )  # (n_triplets, 1)
    del bond_list

    # calculate the derivative part
    kern_func = kern_dict[kern_type]
    kern = kern_func(bodies, grid_dim, kern_exp, fi, fj, fdi, fdj, rij_list, coord_list, ls)

    return kern


def en_en(bodies, grid_dim, kern_exp, fi, fj, *args):
    """energy map + energy block"""
    fifj = fi @ fj.T  # (n_triplets, n_grids)
    kern = np.sum(kern_exp * fifj, axis=0) / bodies ** 2  # (n_grids,)
    return kern


def en_force(bodies, grid_dim, kern_exp, fi, fj, fdi, fdj, rij_list, coord_list, ls):
    """energy map + force block"""
    fifj = fi @ fj.T  # (n_triplets, n_grids)
    ls2 = 1 / (ls * ls)
    n_trplt, n_grids = kern_exp.shape
    kern = np.zeros((3, n_grids), dtype=np.float64)
    for d in range(3):
        B = 0
        fdij = fdi[:, [d]] @ fj.T
        for r in range(grid_dim):
            rij = rij_list[r]
            # column-wise multiplication
            # coord_list[:, [r]].shape = (n_triplets, 1)
            B += rij * coord_list[:, [3 * r + d]]  # (n_triplets, n_grids)

        kern[d, :] = (
            -np.sum(kern_exp * (B * ls2 * fifj + fdij), axis=0) / bodies
        )  # (n_grids,)
    return kern




def self_kernel_sephyps(
    grids,
    fj,
    fdj,
    c2,
    etypes2,
    cutoff_2b,
    cutoff_3b,
    cutoff_mb,
    nspec,
    spec_mask,
    nbond,
    bond_mask,
    ntriplet,
    triplet_mask,
    ncut3b,
    cut3b_mask,
    nmb,
    mb_mask,
    sig2,
    ls2,
    sig3,
    ls3,
    sigm,
    lsm,
    cutoff_func=quadratic_cutoff,
):
    """
    Args:
        data: a single env of a list of envs
    """

    bc1 = spec_mask[c2]
    bc2 = spec_mask[etypes2[0]]
    bc3 = spec_mask[etypes2[1]]
    ttype = triplet_mask[nspec * nspec * bc1 + nspec * bc2 + bc3]
    ls = ls3[ttype]
    sig = sig3[ttype]
    cutoffs = [cutoff_2b, cutoff_3b]

    hyps = [sig, ls]
    return self_kernel(
        grids, fj, fdj, c2, etypes2, hyps, cutoffs, cutoff_func
    )


def self_kernel(
    grids,
    fj,
    fdj,
    c2,
    etypes2,
    hyps,
    cutoffs,
    cutoff_func: Callable = quadratic_cutoff,
):

    kern = 0

    # pre-compute constants
    r_cut = cutoffs[1]
    sig = hyps[0]
    ls = hyps[1]
    sig2 = sig * sig
    ls1 = 1 / (2 * ls * ls)
    ls2 = 1 / (ls * ls)
    ls3 = ls2 * ls2

    ej1 = etypes2[0]
    ej2 = etypes2[1]

    perm_list = get_permutations(c2, ej1, ej2, c2, ej1, ej2)
    ci = np.array([1.0, 0.0, 0.0])

    for perm in perm_list:
        perm_grids = np.take(grids, perm, axis=1)
        rij = grids - perm_grids
        D = np.sum(rij * rij, axis=1)  # (n_grids, ) adding up three bonds
        kern_exp = np.exp(-D * ls1) * sig2
        fjfj = fj ** 2
        kern += kern_exp * np.sum(fjfj, axis=1) / 9  # (n_grids,)

    return kern


kern_dict = {
    "energy_energy": en_en,
    "energy_force": en_force,
    "force_energy": force_en,
    "force_force": force_force,
}

derv_dict = {
    "energy_energy": False,
    "energy_force": True,
    "force_energy": False,
    "force_force": True,
}

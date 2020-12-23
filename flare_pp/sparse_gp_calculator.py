from ase.calculators.calculator import Calculator
from _C_flare import SparseGP, Structure
import numpy as np
import time


class SGP_Calculator(Calculator):
    def __init__(self, sgp_model):
        super().__init__()
        self.gp_model = sgp_model
        self.results = {}
        self.use_mapping = False
        self.mgp_model = None

    # TODO: Figure out why this is called twice per MD step.
    def calculate(self, atoms):
        # Convert coded species to 0, 1, 2, etc.
        coded_species = []
        for spec in atoms.coded_species:
            coded_species.append(self.gp_model.species_map[spec])

        # Create structure descriptor.
        structure_descriptor = Structure(
            atoms.cell,
            coded_species,
            atoms.positions,
            self.gp_model.cutoff,
            self.gp_model.descriptor_calculators,
        )

        # Predict on structure.
        if self.gp_model.variance_type == "SOR":
            self.gp_model.sparse_gp.predict_SOR(structure_descriptor)
        elif self.gp_model.variance_type == "DTC":
            self.gp_model.sparse_gp.predict_DTC(structure_descriptor)
        elif self.gp_model.variance_type == "local":
            self.gp_model.sparse_gp.predict_local_uncertainties(structure_descriptor)

        # Set results.
        self.results["energy"] = structure_descriptor.mean_efs[0]
        self.results["forces"] = structure_descriptor.mean_efs[1:-6].reshape(-1, 3)

        # Convert stress to ASE format.
        flare_stress = structure_descriptor.mean_efs[-6:]
        ase_stress = -np.array(
            [
                flare_stress[0],
                flare_stress[3],
                flare_stress[5],
                flare_stress[4],
                flare_stress[2],
                flare_stress[1],
            ]
        )
        self.results["stress"] = ase_stress

        # Report negative variances, which can arise if there are numerical
        # instabilities.
        if (self.gp_model.variance_type == "SOR") or (
            self.gp_model.variance_type == "DTC"
        ):
            variances = structure_descriptor.variance_efs[1:-6]
            stds = np.zeros(len(variances))
            for n in range(len(variances)):
                var = variances[n]
                if var > 0:
                    stds[n] = np.sqrt(var)
                else:
                    stds[n] = -np.sqrt(np.abs(var))
            self.results["stds"] = stds.reshape(-1, 3)
        # The local variance type should only be used if the model uses a
        # single atom-centered descriptor.
        elif (self.gp_model.variance_type == "local"):
            variances = structure_descriptor.local_uncertainties[0]
            stds = np.sqrt(variances)
            stds_full = np.zeros((len(variances), 3))
            stds_full[:, 0] = stds
            self.results["stds"] = stds_full

    def get_property(self, name, atoms=None, allow_calculation=True):
        if name not in self.results.keys():
            if not allow_calculation:
                return None
            self.calculate(atoms)
        return self.results[name]

    def get_potential_energy(self, atoms=None, force_consistent=False):
        return self.get_property("energy", atoms)

    def get_forces(self, atoms):
        return self.get_property("forces", atoms)

    def get_stress(self, atoms):
        return self.get_property("stress", atoms)

    def get_uncertainties(self, atoms):
        return self.get_property("stds", atoms)

    def calculation_required(self, atoms, quantities):
        return True

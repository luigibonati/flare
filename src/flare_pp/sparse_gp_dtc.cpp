#include "sparse_gp_dtc.h"
#include <iostream>

SparseGP_DTC ::SparseGP_DTC() {}

SparseGP_DTC ::SparseGP_DTC(std::vector<Kernel *> kernels, double sigma_e,
                            double sigma_f, double sigma_s)
    : SparseGP(kernels, sigma_e, sigma_f, sigma_s) {

  // Initialize kernel lists.
  Eigen::MatrixXd empty_matrix;
  for (int i = 0; i < kernels.size(); i++) {
    Kuf_env_kernels.push_back(empty_matrix);
    Kuf_struc_energy.push_back(empty_matrix);
    Kuf_struc_force.push_back(empty_matrix);
    Kuf_struc_stress.push_back(empty_matrix);
    Kuu_kernels.push_back(empty_matrix);
  }
}

void SparseGP_DTC ::add_sparse_environments(
    const std::vector<LocalEnvironment> &envs) {

  int n_envs = envs.size();
  int n_sparse = sparse_environments.size();
  int n_kernels = kernels.size();
  int n_labels = Kuf_struc.cols();
  int n_strucs = training_structures.size();

  // Compute kernels between new environment and previous sparse
  // environments.
  std::vector<Eigen::MatrixXd> prev_blocks;
  for (int i = 0; i < n_kernels; i++) {
    prev_blocks.push_back(Eigen::MatrixXd::Zero(n_sparse, n_envs));
  }

#pragma omp parallel for schedule(static)
  for (int k = 0; k < n_envs; k++) {
    for (int i = 0; i < n_sparse; i++) {
      for (int j = 0; j < n_kernels; j++) {
        prev_blocks[j](i, k) +=
            kernels[j]->env_env(sparse_environments[i], envs[k]);
      }
    }
  }

  // Compute self block. (Note that the work can be cut in half by exploiting
  // the symmetry of the matrix, but this makes parallelization slightly
  // trickier.)
  std::vector<Eigen::MatrixXd> self_blocks;
  for (int i = 0; i < n_kernels; i++) {
    self_blocks.push_back(Eigen::MatrixXd::Zero(n_envs, n_envs));
  }

#pragma omp parallel for schedule(static)
  for (int k = 0; k < n_envs; k++) {
    for (int l = 0; l < n_envs; l++) {
      for (int j = 0; j < n_kernels; j++) {
        self_blocks[j](k, l) += kernels[j]->env_env(envs[k], envs[l]);
      }
    }
  }

  // Update Kuu matrices.
  Eigen::MatrixXd self_block = Eigen::MatrixXd::Zero(n_envs, n_envs);
  Eigen::MatrixXd prev_block = Eigen::MatrixXd::Zero(n_sparse, n_envs);
  for (int i = 0; i < n_kernels; i++) {
    Kuu_kernels[i].conservativeResize(n_sparse + n_envs, n_sparse + n_envs);
    Kuu_kernels[i].block(0, n_sparse, n_sparse, n_envs) = prev_blocks[i];
    Kuu_kernels[i].block(n_sparse, 0, n_envs, n_sparse) =
        prev_blocks[i].transpose();
    Kuu_kernels[i].block(n_sparse, n_sparse, n_envs, n_envs) = self_blocks[i];

    self_block += self_blocks[i];
    prev_block += prev_blocks[i];
  }

  Kuu.conservativeResize(n_sparse + n_envs, n_sparse + n_envs);
  Kuu.block(0, n_sparse, n_sparse, n_envs) = prev_block;
  Kuu.block(n_sparse, 0, n_envs, n_sparse) = prev_block.transpose();
  Kuu.block(n_sparse, n_sparse, n_envs, n_envs) = self_block;

  // Compute kernels between new sparse environment and training structures.
  std::vector<Eigen::MatrixXd> energy_kernels, force_kernels, stress_kernels;
  for (int i = 0; i < n_kernels; i++) {
    energy_kernels.push_back(Eigen::MatrixXd::Zero(n_envs, n_energy_labels));
    force_kernels.push_back(Eigen::MatrixXd::Zero(n_envs, n_force_labels));
    stress_kernels.push_back(Eigen::MatrixXd::Zero(n_envs, n_stress_labels));
  }

  // TODO: Check parallel version -- may need to eliminate kernel vector
  // initialization inside the second for loop.
#pragma omp parallel for schedule(static)
  for (int i = 0; i < n_envs; i++) {
    int e_count = 0;
    int f_count = 0;
    int s_count = 0;
    for (int j = 0; j < n_strucs; j++) {
      // Initialize kernel vector.
      int n_atoms = training_structures[j].noa;
      Eigen::VectorXd kernel_vector =
          Eigen::VectorXd::Zero(1 + 3 * n_atoms + 6);

      for (int k = 0; k < n_kernels; k++) {
        kernel_vector = kernels[k]->env_struc(envs[i], training_structures[j]);

        if (training_structures[j].energy.size() != 0) {
          energy_kernels[k](i, e_count) = kernel_vector(0);
          e_count += 1;
        }

        if (training_structures[j].forces.size() != 0) {
          force_kernels[k].row(i).segment(f_count, n_atoms * 3) =
              kernel_vector.segment(1, n_atoms * 3);
          f_count += n_atoms * 3;
        }

        if (training_structures[j].stresses.size() != 0) {
          stress_kernels[k].row(i).segment(s_count, 6) = kernel_vector.tail(6);
          s_count += 6;
        }
      }
    }
  }

  // Update Kuf_struc matrices.
  Eigen::MatrixXd uf_block = Eigen::MatrixXd::Zero(n_envs, n_labels);
  for (int i = 0; i < n_kernels; i++) {
    Kuf_struc_energy[i].conservativeResize(n_sparse + n_envs, n_energy_labels);
    Kuf_struc_force[i].conservativeResize(n_sparse + n_envs, n_force_labels);
    Kuf_struc_stress[i].conservativeResize(n_sparse + n_envs, n_stress_labels);

    Kuf_struc_energy[i].block(n_sparse, 0, n_envs, n_energy_labels) =
        energy_kernels[i];
    Kuf_struc_force[i].block(n_sparse, 0, n_envs, n_force_labels) =
        force_kernels[i];
    Kuf_struc_stress[i].block(n_sparse, 0, n_envs, n_stress_labels) =
        stress_kernels[i];
  }

  // Form full Kuf struc matrix.
  Kuf_struc = Eigen::MatrixXd::Zero(
      n_sparse + n_envs, n_energy_labels + n_force_labels + n_stress_labels);

  for (int i = 0; i < n_kernels; i++) {
    Kuf_struc.block(0, 0, n_sparse + n_envs, n_energy_labels) +=
        Kuf_struc_energy[i];
    Kuf_struc.block(0, n_energy_labels, n_sparse + n_envs, n_force_labels) +=
        Kuf_struc_force[i];
    Kuf_struc.block(0, n_energy_labels + n_force_labels, n_sparse + n_envs,
                    n_stress_labels) += Kuf_struc_stress[i];
  }

  // Store sparse environments.
  for (int i = 0; i < n_envs; i++) {
    sparse_environments.push_back(envs[i]);
  }
}

void SparseGP_DTC ::add_training_structure(
    const StructureDescriptor &training_structure) {

  int n_energy = training_structure.energy.size();
  int n_force = training_structure.forces.size();
  int n_stress = training_structure.stresses.size();
  int n_labels = n_energy + n_force + n_stress;

  int n_atoms = training_structure.noa;
  int n_sparse = sparse_environments.size();
  int n_kernels = kernels.size();

  // Calculate kernels between sparse environments and training structure.
  std::vector<Eigen::MatrixXd> energy_kernels, force_kernels, stress_kernels;

  for (int i = 0; i < n_kernels; i++) {
    energy_kernels.push_back(Eigen::MatrixXd::Zero(n_sparse, n_energy));
    force_kernels.push_back(Eigen::MatrixXd::Zero(n_sparse, n_force));
    stress_kernels.push_back(Eigen::MatrixXd::Zero(n_sparse, n_stress));
  }

  Eigen::MatrixXd kernel_block = Eigen::MatrixXd::Zero(n_sparse, n_labels);

#pragma omp parallel for schedule(static)
  for (int i = 0; i < n_sparse; i++) {
    Eigen::VectorXd kernel_vector = Eigen::VectorXd::Zero(1 + 3 * n_atoms + 6);
    for (int j = 0; j < n_kernels; j++) {
      kernel_vector +=
          kernels[j]->env_struc(sparse_environments[i], training_structure);

      // Store energy, force, and stress kernels.
      if (n_energy > 0) {
        energy_kernels[j](i, 0) = kernel_vector(0);
      }

      if (n_force > 0) {
        force_kernels[j].row(i) = kernel_vector.segment(1, n_atoms * 3);
      }

      if (n_stress > 0) {
        stress_kernels[j].row(i) = kernel_vector.tail(6);
      }
    }
  }

  // Update Kuf kernels.
  for (int i = 0; i < n_kernels; i++) {
    Kuf_struc_energy[i].conservativeResize(n_sparse,
                                           n_energy_labels + n_energy);
    Kuf_struc_force[i].conservativeResize(n_sparse, n_force_labels + n_force);
    Kuf_struc_stress[i].conservativeResize(n_sparse,
                                           n_stress_labels + n_stress);

    Kuf_struc_energy[i].block(0, n_energy_labels, n_sparse, n_energy) =
        energy_kernels[i];
    Kuf_struc_force[i].block(0, n_force_labels, n_sparse, n_force) =
        force_kernels[i];
    Kuf_struc_stress[i].block(0, n_stress_labels, n_sparse, n_stress) =
        stress_kernels[i];
  }

  // Update label count.
  n_energy_labels += n_energy;
  n_force_labels += n_force;
  n_stress_labels += n_stress;

  // Form full Kuf struc matrix.
  Kuf_struc = Eigen::MatrixXd::Zero(n_sparse, n_energy_labels + n_force_labels +
                                                  n_stress_labels);

  for (int i = 0; i < n_kernels; i++) {
    Kuf_struc.block(0, 0, n_sparse, n_energy_labels) += Kuf_struc_energy[i];
    Kuf_struc.block(0, n_energy_labels, n_sparse, n_force_labels) +=
        Kuf_struc_force[i];
    Kuf_struc.block(0, n_energy_labels + n_force_labels, n_sparse,
                    n_stress_labels) += Kuf_struc_stress[i];
  }

  // Store training structure.
  training_structures.push_back(training_structure);

  // Update labels.
  energy_labels.conservativeResize(n_energy_labels);
  force_labels.conservativeResize(n_force_labels);
  stress_labels.conservativeResize(n_stress_labels);

  energy_labels.tail(n_energy) = training_structure.energy;
  force_labels.tail(n_force) = training_structure.forces;
  stress_labels.tail(n_stress) = training_structure.stresses;

  y_struc.conservativeResize(n_energy_labels + n_force_labels +
                             n_stress_labels);
  y_struc.segment(0, n_energy_labels) = energy_labels;
  y_struc.segment(n_energy_labels, n_force_labels) = force_labels;
  y_struc.segment(n_energy_labels + n_force_labels, n_stress_labels) =
      stress_labels;

  // Update noise.
  noise_struc.conservativeResize(n_energy_labels + n_force_labels +
                                 n_stress_labels);
  noise_struc.segment(0, n_energy_labels) =
      Eigen::VectorXd::Constant(n_energy_labels, 1 / (sigma_e * sigma_e));
  noise_struc.segment(n_energy_labels, n_force_labels) =
      Eigen::VectorXd::Constant(n_force_labels, 1 / (sigma_f * sigma_f));
  noise_struc.segment(n_energy_labels + n_force_labels, n_stress_labels) =
      Eigen::VectorXd::Constant(n_stress_labels, 1 / (sigma_s * sigma_s));
}

void SparseGP_DTC ::update_matrices() {
  // Combine Kuf_struc and Kuf_env.
  int n_sparse = Kuf_struc.rows();
  int n_struc_labels = Kuf_struc.cols();
  int n_env_labels = Kuf_env.cols();
  Kuf = Eigen::MatrixXd::Zero(n_sparse, n_struc_labels + n_env_labels);
  Kuf.block(0, 0, n_sparse, n_struc_labels) = Kuf_struc;
  Kuf.block(0, n_struc_labels, n_sparse, n_env_labels) = Kuf_env;

  // Combine noise_struc and noise_env.
  noise_vector = Eigen::VectorXd::Zero(n_struc_labels + n_env_labels);
  noise_vector.segment(0, n_struc_labels) = noise_struc;
  noise_vector.segment(n_struc_labels, n_env_labels) = noise_env;

  // Combine training labels.
  y = Eigen::VectorXd::Zero(n_struc_labels + n_env_labels);
  y.segment(0, n_struc_labels) = y_struc;
  y.segment(n_struc_labels, n_env_labels) = y_env;

  // Calculate Sigma.
  Eigen::MatrixXd sigma_inv =
      Kuu + Kuf * noise_vector.asDiagonal() * Kuf.transpose() +
      Kuu_jitter * Eigen::MatrixXd::Identity(Kuu.rows(), Kuu.cols());

  Sigma = sigma_inv.inverse();

  // Calculate Kuu inverse.
  Kuu_inverse = Kuu.inverse();

  // Calculate alpha.
  alpha = Sigma * Kuf * noise_vector.asDiagonal() * y;
}

void SparseGP_DTC ::predict_DTC(
    StructureDescriptor test_structure, Eigen::VectorXd &mean_vector,
    Eigen::VectorXd &variance_vector,
    std::vector<Eigen::VectorXd> &mean_contributions) {

  int n_atoms = test_structure.noa;
  int n_out = 1 + 3 * n_atoms + 6;
  int n_sparse = sparse_environments.size();
  int n_kernels = kernels.size();

  // Store kernel matrices for each kernel.
  std::vector<Eigen::MatrixXd> kern_mats;
  for (int i = 0; i < n_kernels; i++) {
    kern_mats.push_back(Eigen::MatrixXd::Zero(n_out, n_sparse));
  }
  Eigen::MatrixXd kern_mat = Eigen::MatrixXd::Zero(n_out, n_sparse);

// Compute the kernel between the test structure and each sparse
// environment, parallelizing over environments.
#pragma omp parallel for schedule(static)
  for (int i = 0; i < n_sparse; i++) {
    for (int j = 0; j < n_kernels; j++) {
      kern_mats[j].col(i) +=
          kernels[j]->env_struc(sparse_environments[i], test_structure);
    }
  }

  // Sum the kernels.
  for (int i = 0; i < n_kernels; i++) {
    kern_mat += kern_mats[i];
  }

  // Compute mean contributions and total mean prediction.
  mean_contributions = std::vector<Eigen::VectorXd>{};
  for (int i = 0; i < n_kernels; i++) {
    mean_contributions.push_back(kern_mats[i] * alpha);
  }

  mean_vector = kern_mat * alpha;

  // Compute variances.
  Eigen::VectorXd V_SOR, Q_self, K_self = Eigen::VectorXd::Zero(n_out);

  // Note: Calculation of the self-kernel can be parallelized.
  for (int i = 0; i < n_kernels; i++) {
    K_self += kernels[i]->self_kernel_struc(test_structure);
  }

  Q_self = (kern_mat * Kuu_inverse * kern_mat.transpose()).diagonal();
  V_SOR = (kern_mat * Sigma * kern_mat.transpose()).diagonal();

  variance_vector = K_self - Q_self + V_SOR;
}

void SparseGP_DTC ::compute_DTC_likelihood() {
  int n_train = Kuf.cols();

  Eigen::MatrixXd Qff_plus_lambda =
      Kuf.transpose() * Kuu_inverse * Kuf +
      noise_vector.asDiagonal() * Eigen::MatrixXd::Identity(n_train, n_train);

  double Q_det = Qff_plus_lambda.determinant();
  Eigen::MatrixXd Q_inv = Qff_plus_lambda.inverse();

  double half = 1.0 / 2.0;
  complexity_penalty = -half * log(Q_det);
  data_fit = -half * y.transpose() * Q_inv * y;
  constant_term = -half * n_train * log(2 * M_PI);
  log_marginal_likelihood = complexity_penalty + data_fit + constant_term;
}

void SparseGP_DTC ::compute_VFE_likelihood() {}

double compute_likelihood(const SparseGP_DTC &sparse_gp,
                          const Eigen::VectorXd &hyperparameters) {

  // Construct transformed Kuu and Kuf matrices.
  int n_kernels = sparse_gp.kernels.size();
  int n_sparse = sparse_gp.Kuf_struc.rows();
  int n_labels = sparse_gp.Kuf_struc.cols();
  int n_energy_labels = sparse_gp.n_energy_labels;
  int n_force_labels = sparse_gp.n_force_labels;
  int n_stress_labels = sparse_gp.n_stress_labels;

  Eigen::MatrixXd Kuu = Eigen::MatrixXd::Zero(n_sparse, n_sparse);
  Eigen::MatrixXd Kuf = Eigen::MatrixXd::Zero(n_sparse, n_labels);

  int n_hyps, hyp_index = 0;
  Eigen::VectorXd hyps_curr;

  for (int i = 0; i < n_kernels; i++) {
    n_hyps = sparse_gp.kernels[i]->kernel_hyperparameters.size();
    hyps_curr = hyperparameters.segment(hyp_index, n_hyps);

    Kuu += sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuu_kernels[i],
                                                  hyps_curr);

    Kuf.block(0, 0, n_sparse, n_energy_labels) +=
        sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuf_struc_energy[i],
                                               hyps_curr);
    Kuf.block(0, n_energy_labels, n_sparse, n_force_labels) +=
        sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuf_struc_force[i],
                                               hyps_curr);
    Kuf.block(0, n_energy_labels + n_force_labels, n_sparse, n_stress_labels) +=
        sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuf_struc_stress[i],
                                               hyps_curr);

    hyp_index += n_hyps;
  }

  Eigen::MatrixXd Kuu_inverse = Kuu.inverse();

  // Construct updated noise vector.
  Eigen::VectorXd noise_vector = Eigen::VectorXd::Zero(
      n_energy_labels + n_force_labels + n_stress_labels);
  double sigma_e = hyperparameters(hyp_index);
  double sigma_f = hyperparameters(hyp_index + 1);
  double sigma_s = hyperparameters(hyp_index + 2);

  noise_vector.segment(0, n_energy_labels) =
      Eigen::VectorXd::Constant(n_energy_labels, 1 / (sigma_e * sigma_e));
  noise_vector.segment(n_energy_labels, n_force_labels) =
      Eigen::VectorXd::Constant(n_force_labels, 1 / (sigma_f * sigma_f));
  noise_vector.segment(n_energy_labels + n_force_labels, n_stress_labels) =
      Eigen::VectorXd::Constant(n_stress_labels, 1 / (sigma_s * sigma_s));

  // Compute likelihood.
  Eigen::MatrixXd Qff_plus_lambda =
      Kuf.transpose() * Kuu_inverse * Kuf +
      noise_vector.asDiagonal() * Eigen::MatrixXd::Identity(n_labels, n_labels);

  double Q_det = Qff_plus_lambda.determinant();
  Eigen::MatrixXd Q_inv = Qff_plus_lambda.inverse();

  double half = 1.0 / 2.0;
  double complexity_penalty = -half * log(Q_det);
  double data_fit = -half * sparse_gp.y.transpose() * Q_inv * sparse_gp.y;
  double constant_term = -half * n_labels * log(2 * M_PI);
  double log_marginal_likelihood =
    complexity_penalty + data_fit + constant_term;

  return log_marginal_likelihood;
}

double compute_likelihood_gradient(const SparseGP_DTC &sparse_gp,
                                   const Eigen::VectorXd &hyperparameters,
                                   Eigen::VectorXd &like_grad){

  // Compute Kuu and Kuf gradients.
  int n_kernels = sparse_gp.kernels.size();
  int n_sparse = sparse_gp.Kuf_struc.rows();
  int n_labels = sparse_gp.Kuf_struc.cols();
  int n_energy_labels = sparse_gp.n_energy_labels;
  int n_force_labels = sparse_gp.n_force_labels;
  int n_stress_labels = sparse_gp.n_stress_labels;
  int n_hyps_total = sparse_gp.hyperparameters.size();

  Eigen::MatrixXd Kuu = Eigen::MatrixXd::Zero(n_sparse, n_sparse);
  Eigen::MatrixXd Kuf = Eigen::MatrixXd::Zero(n_sparse, n_labels);

  std::vector<Eigen::MatrixXd> Kuu_grad, e_grad, f_grad, s_grad,
    Kuu_grads, Kuf_grads;

  int n_hyps, hyp_index = 0, grad_index = 0;
  Eigen::VectorXd hyps_curr;

  for (int i = 0; i < n_kernels; i++) {
    n_hyps = sparse_gp.kernels[i]->kernel_hyperparameters.size();
    hyps_curr = hyperparameters.segment(hyp_index, n_hyps);

    Kuu_grad = sparse_gp.kernels[i]->
        kernel_gradient(sparse_gp.Kuu_kernels[i], hyps_curr);

    e_grad = sparse_gp.kernels[i]->
        kernel_gradient(sparse_gp.Kuf_struc_energy[i], hyps_curr);
    f_grad = sparse_gp.kernels[i]->
        kernel_gradient(sparse_gp.Kuf_struc_force[i], hyps_curr);
    s_grad = sparse_gp.kernels[i]->
        kernel_gradient(sparse_gp.Kuf_struc_stress[i], hyps_curr);
    
    for (int j = 0; j < n_hyps; j ++){
        Kuu_grads.push_back(Kuu_grad[j]);
        Kuf_grads.push_back(Eigen::MatrixXd::Zero(n_sparse, n_labels));

        Kuf_grads[grad_index].block(0, 0, n_sparse, n_energy_labels) += 
            e_grad[j];
        Kuf_grads[grad_index].block(0, n_energy_labels, n_sparse,
            n_force_labels) += f_grad[j];
        Kuf_grads[grad_index].block(0, n_energy_labels + n_force_labels,
            n_sparse, n_stress_labels) += s_grad[j];
        
        grad_index ++;
    }

    Kuu += sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuu_kernels[i],
                                                  hyps_curr);

    Kuf.block(0, 0, n_sparse, n_energy_labels) +=
        sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuf_struc_energy[i],
                                               hyps_curr);
    Kuf.block(0, n_energy_labels, n_sparse, n_force_labels) +=
        sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuf_struc_force[i],
                                               hyps_curr);
    Kuf.block(0, n_energy_labels + n_force_labels, n_sparse, n_stress_labels) +=
        sparse_gp.kernels[i]->kernel_transform(sparse_gp.Kuf_struc_stress[i],
                                               hyps_curr);

    hyp_index += n_hyps;
  }

  Eigen::MatrixXd Kuu_inverse = Kuu.inverse();

  // Construct updated noise vector.
  Eigen::VectorXd noise_vector = Eigen::VectorXd::Zero(
      n_energy_labels + n_force_labels + n_stress_labels);
  double sigma_e = hyperparameters(hyp_index);
  double sigma_f = hyperparameters(hyp_index + 1);
  double sigma_s = hyperparameters(hyp_index + 2);

  noise_vector.segment(0, n_energy_labels) =
      Eigen::VectorXd::Constant(n_energy_labels, 1 / (sigma_e * sigma_e));
  noise_vector.segment(n_energy_labels, n_force_labels) =
      Eigen::VectorXd::Constant(n_force_labels, 1 / (sigma_f * sigma_f));
  noise_vector.segment(n_energy_labels + n_force_labels, n_stress_labels) =
      Eigen::VectorXd::Constant(n_stress_labels, 1 / (sigma_s * sigma_s));

  // Compute Qff grads.
  std::vector<Eigen::MatrixXd> Qff_grads;
  grad_index = 0;
  for (int i = 0; i < n_kernels; i++){
      n_hyps = sparse_gp.kernels[i]->kernel_hyperparameters.size();
      for (int j = 0; j < n_hyps; j ++){
        Qff_grads.push_back(
            Kuf_grads[grad_index].transpose() * Kuu_inverse * Kuf -
            Kuf.transpose() * Kuu_inverse * Kuu_grads[grad_index] *
                Kuu_inverse * Kuf +
            Kuf.transpose() * Kuu_inverse * Kuf_grads[grad_index]);

        grad_index ++;
    }
  }

  // Push back noise gradients.
  Eigen::VectorXd e_noise_grad = Eigen::VectorXd::Zero(n_labels);
  Eigen::VectorXd f_noise_grad = Eigen::VectorXd::Zero(n_labels);
  Eigen::VectorXd s_noise_grad = Eigen::VectorXd::Zero(n_labels);

  e_noise_grad.segment(0, n_energy_labels) =
    Eigen::VectorXd::Constant(
        n_energy_labels, -2 / (sigma_e * sigma_e * sigma_e));
  f_noise_grad.segment(n_energy_labels, n_force_labels) =
    Eigen::VectorXd::Constant(
        n_force_labels, -2 / (sigma_f * sigma_f * sigma_f));
  s_noise_grad.segment(n_energy_labels + n_force_labels, n_stress_labels) =
    Eigen::VectorXd::Constant(
        n_stress_labels, -2 / (sigma_s * sigma_s * sigma_s));

  Qff_grads.push_back(e_noise_grad.asDiagonal() *
                      Eigen::MatrixXd::Identity(n_labels, n_labels));
  Qff_grads.push_back(f_noise_grad.asDiagonal() *
                      Eigen::MatrixXd::Identity(n_labels, n_labels));
  Qff_grads.push_back(s_noise_grad.asDiagonal() *
                      Eigen::MatrixXd::Identity(n_labels, n_labels));

  // Compute likelihood.
  Eigen::MatrixXd Qff_plus_lambda =
      Kuf.transpose() * Kuu_inverse * Kuf +
      noise_vector.asDiagonal() * Eigen::MatrixXd::Identity(n_labels, n_labels);

  double Q_det = Qff_plus_lambda.determinant();
  Eigen::MatrixXd Q_inv = Qff_plus_lambda.inverse();

  double half = 1.0 / 2.0;
  double complexity_penalty = -half * log(Q_det);
  double data_fit = -half * sparse_gp.y.transpose() * Q_inv * sparse_gp.y;
  double constant_term = -half * n_labels * log(2 * M_PI);
  double log_marginal_likelihood =
    complexity_penalty + data_fit + constant_term;

  // Compute likelihood gradient.
  like_grad = Eigen::VectorXd::Zero(n_hyps_total);
  for (int i = 0; i < n_hyps_total; i ++){
      like_grad(i) =
        -half * (Q_inv * Qff_grads[i]).trace() +
        half * sparse_gp.y.transpose() * Q_inv * Qff_grads[i] * Q_inv *
            sparse_gp.y;
  }

  return log_marginal_likelihood;
}

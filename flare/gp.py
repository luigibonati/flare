"""Gaussian process model of the Born Oppenheimer potential energy surface."""
import math
from typing import List, Callable
import numpy as np
from scipy.linalg import solve_triangular
from scipy.optimize import minimize
from flare.env import AtomicEnvironment
from flare.struc import Structure
from flare.gp_algebra import get_ky_and_hyp, get_like_grad_from_mats, \
    get_neg_likelihood, get_neg_like_grad, get_ky_and_hyp_par
from flare.kernels import str_to_kernel
from flare.mc_simple import str_to_mc_kernel


class GaussianProcess:
    """ Gaussian Process Regression Model.

    Implementation is based on Algorithm 2.1 (pg. 19) of
    "Gaussian Processes for Machine Learning" by Rasmussen and Williams"""

    def __init__(self, kernel: Callable,
                 kernel_grad: Callable, hyps,
                 cutoffs,
                 hyp_labels: List = None,
                 energy_force_kernel: Callable = None,
                 energy_kernel: Callable = None,
                 opt_algorithm: str = 'L-BFGS-B',
                 opt_params: dict = None,
                 maxiter=10, par: bool=False,
                 output=None):
        """Initialize GP parameters and training data."""

        self.kernel = kernel
        self.kernel_grad = kernel_grad
        self.energy_kernel = energy_kernel
        self.energy_force_kernel = energy_force_kernel
        self.kernel_name = kernel.__name__
        self.hyps = hyps
        self.hyp_labels = hyp_labels
        self.cutoffs = cutoffs
        self.algo = opt_algorithm
        self.opt_params = opt_params if opt_params is not None else {}

        self.training_data = []
        self.training_labels = []
        self.training_labels_np = np.empty(0, )
        self.maxiter = maxiter
        self.par = par
        self.output = output

        # Parameters set during training
        self.ky_mat = None
        self.l_mat = None
        self.alpha = None
        self.ky_mat_inv = None
        self.l_mat_inv = None
        self.likelihood = None
        self.likelihood_gradient = None

    # TODO unit test custom range
    def update_db(self, struc: Structure, forces: list,
                  custom_range: List[int] = ()):
        """Given structure and forces, add to training set.

        :param struc: structure to add to db
        :type struc: Structure
        :param forces: list of corresponding forces to add to db
        :type forces: list<float>
        :param custom_range: Indices to use in lieu of the whole structure
        :type custom_range: List[int]
        """

        # By default, use all atoms in the structure
        noa = len(struc.positions)
        update_indices = custom_range or list(range(noa))

        for atom in update_indices:
            env_curr = AtomicEnvironment(struc, atom, self.cutoffs)
            forces_curr = np.array(forces[atom])

            self.training_data.append(env_curr)
            self.training_labels.append(forces_curr)

        # create numpy array of training labels
        self.training_labels_np = self.force_list_to_np(self.training_labels)

    def add_one_env(self, env: AtomicEnvironment,
                    force, train: bool = False, **kwargs):
        """
        Tool to add a single environment / force pair into the training set.

        :param force:
        :param env:
        :param force: (x,y,z) component associated with environment
        :param train:
        :return:
        """
        self.training_data.append(env)
        self.training_labels.append(force)
        self.training_labels_np = self.force_list_to_np(self.training_labels)

        if train:
            self.train(**kwargs)

    @staticmethod
    def force_list_to_np(forces: list):
        """ Convert list of forces to numpy array of forces.

        :param forces: list of forces to convert
        :type forces: list<float>
        :return: numpy array forces
        :rtype: np.ndarray
        """
        forces_np = []

        for force in forces:
            for force_comp in force:
                forces_np.append(force_comp)

        forces_np = np.array(forces_np)

        return forces_np

    def train(self, output=None, opt_param_override: dict = None):
        """Train Gaussian Process model on training data. Tunes the \
hyperparameters to maximize the likelihood, then computes L and alpha \
(related to the covariance matrix of the training set)."""

        x_0 = self.hyps

        args = (self.training_data, self.training_labels_np,
                self.kernel_grad, self.cutoffs, output,
                self.par)
        res = None

        # Make local copy of opt params so as to not overwrite with override
        opt_param_temp = dict(self.opt_params)
        if opt_param_override is not None:
            for key, value in opt_param_override.items():
                opt_param_temp[key] = value

        grad_tol = opt_param_temp.get('grad_tol', 1e-4)
        x_tol = opt_param_temp.get('x_tol', 1e-5)
        line_steps = opt_param_temp.get('maxls', 20)
        max_iter = opt_param_temp.get('maxiter', self.maxiter)
        algo = opt_param_temp.get('algorithm', self.algo)
        disp = opt_param_temp.get('disp', False)


        if algo == 'L-BFGS-B':

            # bound signal noise below to avoid overfitting
            bounds = np.array([(1e-6, np.inf)] * len(x_0))
            # bounds = np.array([(1e-6, np.inf)] * len(x_0))
            # bounds[-1] = [1e-6,np.inf]
            # Catch linear algebra errors and switch to BFGS if necessary
            try:
                res = minimize(get_neg_like_grad, x_0, args,
                               method='L-BFGS-B', jac=True, bounds=bounds,
                               options={'disp': disp, 'gtol': grad_tol,
                                        'maxls': line_steps,
                                        'maxiter': max_iter})
            except:
                print("Warning! Algorithm for L-BFGS-B failed. Changing to "
                      "BFGS for remainder of run.")
                self.opt_params['algorithm'] = 'BFGS'
                algo = 'BFGS'

        if opt_param_temp.get('custom_bounds', None) is not None:
            res = minimize(get_neg_like_grad, x_0, args,
                           method='L-BFGS-B', jac=True,
                           bounds=opt_param_temp.get('custom_bonuds'),
                           options={'disp': disp, 'gtol': grad_tol,
                                    'maxls': line_steps,
                                    'maxiter': max_iter})

        elif algo == 'BFGS':
            res = minimize(get_neg_like_grad, x_0, args,
                           method='BFGS', jac=True,
                           options={'disp': disp, 'gtol': grad_tol,
                                    'maxiter': max_iter})

        elif algo == 'nelder-mead':
            res = minimize(get_neg_likelihood, x_0, args,
                           method='nelder-mead',
                           options={'disp': disp,
                                    'maxiter': max_iter,
                                    'xtol': x_tol})
        if res is None:
            raise RuntimeError("Optimization failed for unknown reason.")
        self.hyps = res.x
        self.set_L_alpha()
        self.likelihood = -res.fun
        self.likelihood_gradient = -res.jac

    def predict(self, x_t: AtomicEnvironment, d: int) -> [float, float]:
        """Predict force component of an atomic environment and its \
uncertainty."""

        # Kernel vector allows for evaluation of At. Env.
        k_v = self.get_kernel_vector(x_t, d)

        # Guarantee that alpha is up to date with training set
        if self.alpha is None or 3 * len(self.training_data) != len(
                self.alpha):
            self.set_L_alpha()

        # get predictive mean
        pred_mean = np.matmul(k_v, self.alpha)

        # get predictive variance without cholesky (possibly faster)
        self_kern = self.kernel(x_t, x_t, d, d, self.hyps,
                                self.cutoffs)
        pred_var = self_kern - \
            np.matmul(np.matmul(k_v, self.ky_mat_inv), k_v)

        return pred_mean, pred_var

    def predict_local_energy(self, x_t: AtomicEnvironment) -> float:
        """Predict the local energy of an atomic environment.

        :param x_t: Atomic environment of test atom.
        :type x_t: AtomicEnvironment
        :return: local energy in eV (up to a constant).
        :rtype: float
        """

        k_v = self.en_kern_vec(x_t)
        pred_mean = np.matmul(k_v, self.alpha)

        return pred_mean

    def predict_local_energy_and_var(self, x_t: AtomicEnvironment):
        """Predict the local energy of an atomic environment and its \
uncertainty."""

        # get kernel vector
        k_v = self.en_kern_vec(x_t)

        # get predictive mean
        pred_mean = np.matmul(k_v, self.alpha)

        # get predictive variance
        v_vec = solve_triangular(self.l_mat, k_v, lower=True)
        self_kern = self.energy_kernel(x_t, x_t, self.hyps,
                                       self.cutoffs)
        pred_var = self_kern - np.matmul(v_vec, v_vec)

        return pred_mean, pred_var

    def get_kernel_vector(self, x: AtomicEnvironment,
                          d_1: int):
        """
        Compute kernel vector, comparing input environment to all environments
        in the GP's training set.

        :param x: data point to compare against kernel matrix
        :type x: AtomicEnvironment
        :param d_1: Cartesian component of force vector to get (1=x,2=y,3=z)
        :type d_1: int
        :return: kernel vector
        :rtype: np.ndarray
        """

        ds = [1, 2, 3]
        size = len(self.training_data) * 3
        k_v = np.zeros(size, )

        for m_index in range(size):
            x_2 = self.training_data[int(math.floor(m_index / 3))]
            d_2 = ds[m_index % 3]
            k_v[m_index] = self.kernel(x, x_2, d_1, d_2,
                                       self.hyps, self.cutoffs)
        return k_v

    def en_kern_vec(self, x: AtomicEnvironment):
        """Compute the vector of energy/force kernels between an atomic \
environment and the environments in the training set."""

        ds = [1, 2, 3]
        size = len(self.training_data) * 3
        k_v = np.zeros(size, )

        for m_index in range(size):
            x_2 = self.training_data[int(math.floor(m_index / 3))]
            d_2 = ds[m_index % 3]
            k_v[m_index] = self.energy_force_kernel(x_2, x, d_2,
                                                    self.hyps, self.cutoffs)

        return k_v

    def set_L_alpha(self):
        """
        Invert the covariance matrix, setting L (a lower triangular
        matrix s.t. L L^T = (K + sig_n^2 I) ) and alpha, the inverse
        covariance matrix multiplied by the vector of training labels.
        The forces and variances are later obtained using alpha.
        :return:
        """
        if self.par:
            hyp_mat, ky_mat = \
                get_ky_and_hyp_par(self.hyps, self.training_data,
                                   self.training_labels_np,
                                   self.kernel_grad, self.cutoffs)
        else:
            hyp_mat, ky_mat = \
                get_ky_and_hyp(self.hyps, self.training_data,
                               self.training_labels_np,
                               self.kernel_grad, self.cutoffs)

        like, like_grad = \
            get_like_grad_from_mats(ky_mat, hyp_mat, self.training_labels_np)
        l_mat = np.linalg.cholesky(ky_mat)
        l_mat_inv = np.linalg.inv(l_mat)
        ky_mat_inv = l_mat_inv.T @ l_mat_inv
        alpha = np.matmul(ky_mat_inv, self.training_labels_np)

        self.ky_mat = ky_mat
        self.l_mat = l_mat
        self.alpha = alpha
        self.ky_mat_inv = ky_mat_inv
        self.l_mat_inv = l_mat_inv

        self.likelihood = like
        self.likelihood_gradient = like_grad

    def update_L_alpha(self):
        """
        Update the GP's L matrix and alpha vector.
        """

        # Set L matrix and alpha if set_L_alpha has not been called yet
        if self.l_mat is None:
            self.set_L_alpha()
            return

        n = self.l_mat_inv.shape[0]
        N = len(self.training_data)
        m = N - n // 3  # number of new data added
        ky_mat = np.zeros((3 * N, 3 * N))
        ky_mat[:n, :n] = self.ky_mat
        # calculate kernels for all added data
        for i in range(m):
            ind = n // 3 + i
            x_t = self.training_data[ind]
            k_vi = np.array([self.get_kernel_vector(x_t, d + 1)
                             for d in range(3)]).T  # (n+3m) x 3
            ky_mat[:, 3 * ind:3 * ind + 3] = k_vi
            ky_mat[3 * ind:3 * ind + 3, :n] = k_vi[:n, :].T
        sigma_n = self.hyps[-1]
        ky_mat[n:, n:] += sigma_n ** 2 * np.eye(3 * m)

        l_mat = np.linalg.cholesky(ky_mat)
        l_mat_inv = np.linalg.inv(l_mat)
        ky_mat_inv = l_mat_inv.T @ l_mat_inv
        alpha = np.matmul(ky_mat_inv, self.training_labels_np)

        self.ky_mat = ky_mat
        self.l_mat = l_mat
        self.alpha = alpha
        self.ky_mat_inv = ky_mat_inv
        self.l_mat_inv = l_mat_inv

    def __str__(self):
        """String representation of the GP model."""

        thestr = "GaussianProcess Object\n"
        thestr += 'Kernel: {}\n'.format(self.kernel_name)
        thestr += "Training points: {}\n".format(len(self.training_data))
        thestr += 'Cutoffs: {}\n'.format(self.cutoffs)
        thestr += 'Model Likelihood: {}\n'.format(self.likelihood)

        thestr += 'Hyperparameters: \n'
        if self.hyp_labels is None:
            # Put unlabeled hyperparameters on one line
            thestr = thestr[:-1]
            thestr += str(self.hyps) + '\n'
        else:
            for hyp, label in zip(self.hyps, self.hyp_labels):
                thestr += "{}: {}\n".format(label, hyp)

        return thestr

    def as_dict(self):
        """Dictionary representation of the GP model."""

        out_dict = dict(vars(self))

        out_dict['training_data'] = [env.as_dict() for env in
                                     self.training_data]
        # Remove the callables
        del out_dict['kernel']
        del out_dict['kernel_grad']

        return out_dict

    @staticmethod
    def from_dict(dictionary):
        """Create GP object from dictionary representation."""

        if 'mc' in dictionary['kernel_name']:
            force_kernel, grad = \
                str_to_mc_kernel(dictionary['kernel_name'], include_grad=True)
        else:
            force_kernel, grad = str_to_kernel(dictionary['kernel_name'],
                                               include_grad=True)

        if dictionary['energy_kernel'] is not None:
            energy_kernel = str_to_kernel(dictionary['energy_kernel'])
        else:
            energy_kernel = None

        if dictionary['energy_force_kernel'] is not None:
            energy_force_kernel = \
                str_to_kernel(dictionary['energy_force_kernel'])
        else:
            energy_force_kernel = None

        new_gp = GaussianProcess(kernel=force_kernel,
                                 kernel_grad=grad,
                                 energy_kernel=energy_kernel,
                                 energy_force_kernel=energy_force_kernel,
                                 cutoffs=np.array(dictionary['cutoffs']),
                                 hyps=np.array(dictionary['hyps']),
                                 hyp_labels=dictionary['hyp_labels'],
                                 par=dictionary['par'],
                                 maxiter=dictionary['maxiter'],
                                 opt_params=dictionary['opt_params'],
                                 opt_algorithm=dictionary['algo'])

        # Save time by attempting to load in computed attributes
        new_gp.l_mat = np.array(dictionary.get('l_mat', None))
        new_gp.l_mat_inv = np.array(dictionary.get('l_mat_inv', None))
        new_gp.alpha = np.array(dictionary.get('alpha', None))
        new_gp.ky_mat = np.array(dictionary.get('ky_mat', None))
        new_gp.ky_mat_inv = np.array(dictionary.get('ky_mat_inv', None))

        new_gp.training_data = [AtomicEnvironment.from_dict(env) for env in
                                dictionary['training_data']]
        new_gp.training_labels = dictionary['training_labels']

        new_gp.likelihood = dictionary['likelihood']
        new_gp.likelihood_gradient = dictionary['likelihood_gradient']

        return new_gp

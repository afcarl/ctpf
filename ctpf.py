"""

User-Artist-Song Poisson matrix factorization with Batch inference

CREATED: 2014-03-25 02:06:52 by Dawen Liang <dliang@ee.columbia.edu>

MODIFIED: 2015-03-25 13:06:12 by Jaan Altosaar <altosaar@princeton.edu>

"""

import sys
import numpy as np
from scipy import sparse, special, weave
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
import logging

class PoissonMF(BaseEstimator, TransformerMixin):
    ''' Poisson matrix factorization with batch inference '''
    def __init__(self, n_components=100, max_iter=100, min_iter=1, tol=0.0001,
                 smoothness=100, random_state=None, verbose=False,
                 beta=False, theta=False,
                 categorywise=False,
                 item_fit_type='all_categories',
                 user_fit_type='default',
                 observed_item_attributes=False,
                 observed_user_preferences=False,
                 zero_untrained_components=False,
                 **kwargs):

        self.n_components = n_components
        self.max_iter = max_iter
        self.tol = tol
        self.min_iter = min_iter
        self.smoothness = smoothness
        self.random_state = random_state
        self.verbose = verbose
        self.max_iter_fixed = 4
        self.observed_user_preferences = observed_user_preferences
        self.observed_item_attributes = observed_item_attributes
        self.categorywise = categorywise
        self.zero_untrained_components = zero_untrained_components
        self.item_fit_type = item_fit_type
        self.user_fit_type = user_fit_type
        self.observed_item_corrections = False

        if observed_user_preferences:
            self.Et = theta
        if observed_item_attributes:
            self.Eb = beta
        if categorywise:
            if not type(beta) == np.ndarray:
                raise Exception('need observed categories for categorywise')

        if type(self.random_state) is int:
            np.random.seed(self.random_state)
        elif self.random_state is not None:
            np.random.setstate(self.random_state)

        self._parse_args(**kwargs)
        self.logger = logging.getLogger(__name__)


    def _parse_args(self, **kwargs):
        self.a = float(kwargs.get('a', 0.1))
        self.b = float(kwargs.get('b', 0.1))
        self.c = float(kwargs.get('c', 0.1))
        self.d = float(kwargs.get('d', 0.1))
        self.f = float(kwargs.get('f', 0.1))
        self.g = float(kwargs.get('g', 0.1))
        # self.song2artist = np.array(kwargs.get('s2a', None))
        # self.artist2songs = dict()
        # self.n_item_corrections = len(np.unique(self.song2artist))
        # for artist in range(0,self.n_item_corrections):
        #     #self.artist2songs[artist]=np.where(self.song2artist==artist)[0]
        #     self.artist2songs[artist]=np.array([artist])
        # self.n_songs_by_artist = np.reshape(np.array([self.artist2songs[artist].size for artist in range(self.n_item_corrections)]).astype(np.float32),(self.n_item_corrections,1))
        # #self.artist_indicator = pd.get_dummies(self.song2artist).T
        # #self.artist_indicator = sparse.csr_matrix(self.artist_indicator.values)
        # self.artist_indicator = sparse.identity(self.n_item_corrections, format='csr')

    def _init_users(self, n_users):
        # if we pass in observed thetas:
        if self.observed_user_preferences:
            self.logger.info('initializing theta (user prefs) to be the observed one')
            self.Elogt = None
            self.gamma_t = None
            self.rho_t = None
        else: # proceed normally
            # variational parameters for theta
            self.logger.info('initializing theta (user prefs) normally from gamma')
            self.gamma_t = self.smoothness * \
                np.random.gamma(self.smoothness, 1. / self.smoothness,
                                size=(self.n_components, n_users)
                                ).astype(np.float32)
            self.rho_t = self.smoothness * \
                np.random.gamma(self.smoothness, 1. / self.smoothness,
                                size=(self.n_components, n_users)
                                ).astype(np.float32)
            self.Et, self.Elogt = _compute_expectations(self.gamma_t, self.rho_t)

    def _init_items(self, n_items):
        # if we pass in observed betas:
        if self.observed_item_attributes:
            self.logger.info('initializing beta to be the observed one')
            self.Elogb = None
            self.gamma_bs = None
            self.rho_bs = None
        else: # proceed normally
            # variational parameters for beta_songs (beta_s)
            self.logger.info('initializing items normally from gamma')
            self.gamma_bs = 0.01 * self.smoothness * \
                np.random.gamma(self.smoothness, 1. / self.smoothness,
                                size=(n_items, self.n_components)
                                ).astype(np.float32)
            self.rho_bs = 0.01 * self.smoothness * \
                np.random.gamma(self.smoothness, 1. / self.smoothness,
                                size=(n_items, self.n_components)
                                ).astype(np.float32)
            self.Eb, self.Elogb = _compute_expectations(self.gamma_bs, self.rho_bs)

    def _init_item_corrections(self, n_items):
        self.logger.info('initializing item_corrections normally from gamma')
        # variational parameters for epsilon corrections
        self.gamma_eps = self.smoothness * \
            np.random.gamma(self.smoothness, 1. / self.smoothness,
                            size=(n_items, self.n_components)
                            ).astype(np.float32)
        self.rho_eps = self.smoothness * \
            np.random.gamma(self.smoothness, 1. / self.smoothness,
                            size=(n_items, self.n_components)
                            ).astype(np.float32)
        self.Eeps, self.Elogeps = _compute_expectations(self.gamma_eps, self.rho_eps)

    def fit(self, X, rows, cols, vad):
        '''Fit the model to the data in X.

        Parameters
        ----------
        X : array-like, shape (n_songs, n_users)
            Training data.

        Returns
        -------
        self: object
            Returns the instance itself.
        '''
        n_items, n_users = X.shape
        self.n_users = n_users
        self._init_items(n_items)
        self._init_users(n_users)
        self._init_item_corrections(n_items)
        if self.user_fit_type == 'converge_separately':
            best_validation_ll = -np.inf
            for switch_idx in xrange(self.max_iter_fixed):
                if switch_idx % 2 == 0:
                    update_users_or_corrections = 'items'
                    if switch_idx % 4 == 0:
                        update_categories = 'in_category'
                    else:
                        update_categories = 'out_category'
                else:
                    update_users_or_corrections = 'users'
                    self.observed_item_corrections = False
                if switch_idx == 1:
                    initialize_users = 'initialize'
                else:
                    initialize_users = 'none'
                self.logger.info('=> only updating {}, switch number {}'
                    .format(update_users_or_corrections, switch_idx))
                validation_ll, best_pll_dict = self._update(
                    X, rows, cols, vad,
                    initialize_users=initialize_users,
                    update_users_or_corrections=update_users_or_corrections,
                    update_categories=update_categories)
                new_validation_ll = best_pll_dict['pred_ll']
                self.logger.info('set params to best pll {}, old one was {}'
                    .format(new_validation_ll, validation_ll))
                validation_ll = new_validation_ll
                self.Eeps = best_pll_dict['best_Eeps']
                self.Eb = best_pll_dict['best_Eb']
                self.Et = best_pll_dict['best_Et']
                self.Elogeps = best_pll_dict['best_Elogeps']
                self.Elogb = best_pll_dict['best_Elogb']
                self.Elogt = best_pll_dict['best_Elogt']
                if validation_ll > best_validation_ll:
                    best_Eeps = self.Eeps
                    best_Eb = self.Eb
                    best_Et = self.Et
                    best_validation_ll = validation_ll
                self.logger.info('best validation ll was {}'.format(
                    best_validation_ll))
                self.Eeps = best_Eeps
                self.Eb = best_Eb
                self.Et = best_Et
        else:
            self._update(X, rows, cols, vad)
        return self

    def _update(self, X, rows, cols, vad,
        initialize_users='none',
        update_users_or_corrections='both',
        update_categories='all_categories'):
        # alternating between update latent components and weights
        old_pll = -np.inf
        best_pll_dict = dict(pred_ll = -np.inf)

        # user update logic
        for i in xrange(self.max_iter):
            if (update_users_or_corrections == 'items' or
                (self.observed_user_preferences and self.user_fit_type == 'default')):
                pass
            elif (update_users_or_corrections == 'users'):
                if initialize_users == 'initialize' and i == 0:
                    #self.observed_user_preferences = False
                    #self._init_users(self.n_users)
                    self.logger.info('switching from obs user prefs: {}'.format(self.observed_user_preferences))
                    self._update_users(X, rows, cols, switch_from_observed_user_preferences=True)
                    self.logger.info('switched from obs user prefs, now it is: {}'.format(self.observed_user_preferences))
                else:
                    self._update_users(X, rows, cols)
            else:
                self.logger.info('BEFORE updating users')
                train_ll = self.pred_loglikeli(X.data, rows, cols)
                self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
                        .format(train_ll))
                self._update_users(X, rows, cols)
                train_ll = self.pred_loglikeli(X.data, rows, cols)
                self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
                        .format(train_ll))
                self._update_users(X, rows, cols)
                train_ll = self.pred_loglikeli(X.data, rows, cols)
                self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
                        .format(train_ll))
                self._update_users(X, rows, cols)
                train_ll = self.pred_loglikeli(X.data, rows, cols)
                self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
                        .format(train_ll))
                self._update_users(X, rows, cols)
                train_ll = self.pred_loglikeli(X.data, rows, cols)
                self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
                        .format(train_ll))

            # item update logic
            if self.observed_item_attributes:
                pass
            else:
                self._update_items(X, rows, cols)
                train_ll = self.pred_loglikeli(X.data, rows, cols)
                self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
                        .format(train_ll))

            # zero out in-category or out_category item_corrections
            if self.item_fit_type == 'converge_in_category_first' or self.item_fit_type == 'converge_out_category_first':
                if self.zero_untrained_components and i == 0 and update_categories == 'all_categories':
                    # store the initial values somewhere, then zero them out,
                    # then load them back in once they've been fit
                    beta_bool = self.Eb.astype(bool)
                    beta_bool_not = np.logical_not(beta_bool)
                    small_num = 1e-5
                    if self.item_fit_type == 'converge_in_category_first':
                        # zero out out_category components
                        gamma_eps_out_category = self.gamma_eps[beta_bool_not]
                        rho_eps_out_category = self.rho_eps[beta_bool_not]
                        self.gamma_eps[beta_bool_not] = small_num
                        self.rho_eps[beta_bool_not] = small_num
                    elif self.item_fit_type == 'converge_out_category_first':
                        # zero out in_category components
                        gamma_eps_in_category = self.gamma_eps[beta_bool]
                        rho_eps_in_category = self.rho_eps[beta_bool]
                        self.gamma_eps[beta_bool] = small_num
                        self.rho_eps[beta_bool] = small_num

            # item correction (artist) update logic
            if update_users_or_corrections == 'items':
                # if (self.categorywise and
                #     self.item_fit_type == 'converge_in_category_first' and
                #     update_categories == 'all_categories'):
                #         self._update_item_corrections(X, rows, cols, update_categories='in_category')
                # elif (self.categorywise and
                #     self.item_fit_type == 'converge_out_category_first' and
                #     update_categories == 'all_categories'):
                #         self._update_item_corrections(X,rows,cols, update_categories='out_category')
                # else:
                self._update_item_corrections(X,rows,cols, update_categories=update_categories)
            elif update_users_or_corrections == 'both':
                self._update_item_corrections(X,rows,cols)
                train_ll = self.pred_loglikeli(X.data, rows, cols)
                self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
                        .format(train_ll))

            pred_ll = self.pred_loglikeli(**vad)
            # train_ll = self.pred_loglikeli(X.data, rows, cols)
            # self.logger.info('{:0.5f} <=========== TRAIN log-likelihood'
            #         .format(train_ll))
            if np.isnan(pred_ll):
                self.logger.error('got nan in predictive ll')
                raise Exception('nan in predictive ll')
            else:
                if pred_ll > best_pll_dict['pred_ll']:
                    best_pll_dict['pred_ll'] = pred_ll
                    self.logger.info('logged new best pred_ll as {}'
                        .format(pred_ll))
                    best_pll_dict['best_Eeps'] = self.Eeps
                    best_pll_dict['best_Elogeps'] = self.Elogeps
                    best_pll_dict['best_Eb'] = self.Eb
                    best_pll_dict['best_Elogb'] = self.Elogb
                    best_pll_dict['best_Et'] = self.Et
                    best_pll_dict['best_Elogt'] = self.Elogt
            improvement = (pred_ll - old_pll) / abs(old_pll)
            if self.verbose:
                string = 'ITERATION: %d\tPred_ll: %.2f\tOld Pred_ll: %.2f\tImprovement: %.5f' % (i, pred_ll, old_pll, improvement)
                self.logger.info(string)
            if improvement < self.tol and i >= self.min_iter:
                # if we're converging in category or out category components, need to re-load the initial values!
                if update_categories == 'all_categories' and self.item_fit_type != 'default':
                    if self.item_fit_type == 'converge_in_category_first':
                        # we converged in-category. now converge out_category
                        if self.zero_untrained_components:
                            self.logger.info('re-load initial values for out_category')
                            self.gamma_eps[beta_bool_not] = gamma_eps_out_category
                            self.rho_eps[beta_bool_not] = rho_eps_out_category
                        self._update(X, rows, cols, vad, update_categories='out_category')
                    if self.item_fit_type == 'converge_out_category_first':
                        # we converged out-category. now converge in_category
                        if zero_untrained_components:
                            self.logger.info('re-load initial values for in_category')
                            self.gamma_eps[beta_bool] = gamma_eps_in_category
                            self.rho_eps[beta_bool] = rho_eps_in_category
                        self._update(X, rows, cols, vad, update_categories='in_category')
                break
            old_pll = pred_ll
        #pass
        return pred_ll, best_pll_dict

    def _update_users(self, X, rows, cols, switch_from_observed_user_preferences=False):
        self.logger.info('updating users')

        if self.observed_item_attributes:
            expElogb = self.Eb
        else:
            expElogb = np.exp(self.Elogb)

        if self.observed_user_preferences:
            expElogt = self.Et
        else:
            expElogt = np.exp(self.Elogt)

        if self.observed_item_corrections:
            expElogeps = self.Eeps
        else:
            expElogeps = np.exp(self.Elogeps)

        ratioTb = sparse.csr_matrix((X.data / self._xexplog_b(rows, cols), (rows, cols)),
            dtype=np.float32, shape=X.shape).transpose()
        ratioTeps = sparse.csr_matrix((X.data / self._xexplog_eps(rows, cols), (rows, cols)),
            dtype=np.float32, shape=X.shape).transpose()
        self.gamma_t = self.a + expElogt * ratioTb.dot(expElogb).T + expElogt * ratioTeps.dot(expElogeps).T
        self.rho_t = self.b + np.sum(self.Eeps, axis=0, keepdims=True).T + np.sum(self.Eb, axis=0, keepdims=True).T

        self.Et, self.Elogt = _compute_expectations(self.gamma_t, self.rho_t)

        # switch off after updating once using fixed user preferences!
        if switch_from_observed_user_preferences:
            self.observed_user_preferences = False

    def _update_items(self, X, rows, cols):

        self.logger.info('update items')

        if self.observed_user_preferences:
            expElogt = self.Et
        else:
            expElogt = np.exp(self.Elogt)

        ratio = sparse.csr_matrix((X.data / self._xexplog_b(rows, cols), (rows, cols)), dtype=np.float32, shape=X.shape)
        self.gamma_bs = self.f + np.exp(self.Elogb) * ratio.dot(expElogt.T)
        self.rho_bs = self.g + np.sum(self.Et, axis=1)
        self.Eb, self.Elogb = _compute_expectations(self.gamma_bs, self.rho_bs)

    def _update_item_corrections(self, X, rows, cols,
        update_categories='all_categories'):

        self.logger.info('updating epsilons / item_corrections')

        ratio = sparse.csr_matrix((X.data / self._xexplog_eps(rows, cols), (rows, cols)), dtype=np.float32, shape=X.shape)

        if self.observed_user_preferences:
            expElogt = self.Et.T
        else:
            expElogt = np.exp(self.Elogt.T)

        gamma_eps_updated = self.c + np.exp(self.Elogeps) * ratio.dot(expElogt)
        rho_eps_updated = self.d + np.sum(self.Et, axis=1)

        if update_categories == 'in_category' or update_categories == 'out_category':

            beta_bool = self.Eb.astype(bool)

            if update_categories == 'in_category':
                    self.logger.info('updating *only* in-category parameters')
                    self.gamma_eps[beta_bool] = gamma_eps_updated[beta_bool]
                    self.rho_eps[beta_bool] = rho_eps_updated[beta_bool]
            elif update_categories == 'out_category':
                    beta_bool_not = np.logical_not(beta_bool)
                    self.logger.info('updating *only* out-category parameters')
                    self.gamma_eps[beta_bool_not] = gamma_eps_updated[beta_bool_not]
                    self.rho_eps[beta_bool_not] = \
                        rho_eps_updated[beta_bool_not]
        elif update_categories == 'all_categories':
            self.gamma_eps = gamma_eps_updated
            self.rho_eps = rho_eps_updated

        self.Eeps, self.Elogeps = _compute_expectations(self.gamma_eps, self.rho_eps)


    def _xexplog_b(self, rows, cols):
        '''
        sum_k exp(E[log theta_{ik} * beta_s_{kd}])
        '''
        if self.observed_user_preferences:
            expElogt = self.Et
        else:
            expElogt = np.exp(self.Elogt)

        if self.observed_item_attributes:
            expElogb = self.Eb
        else:
            expElogb = np.exp(self.Elogb)

        data = _inner(expElogb, expElogt, rows, cols)

        return data

    def _xexplog_eps(self, rows, cols):
        '''
        user i, doc d
        sum_k exp(E[log theta_{ik} * eps_{kd}])
        '''
        if self.observed_user_preferences:
            expElogt = self.Et
        else:
            expElogt = np.exp(self.Elogt)

        data = _inner(np.exp(self.Elogeps), expElogt, rows, cols)

        return data

    def pred_loglikeli(self, X_new, rows_new, cols_new):
        X_pred_bs = _inner(self.Eb, self.Et, rows_new, cols_new)
        #rows_item_corrections_new = np.array([self.song2artist[song] for song in rows_new], dtype=np.int32)
        rows_item_corrections_new = np.array([song for song in rows_new], dtype=np.int32)
        X_pred_ba = _inner(self.Eeps, self.Et, rows_item_corrections_new, cols_new)
        X_pred = X_pred_bs + X_pred_ba
        pred_ll = np.mean(X_new * np.log(X_pred) - X_pred)
        return pred_ll

def _inner(beta, theta, rows, cols):
    n_ratings = rows.size
    n_components, n_users = theta.shape
    data = np.empty(n_ratings, dtype=np.float32)
    code = r"""
    for (int i = 0; i < n_ratings; i++) {
       data[i] = 0.0;
       for (int j = 0; j < n_components; j++) {
           data[i] += beta[rows[i] * n_components + j] * theta[j * n_users + cols[i]];
       }
    }
    """
    weave.inline(code, ['data', 'theta', 'beta', 'rows', 'cols',
                        'n_ratings', 'n_components', 'n_users'])
    return data

def _compute_expectations(alpha, beta):
    '''
    Given x ~ Gam(alpha, beta), compute E[x] and E[log x]
    '''
    return (alpha / beta, special.psi(alpha) - np.log(beta))
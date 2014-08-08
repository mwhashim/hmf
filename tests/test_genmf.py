'''
This module contains a number of tests that check hmf's results against those of genmf

We check results for sigma, lnsigma, and the differential and cumulative mass functions against
genmf for two different redshifts (0 and 2). We use precisely the same transfer function here
as we use in genmf (tabulated). Another test tests if the power spectrum is generated
correctly according to this tabulated version.

The data files in the data/ directory are the following:
ST_0 etc :: output from genmf with given fit and redshift, produced with default cosmology here
power_for_hmf_tests.dat :: the power spectrum used in genmf
transfer_for_hmf_tests.dat :: the transfer function used in hmf (corresponds directly to the power)

The power was generated with hmf.transfer itself, so can be used as a direct test
for later versions.

To be more explicit, the power spectrum in all cases is produced with the following parameters:

       "w_lam"    :-1,
       "omegab"   : 0.05,
       "omegac"   : 0.25,
       "omegav"   : 0.7,
       "omegan"   : 0.0,
       "H0"       : 70,
       'cs2_lam'  : 1,
       'TCMB'     : 2.725,
       'yhe'      : 0.24,
       'Num_Nu_massless' : 3.04,
       'reion__redshift': 10.3,
       'reion__optical_depth': 0.085
        "sigma_8":0.8,
        "n":1,
        "delta_c":1.686,
        "crit_dens":27.755 * 10 ** 10
        'Num_Nu_massive'  : 0,
         'reion__fraction' :-1,
         'reion__delta_redshift' : 1.5,
         'lAccuracyBoost' : 1,
         'lSampleBoost'   : 1,
         'AccuracyBoost'  : 1,
         'transfer__k_per_logint': 0,
         'transfer__kmax':100.0
'''
#===============================================================================
# Some Imports
#===============================================================================
import numpy as np
from hmf import _MassFunction
# from scipy.interpolate import InterpolatedUnivariateSpline as spline
import inspect
import os

LOCATION = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
#=======================================================================
# Some general functions used in tests
#=======================================================================
def rms_diff(vec1, vec2, tol):
    mask = np.logical_and(np.logical_not(np.isnan(vec1)), np.logical_not(np.isnan(vec2)))
    vec1 = vec1[mask]
    vec2 = vec2[mask]
    err = np.sqrt(np.mean(((vec1 - vec2) / vec2) ** 2))
    print "RMS Error: ", err, "(> ", tol, ")"
    return err < tol

def max_diff_rel(vec1, vec2, tol):
    mask = np.logical_and(np.logical_not(np.isnan(vec1)), np.logical_not(np.isnan(vec2)))
    vec1 = vec1[mask]
    vec2 = vec2[mask]
    err = np.max(np.abs((vec1 - vec2) / vec2))
    print "Max Diff: ", err, "(> ", tol, ")"
    return err < tol

def max_diff(vec1, vec2, tol):
    mask = np.logical_and(np.logical_not(np.isnan(vec1)), np.logical_not(np.isnan(vec2)))
    vec1 = vec1[mask]
    vec2 = vec2[mask]
    err = np.max(np.abs((vec1 - vec2)))
    print "Max Diff: ", err, "(> ", tol, ")"
    return err < tol

#===============================================================================
# The Test Classes
#===============================================================================
class TestGenMF(object):
    def check_col(self, pert, fit, redshift, col):
        """ Able to check all columns only dependent on base cosmology (not fit) """


        data = np.genfromtxt(LOCATION + "/data/" + fit + '_' + str(int(redshift)))[::-1][400:1201]

        # We have to do funky stuff to the data if its been cut by genmf
        if col is "sigma":
            assert max_diff_rel(pert.sigma, data[:, 5], 0.004)
        elif col is "lnsigma":  # We just do diff on this one because it passes through 0
            assert max_diff(pert.lnsigma, data[:, 3], 0.001)
        elif col is "n_eff":
            assert max_diff_rel(pert.n_eff, data[:, 6], 0.001)
        elif col is "dndlog10m":
            assert rms_diff(pert.dndlog10m, 10 ** data[:, 1], 0.004)
        elif col is "fsigma":
            assert rms_diff(pert.fsigma, data[:, 4], 0.004)
        elif col is "ngtm":
            assert rms_diff(pert.ngtm, 10 ** data[:, 2], 0.046)

    def test_sigmas(self):
        hmf = _MassFunction(Mmin=7, Mmax=15.001, dlog10m=0.01, omegab=0.05, omegac=0.25,
                            omegav=0.7, sigma_8=0.8, n=1, H0=70.0,
                            lnk_min=-11, lnk_max=11, dlnk=0.01, transfer_options={"fname":LOCATION + "/data/transfer_for_hmf_tests.dat"},
                            mf_fit='ST', z=0.0, transfer_fit="FromFile")
        for redshift in [0.0, 2.0]:
            hmf.update(z=redshift)
            for col in ['sigma', 'lnsigma', 'n_eff']:
                yield self.check_col, hmf, "ST", redshift, col

    def test_fits(self):
#         hmf = _MassFunction(Mmin=7, Mmax=15.001, dlog10m=0.01, omegab=0.05, omegac=0.25,
#                             omegav=0.7, sigma_8=0.8, n=1, H0=70.0,
#                             lnk_min=-16, lnk_max=16, dlnk=0.01, transfer_options={"transfer__kmax":5,
#                             'transfer__k_per_logint':0}, mf_fit='ST', z=0.0)
        hmf = _MassFunction(Mmin=7, Mmax=15.001, dlog10m=0.01, omegab=0.05, omegac=0.25,
                            omegav=0.7, sigma_8=0.8, n=1, H0=70.0,
                            lnk_min=-11, lnk_max=11, dlnk=0.01, transfer_options={"fname":LOCATION + "/data/transfer_for_hmf_tests.dat"},
                            mf_fit='ST', z=0.0, transfer_fit="FromFile")
        for redshift in [0.0, 2.0]:
            hmf.update(z=redshift)
            for fit in ["ST", "PS", "Reed03", "Warren", "Jenkins", "Reed07"]:
                hmf.update(mf_fit=fit)
                for col in ['dndlog10m', 'ngtm', 'fsigma']:
                    yield self.check_col, hmf, fit, redshift, col


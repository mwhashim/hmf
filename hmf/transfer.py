"""
This module contains a single class, `Transfer`, which provides methods to 
calculate the transfer function, matter power spectrum and several other 
related quantities. 
"""
import numpy as np
from cosmo import Cosmology
from scipy.interpolate import InterpolatedUnivariateSpline as spline
import cosmolopy as cp
import scipy.integrate as integ
from _cache import cached_property, set_property
import copy
# import cosmolopy.density as cden
import tools
try:
    import pycamb
    HAVE_PYCAMB = True
except ImportError:
    HAVE_PYCAMB = False

class Transfer(object):
    '''
    Neatly deals with different transfer functions and their routines.
    
    The purpose of this class is to calculate transfer functions, power spectra
    and several tightly associated quantities using many of the available fits
    from the literature. 
        
    Importantly, it contains the means to calculate the transfer function using the
    popular CAMB code, the Eisenstein-Hu fit (1998), the BBKS fit or the Bond and
    Efstathiou fit (1984). Furthermore, it can calculate non-linear corrections
    using the halofit model (with updated parameters from Takahashi2012).
    
    The primary feature of this class is to wrap all the methods into a unified
    interface. On top of this, the class implements optimized updates of 
    parameters which is useful in, for example, MCMC code which covers a
    large parameter-space. Calling the `nonlinear_power` does not re-evaluate
    the entire transfer function, rather it just calculates the corrections, 
    improving performance.
    
    To update parameters optimally, use the update() method. 
    All output quantities are calculated only when needed (but stored after 
    first calculation for quick access).
    
    
    Parameters
    ----------
    lnk_min : float
        Defines min log wavenumber, *k* [units :math:`h Mpc^{-1}`]. 
        
    lnk_max : float
        Defines max log wavenumber, *k* [units :math:`h Mpc^{-1}`].
     
    dlnk : float
        Defines log interval between wavenumbers
        
    z : float, optional, default ``0.0``
        The redshift of the analysis.
                   
    wdm_mass : float, optional, default ``None``
        The warm dark matter particle size in *keV*, or ``None`` for CDM.
                                                                          
    transfer_fit : str, { ``"CAMB"``, ``"EH"``, ``"bbks"``, ``"bond_efs"``} 
        Defines which transfer function fit to use. If not defined from the
        listed options, it will be treated as a filename to be read in. In this
        case the file must contain a transfer function in CAMB output format. 
           
    Scalar_initial_condition : int, {1,2,3,4,5}
        (CAMB-only) Initial scalar perturbation mode (adiabatic=1, CDM iso=2, 
        Baryon iso=3,neutrino density iso =4, neutrino velocity iso = 5) 
        
    lAccuracyBoost : float, optional, default ``1.0``
        (CAMB-only) Larger to keep more terms in the hierarchy evolution
    
    AccuracyBoost : float, optional, default ``1.0``
        (CAMB-only) Increase accuracy_boost to decrease time steps, use more k 
        values,  etc.Decrease to speed up at cost of worse accuracy. 
        Suggest 0.8 to 3.
        
    w_perturb : bool, optional, default ``False``
        (CAMB-only) 
    
    transfer__k_per_logint : int, optional, default ``11``
        (CAMB-only) Number of wavenumbers estimated per log interval by CAMB
        Default of 11 gets best performance for requisite accuracy of mass function.
        
    transfer__kmax : float, optional, default ``0.25``
        (CAMB-only) Maximum value of the wavenumber.
        Default of 0.25 is high enough for requisite accuracy of mass function.
        
    ThreadNum : int, optional, default ``0``
        (CAMB-only) Number of threads to use for calculation of transfer 
        function by CAMB. Default 0 automatically determines the number.
                       
    kwargs : keywords
        The ``**kwargs`` take any cosmological parameters desired, which are 
        input to the `hmf.cosmo.Cosmology` class. `hmf.Perturbations` uses a 
        default parameter set from the first-year PLANCK mission, with optional 
        modifications by the user. Here is a list of parameters currently 
        available (and their defaults in `Transfer`):       
                 
        :sigma_8: [0.8344] The normalisation. Mass variance in top-hat spheres 
            with :math:`R=8Mpc h^{-1}`   
        :n: [0.9624] The spectral index 
        :w: [-1] The dark-energy equation of state
        :cs2_lam: [1] The constant comoving sound speed of dark energy
        :t_cmb: [2.725] Temperature of the CMB
        :y_he: [0.24] Helium fraction
        :N_nu: [3.04] Number of massless neutrino species
        :N_nu_massive: [0] Number of massive neutrino species
        :delta_c: [1.686] The critical overdensity for collapse
        :H0: [67.11] The hubble constant
        :h: [``H0/100.0``] The hubble parameter
        :omegan: [0] The normalised density of neutrinos
        :omegab_h2: [0.022068] The normalised baryon density by ``h**2``
        :omegac_h2: [0.12029] The normalised CDM density by ``h**2``
        :omegav: [0.6825] The normalised density of dark energy
        :omegab: [``omegab_h2/h**2``] The normalised baryon density
        :omegac: [``omegac_h2/h**2``] The normalised CDM density     
        :force_flat: [False] Whether to force the cosmology to be flat (affects only ``omegav``)
        :default: [``"planck1_base"``] A default set of cosmological parameters
    '''

    fits = ["CAMB", "EH", "bbks", "bond_efs"]
    _cp = ["sigma_8", "n", "w", "cs2_lam", "t_cmb", "y_he", "N_nu",
           "omegan", "H0", "h", "omegab",
           "omegac", "omegav", "omegab_h2", "omegac_h2",
           "force_flat", "default"]

    def __init__(self, z=0.0, lnk_min=np.log(1e-8),
                 lnk_max=np.log(2e4), dlnk=0.05,
                 wdm_mass=None, transfer_fit='CAMB',
                 Scalar_initial_condition=1, lAccuracyBoost=1,
                 AccuracyBoost=1, w_perturb=False, transfer__k_per_logint=11,
                 transfer__kmax=5, ThreadNum=0, **kwargs):
        '''
        Initialises some parameters
        '''
        # Set up a simple dictionary of cosmo params which can be later updated
        if "default" not in kwargs:
            kwargs["default"] = "planck1_base"

        self._cpdict = {k:v for k, v in kwargs.iteritems() if k in Transfer._cp}
        self._camb_options = {'Scalar_initial_condition' : Scalar_initial_condition,
                              'scalar_amp'      : 1E-9,
                              'lAccuracyBoost' : lAccuracyBoost,
                              'AccuracyBoost'  : AccuracyBoost,
                              'w_perturb'      : w_perturb,
                              'transfer__k_per_logint': transfer__k_per_logint,
                              'transfer__kmax':transfer__kmax,
                              'ThreadNum':ThreadNum}



        # Set all given parameters
        self.lnk_min = lnk_min
        self.lnk_max = lnk_max
        self.dlnk = dlnk
        self.wdm_mass = wdm_mass
        self.z = z
        self.transfer_fit = transfer_fit
        self.cosmo = Cosmology(**self._cpdict)

        # Here we store the values (with defaults) into _cpdict so they can be updated later.
        if "omegab" in kwargs:
            actual_cosmo = {k:v for k, v in self.cosmo.__dict__.iteritems()
                            if k in Transfer._cp and k not in ["omegab_h2", "omegac_h2"]}
        else:
            actual_cosmo = {k:v for k, v in self.cosmo.__dict__.iteritems()
                            if k in Transfer._cp and k not in ["omegab", "omegac"]}
        if "h" in kwargs:
            del actual_cosmo["H0"]
        elif "H0" in kwargs:
            del actual_cosmo["h"]
        self._cpdict.update(actual_cosmo)

    def update(self, **kwargs):
        """
        Update the class optimally with given arguments.
        
        Accepts any argument that the constructor takes
        """
        # First update the cosmology
        cp = {k:v for k, v in kwargs.iteritems() if k in self._cp}
        if cp:
            true_cp = {}
            for k, v in cp.iteritems():
                if k not in self._cpdict:
                    true_cp[k] = v
                elif k in self._cpdict:
                    if v != self._cpdict[k]:
                        true_cp[k] = v

            self._cpdict.update(true_cp)
            # Delete the entries we've used from kwargs
            for k in cp:
                del kwargs[k]

            # Now actually update the Cosmology class
            self.cosmo = Cosmology(**self._cpdict)

            # The following two parameters don't necessitate a complete recalculation
            if "n" in true_cp:
                try: del self._unnormalised_lnP
                except AttributeError: pass
            if "sigma_8" in true_cp:
                try: del self._lnP_cdm_0
                except AttributeError: pass
                try: del self._lnT_cdm
                except AttributeError: pass

            # All other parameters mean recalculating everything :(
            for item in ["omegab", "omegac", "h", "H0", "omegab_h2", "omegac_h2"]:
                if item in true_cp:
                    del self._unnormalised_lnT

        # Now do the other parameters
        for key, val in kwargs.iteritems():  # only camb options should be left
            # CAMB OPTIONS
            if key in self._camb_options:
                if self._camb_options[key] != val:
                    self._camb_options.update({key:val})
                    if key != "ThreadNum":
                        del self._unnormalised_lnT
            # ANYTHING ELSE
            else:
                if "_Transfer__" + key not in self.__dict__:
                    print "WARNING: ", key, " is not a valid parameter for the Transfer class"
                else:
                    if np.any(getattr(self, key) != val):
                        setattr(self, key, val)  # doing it this way enables value-checking

        # Some extra logic for deletes
        if ('omegab' in cp or 'omegac' in cp or 'omegav' in cp) and self.z > 0:
            del self.growth
        elif 'z' in kwargs:
            if kwargs['z'] == 0:
                del self.growth

    # ---- SET PROPERTIES --------------------------------
    @set_property("lnk")
    def lnk_min(self, val):
        return val

    @set_property("lnk")
    def lnk_max(self, val):
        return val

    @set_property("lnk")
    def dlnk(self, val):
        return val

    @set_property("growth")
    def z(self, val):
        try:
            val = float(val)
        except ValueError:
            raise ValueError("z must be a number (", val, ")")

        if val < 0:
            raise ValueError("z must be > 0 (", val, ")")

        return val

    @set_property("_lnP_0", "transfer")
    def wdm_mass(self, val):
        if val is None:
            return val
        try:
            val = float(val)
        except ValueError:
            raise ValueError("wdm_mass must be a number (", val, ")")

        if val <= 0:
            raise ValueError("wdm_mass must be > 0 (", val, ")")
        return val

    @set_property("_unnormalised_lnT")
    def transfer_fit(self, val):
        if not HAVE_PYCAMB and val == "CAMB":
            raise ValueError("You cannot use the CAMB transfer since pycamb isn't installed")
        return val


    # ---- DERIVED PROPERTIES AND FUNCTIONS ---------------
    @cached_property("_unnormalised_lnT")
    def lnk(self):
        return np.arange(self.lnk_min, self.lnk_max, self.dlnk)


    def _check_low_k(self, lnk, lnT):
        """
        Check convergence of transfer function at low k.
        
        Unfortunately, some versions of CAMB produce a transfer which has a
        turn-up at low k, which is what we seek to cut out here.
        
        Parameters
        ----------
        lnk : array_like
            Value of log(k)
            
        lnT : array_like
            Value of log(transfer)
        """

        start = 0
        for i in range(len(lnk) - 1):
            if abs((lnT[i + 1] - lnT[i]) / (lnk[i + 1] - lnk[i])) < 0.01:
                start = i
                break
        lnT = lnT[start:-1]
        lnk = lnk[start:-1]

        return lnk, lnT

    # ---- TRANSFER FITS -------------------------------------------------------
    def _from_file(self, k):
        """
        Import the transfer function from file.
        
        The format can either be CAMB, or 2-column k, T.
        
        .. note :: This should not be called by the user!
        """
        try:
            T = np.log(np.genfromtxt(self.transfer_fit)[:, [0, 6]].T)
        except IndexError:
            T = np.log(np.genfromtxt(self.transfer_fit)[:, [0, 1]].T)

        lnk, lnT = self._check_low_k(T[0, :], T[1, :])
        return spline(lnk, lnT, k=1)(k)

    def _CAMB(self, k):
        """
        Generate transfer function with CAMB
        
        .. note :: This should not be called by the user!
        """
        cdict = dict(self.cosmo.pycamb_dict(),
                     **self._camb_options)
        T = pycamb.transfers(**cdict)[1]
        T = np.log(T[[0, 6], :, 0])

        lnk, lnT = self._check_low_k(T[0, :], T[1, :])

        return spline(lnk, lnT, k=1)(k)

    def _EH(self, k):
        """
        Eisenstein-Hu transfer function
        
        .. note :: This should not be called by the user!
        """

        T = np.log(cp.perturbation.transfer_function_EH(np.exp(k) * self.cosmo.h,
                                    **self.cosmo.cosmolopy_dict())[1])
        return T

    def _bbks(self, k):
        """
        BBKS transfer function.

        .. note :: This should not be called by the user!
        """
        Gamma = self.cosmo.omegam * self.cosmo.h
        q = np.exp(k) / Gamma * np.exp(self.cosmo.omegab + np.sqrt(2 * self.cosmo.h) *
                               self.cosmo.omegab / self.cosmo.omegam)
        return np.log((np.log(1.0 + 2.34 * q) / (2.34 * q) *
                (1 + 3.89 * q + (16.1 * q) ** 2 + (5.47 * q) ** 3 +
                 (6.71 * q) ** 4) ** (-0.25)))

    def _bond_efs(self, k):
        """
        Bond and Efstathiou transfer function.
        
        .. note :: This should not be called by the user!
        """

        omegah2 = 1.0 / (self.cosmo.omegam * self.cosmo.h ** 2)

        a = 6.4 * omegah2
        b = 3.0 * omegah2
        c = 1.7 * omegah2
        nu = 1.13
        k = np.exp(k)
        return np.log((1 + (a * k + (b * k) ** 1.5 + (c * k) ** 2) ** nu) ** (-1 / nu))

    @cached_property("_unnormalised_lnP", "_lnT_cdm")
    def _unnormalised_lnT(self):
        """
        The un-normalised transfer function
        
        This wraps the individual transfer_fit methods to provide unified access.
        """
        try:
            return getattr(self, "_" + self.transfer_fit)(self.lnk)
        except AttributeError:
            return self._from_file(self.lnk)

    @cached_property("_lnP_cdm_0")
    def _unnormalised_lnP(self):
        """
        Un-normalised CDM log power at :math:`z=0` [units :math:`Mpc^3/h^3`]
        """
        return self.cosmo.n * self.lnk + 2 * self._unnormalised_lnT

    @cached_property("_lnP_0")
    def _lnP_cdm_0(self):
        """
        Normalised CDM log power at z=0 [units :math:`Mpc^3/h^3`]
        """
        return tools.normalize(self.cosmo.sigma_8,
                               self._unnormalised_lnP,
                               self.lnk, self.cosmo.mean_dens)[0]

    @cached_property("transfer")
    def _lnT_cdm(self):
        """
        Normalised CDM log transfer function
        """
        return tools.normalize(self.cosmo.sigma_8,
                               self._unnormalised_lnT,
                               self.lnk, self.cosmo.mean_dens)

    @cached_property("power")
    def _lnP_0(self):
        """
        Normalised log power at :math:`z=0` (for CDM/WDM)
        """
        if self.wdm_mass is not None:
            return tools.wdm_transfer(self.wdm_mass, self._lnP_cdm_0,
                                              self.lnk, self.cosmo.h, self.cosmo.omegac)
        else:
            return self._lnP_cdm_0

    @cached_property("power")
    def growth(self):
        r"""
        The growth factor :math:`d(z)`
        
        This is calculated (see Lukic 2007) as
        
        .. math:: d(z) = \frac{D^+(z)}{D^+(z=0)}
                
        where
        
        .. math:: D^+(z) = \frac{5\Omega_m}{2}\frac{H(z)}{H_0}\int_z^{\infty}{\frac{(1+z')dz'}{[H(z')/H_0]^3}}
        
        and
        
        .. math:: H(z) = H_0\sqrt{\Omega_m (1+z)^3 + (1-\Omega_m)}
        
        """
        if self.z > 0:
            return tools.growth_factor(self.z, self.cosmo)
        else:
            return 1.0

    @cached_property("delta_k")
    def power(self):
        """
        Normalised log power spectrum [units :math:`Mpc^3/h^3`]
        """
        return 2 * np.log(self.growth) + self._lnP_0

    @cached_property()
    def transfer(self):
        """
        Normalised log transfer function for CDM/WDM
        """
        return tools.wdm_transfer(self.wdm_mass, self._lnT_cdm,
                                  self.lnk, self.cosmo.h, self.cosmo.omegac)

    @cached_property("nonlinear_delta_k")
    def delta_k(self):
        r"""
        Dimensionless power spectrum, :math:`\Delta_k = \frac{k^3 P(k)}{2\pi^2}`
        """
        return 3 * self.lnk + self.power - np.log(2 * np.pi ** 2)

    @cached_property()
    def nonlinear_power(self):
        """
        Non-linear log power [units :math:`Mpc^3/h^3`]
        
        Non-linear corrections come from HALOFIT (Smith2003) with updated
        parameters from Takahashi2012. 
        
        This code was heavily influenced by the HaloFit class from the 
        `chomp` python package by Christopher Morrison, Ryan Scranton 
        and Michael Schneider (https://code.google.com/p/chomp/). It has 
        been modified to improve its integration with this package.        
        """
        return -3 * self.lnk + self.nonlinear_delta_k + np.log(2 * np.pi ** 2)

    def _get_spec(self):
        """
        Calculate nonlinear wavenumber, effective spectral index and curvature
        of the power spectrum.
        """
        k = np.exp(self.lnk)
        delta_k = np.exp(self.delta_k)

        # Initialize sigma spline
        if self.cosmo.sigma_8 < 1.0 and self.cosmo.sigma_8 > 0.6:
            lnr = np.linspace(np.log(0.1), np.log(10.0), 500)
            lnsig = np.empty(500)

            for i, r in enumerate(lnr):
                R = np.exp(r)
                integrand = delta_k * np.exp(-(k * R) ** 2)
                sigma2 = integ.simps(integrand, np.log(k))
                lnsig[i] = np.log(sigma2)

        else:  # # weird sigma_8 means we need a different range of r to go through 0.
            for r in [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]:
                integrand = delta_k * np.exp(-(k * r) ** 2)
                sigma2 = integ.simps(integrand, np.log(k))
                lnsig1 = np.log(sigma2)

                if lnsig1 < 0:
                    lnsig1 = lnsig_old
                    break

                lnsig_old = copy.copy(lnsig1)

            lnr = np.linspace(np.log(0.01), np.log(10 * lnsig1), 500)
            lnsig = np.empty(500)

            for i, r in enumerate(lnr):
                R = np.exp(r)
                integrand = delta_k * np.exp(-(k * R) ** 2)
                sigma2 = integ.simps(integrand, np.log(k))
                lnsig[i] = np.log(sigma2)

        r_of_sig = spline(lnsig[::-1], lnr[::-1], k=5)
        rknl = 1.0 / np.exp(r_of_sig(0.0))

        sig_of_r = spline(lnr, lnsig, k=5)

        try:
            dev1, dev2 = sig_of_r.derivatives(np.log(1.0 / rknl))[1:3]
        except:
            lnr = np.linspace(np.log(0.2 / rknl), np.log(5 / rknl), 100)
            lnsig = np.empty(100)

            for i, r in enumerate(lnr):
                R = np.exp(r)
                integrand = delta_k * np.exp(-(k * R) ** 2)
                sigma2 = integ.simps(integrand, np.log(k))
                lnsig[i] = np.log(sigma2)
            sig_of_r = spline(lnr, lnsig, k=5)
            dev1, dev2 = sig_of_r.derivatives(np.log(1.0 / rknl))[1:3]

        rneff = -dev1 - 3.0
        rncur = -dev2

        print "rknl, rneff, rncur: ", rknl, rneff, rncur
        return rknl, rneff, rncur

    def _halofit(self, k, neff, rncur, rknl, plin):
        """
        Halofit routine to calculate pnl and plin.
        
        Basically copies the CAMB routine
        """

        # Define the cosmology at redshift
        omegam = cp.density.omega_M_z(self.z, **self.cosmo.cosmolopy_dict())
        omegav = self.cosmo.omegav / cp.distance.e_z(self.z, **self.cosmo.cosmolopy_dict()) ** 2

        w = self.cosmo.w
        fnu = self.cosmo.omegan / self.cosmo.omegam

        a = 10 ** (1.5222 + 2.8553 * neff + 2.3706 * neff ** 2 +
                    0.9903 * neff ** 3 + 0.2250 * neff ** 4 +
                    - 0.6038 * rncur + 0.1749 * omegav * (1 + w))
        b = 10 ** (-0.5642 + 0.5864 * neff + 0.5716 * neff ** 2 +
                - 1.5474 * rncur + 0.2279 * omegav * (1 + w))
        c = 10 ** (0.3698 + 2.0404 * neff + 0.8161 * neff ** 2 + 0.5869 * rncur)
        gam = 0.1971 - 0.0843 * neff + 0.8460 * rncur
        alpha = np.abs(6.0835 + 1.3373 * neff - 0.1959 * neff ** 2 +
                - 5.5274 * rncur)
        beta = (2.0379 - 0.7354 * neff + 0.3157 * neff ** 2 +
                  1.2490 * neff ** 3 + 0.3980 * neff ** 4 - 0.1682 * rncur +
                  fnu * (1.081 + 0.395 * neff ** 2))
        xmu = 0.0
        xnu = 10 ** (5.2105 + 3.6902 * neff)

        if np.abs(1 - omegam) > 0.01:
            f1a = omegam ** -0.0732
            f2a = omegam ** -0.1423
            f3a = omegam ** 0.0725
            f1b = omegam ** -0.0307
            f2b = omegam ** -0.0585
            f3b = omegam ** 0.0743
            frac = omegav / (1 - omegam)
            f1 = frac * f1b + (1 - frac) * f1a
            f2 = frac * f2b + (1 - frac) * f2a
            f3 = frac * f3b + (1 - frac) * f3a
        else:
            f1 = f2 = f3 = 1.0

        y = k / rknl

        ph = a * y ** (f1 * 3) / (1 + b * y ** f2 + (f3 * c * y) ** (3 - gam))
        ph = ph / (1 + xmu * y ** (-1) + xnu * y ** (-2)) * (1 + fnu * (0.977 - 18.015 * (self.cosmo.omegam - 0.3)))
        plinaa = plin * (1 + fnu * 47.48 * k ** 2 / (1 + 1.5 * k ** 2))
        pq = plin * (1 + plinaa) ** beta / (1 + plinaa * alpha) * np.exp(-y / 4.0 - y ** 2 / 8.0)
        pnl = pq + ph
        print "pnl: ", pnl
        return pnl

    @cached_property("nonlinear_power")
    def nonlinear_delta_k(self):
        r"""
        Dimensionless nonlinear power spectrum, :math:`\Delta_k = \frac{k^3 P_{\rm nl}(k)}{2\pi^2}`
        """
        rknl, rneff, rncur = self._get_spec()
        mask = np.exp(self.lnk) > 0.005
        plin = np.exp(self.delta_k)
        k = np.exp(self.lnk[mask])
        pnl = self._halofit(k, rneff, rncur, rknl, plin[mask])
        nonlinear_delta_k = np.exp(self.delta_k)
        nonlinear_delta_k[mask] = pnl
        nonlinear_delta_k = np.log(nonlinear_delta_k)
        return nonlinear_delta_k

# Copyright 2016, FBPIC contributors
# Authors: Remi Lehe, Manuel Kirchen
# License: 3-Clause-BSD-LBNL
"""
This test file is part of FB-PIC (Fourier-Bessel Particle-In-Cell).

It tests the injection of a laser by a laser antenna

The laser is emitted from an antenna, and then its 2D profile is
compared with theory. There is typically a strong influence of the
longitudinal resolution on the amplitude of the emitted laser:
below ~30 points per laser wavelength, the emitted a0 can be ~10%
smaller than the desired value.

This is tested for different particle shapes.

Usage :
-------
In order to show the images of the laser, and manually check the
agreement between the simulation and the theory:
$ python tests/test_laser_antenna.py
(except when setting show to False in the parameters below)

In order to let Python check the agreement between the curve without
having to look at the plots
$ py.test -q tests/test_laser_antenna.py
or
$ python setup.py test
"""
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from scipy.constants import c, m_e, e
from fbpic.main import Simulation
from fbpic.lpa_utils.laser import add_laser
from fbpic.openpmd_diag import FieldDiagnostic
from fbpic.lpa_utils.boosted_frame import BoostConverter

# Parameters
# ----------
show = False
write_files = True
# Whether to show the plots, and check them manually
use_cuda = True

# Simulation box
Nz = 800
zmin = -10.e-6
zmax = 10.e-6
Nr = 25
rmax = 400.e-6
Nm = 2
dt = (zmax-zmin)/Nz/c
# Laser pulse
w0 = 128.e-6
ctau = 5.e-6
a0 = 1.
z0_antenna = 0.e-6
zf = 0.e-6
z0 = -5.e-6
# Propagation
Lprop = 10.5e-6
Ntot_step = int(Lprop/(c*dt))
N_show = 3 # Number of instants in which to show the plots (during propagation)

# The boost in the case of the boosted frame run
gamma_boost = 10.

def test_antenna_labframe_cubic(show=False, write_files=False):
    """
    Function that is run by py.test, when doing `python setup.py test`
    Test the emission of a laser by an antenna, in the lab frame
    """
    run_and_check_laser_antenna(None, 'cubic', show, write_files)

def test_antenna_labframe_linear(show=False, write_files=False):
    """
    Function that is run by py.test, when doing `python setup.py test`
    Test the emission of a laser by an antenna, in the lab frame
    """
    run_and_check_laser_antenna(None, 'linear', show, write_files)
    if use_cuda:
        run_and_check_laser_antenna(None, 'linear_non_atomic', 
                                    show, write_files)

def test_antenna_boostedframe_cubic(show=False, write_files=False):
    """
    Function that is run by py.test, when doing `python setup.py test`
    Test the emission of a laser by an antenna, in the boosted frame
    """
    run_and_check_laser_antenna(gamma_boost, 'cubic', show, write_files)

def test_antenna_boostedframe_linear(show=False, write_files=False):
    """
    Function that is run by py.test, when doing `python setup.py test`
    Test the emission of a laser by an antenna, in the boosted frame
    """
    run_and_check_laser_antenna(gamma_boost, 'linear', show, write_files)
    if use_cuda:
        run_and_check_laser_antenna(gamma_boost, 'linear_non_atomic', 
                                show, write_files)

def run_and_check_laser_antenna(gamma_b, shape, show, write_files):
    """
    Generic function, which runs and check the laser antenna for 
    both boosted frame and lab frame

    Parameters
    ----------
    gamma_b: float or None
        The Lorentz factor of the boosted frame

    shape: string
        Indicates the particle shape that is being used

    show: bool
        Whether to show the images of the laser as pop-up windows

    write_files: bool
        Whether to output openPMD data of the laser
    """
    # Initialize the simulation object
    sim = Simulation( Nz, zmax, Nr, rmax, Nm, dt, p_zmin=0, p_zmax=0,
                    p_rmin=0, p_rmax=0, p_nz=2, p_nr=2, p_nt=2, n_e=0.,
                    zmin=zmin, use_cuda=use_cuda, boundaries='open',
                    gamma_boost=gamma_b, particle_shape=shape)

    # Remove the particles
    sim.ptcl = []

    # Add the laser
    add_laser( sim, a0, w0, ctau, z0, zf=zf,
        method='antenna', z0_antenna=z0_antenna, gamma_boost=gamma_b)

    # Calculate the number of steps between each output
    N_step = int( round( Ntot_step/N_show ) )

    # Add diagnostic
    if write_files:
        sim.diags = [
            FieldDiagnostic( N_step, sim.fld, comm=None,
                             fieldtypes=["rho", "E", "B", "J"] )
            ]

    # Loop over the iterations
    print('Running the simulation...')
    for it in range(N_show) :
        print( 'Diagnostic point %d/%d' %(it, N_show) )
        # Advance the Maxwell equations
        sim.step( N_step, show_progress=False )
        # Plot the fields during the simulation
        if show==True :
            plt.clf()
            sim.fld.interp[1].show('Et')
            plt.show()
    # Finish the remaining iterations
    sim.step( Ntot_step - N_show*N_step, show_progress=False )

    # Check the transverse E and B field
    Nz_half = int(sim.fld.interp[1].Nz/2) + 2
    z = sim.fld.interp[1].z[Nz_half:-sim.comm.n_guard]
    r = sim.fld.interp[1].r
    # Loop through the different fields
    for fieldtype, info_in_real_part, factor in [ ('Er', True, 2.), \
                ('Et', False, 2.), ('Br', False, 2.*c), ('Bt', True, 2.*c) ]:
        # factor correspond to the factor that has to be applied
        # in order to get a value which is comparable to an electric field
        # (Because of the definition of the interpolation grid, the )
        field = getattr(sim.fld.interp[1], fieldtype)\
                            [Nz_half:-sim.comm.n_guard]
        print( 'Checking %s' %fieldtype )
        check_fields( factor*field, z, r, info_in_real_part, gamma_b )
        print( 'OK' )

def check_fields( interp1_complex, z, r, info_in_real_part, gamma_b,
                    show_difference=False ):
    """
    Check the real and imaginary part of the interpolation grid agree
    with the theory by:
    - Checking that the part (real or imaginary) that does not
        carry information is zero
    - Extracting the a0 from the other part and comparing it
        to the predicted value
    - Using the extracted value of a0 to compare the simulated
      profile with a gaussian profile
    """
    # Extract the part that has information
    if info_in_real_part:
        interp1 = interp1_complex.real
        zero_part = interp1_complex.imag
    else:
        interp1 = interp1_complex.imag
        zero_part = interp1_complex.real

    # Control that the part that has no information is 0
    assert np.allclose( 0., zero_part, atol=1.e-6*interp1.max() )

    # Get the predicted properties of the laser in the boosted frame
    if gamma_b is None:
        boost = BoostConverter(1.)
    else:
        boost = BoostConverter(gamma_b)
    ctau_b, lambda0_b, Lprop_b, z0_b = \
        boost.copropag_length([ctau, 0.8e-6, Lprop, z0])
    
    # Fit the on-axis profile to extract a0
    def fit_function(z, a0, z0_phase):
        return( gaussian_laser( z, r[0], a0, z0_phase, 
                                z0_b+Lprop_b, ctau_b, lambda0_b ) )
    fit_result = curve_fit( fit_function, z, interp1[:,0],
                            p0=np.array([a0, z0_b+Lprop_b]) )
    a0_fit, z0_fit = fit_result[0]

    # Check that the a0 agrees within 5% of the predicted value
    assert abs( abs(a0_fit) - a0 )/a0 < 0.05

    # Calculate predicted fields
    r2d, z2d = np.meshgrid(r, z)
    # Factor 0.5 due to the definition of the interpolation grid
    interp1_predicted = gaussian_laser( z2d, r2d, a0_fit, z0_fit,
                                        z0_b+Lprop_b, ctau_b, lambda0_b )
    # Plot the difference
    if show_difference:
        plt.subplot(311)
        plt.imshow( interp1.T )
        plt.colorbar()
        plt.subplot(312)
        plt.imshow( interp1_predicted.T )
        plt.colorbar()
        plt.subplot(313)
        plt.imshow( (interp1_predicted - interp1).T )
        plt.colorbar()
        plt.show()
    # Control the values (with a precision of 3%)
    assert np.allclose( interp1_predicted, interp1, atol=3.e-2*interp1.max() )

def gaussian_laser( z, r, a0, z0_phase, z0_prop, ctau, lambda0 ):
    """
    Returns a Gaussian laser profile
    """
    k0 = 2*np.pi/lambda0
    E0 = a0*m_e*c**2*k0/e
    return( E0*np.exp( -r**2/w0**2 - (z-z0_prop)**2/ctau**2 ) \
                *np.cos( k0*(z-z0_phase) ) )

if __name__ == '__main__' :

    # Run the testing functions
    test_antenna_labframe_cubic(show, write_files)
    test_antenna_labframe_linear(show, write_files)
    test_antenna_boostedframe_cubic(show, write_files)
    test_antenna_boostedframe_linear(show, write_files)

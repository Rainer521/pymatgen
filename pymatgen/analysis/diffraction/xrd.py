#!/usr/bin/env python

"""
This module implements an XRD pattern calculator.
"""

from __future__ import division

__author__ = "Shyue Ping Ong"
__copyright__ = "Copyright 2012, The Materials Project"
__version__ = "0.1"
__maintainer__ = "Shyue Ping Ong"
__email__ = "ongsp@ucsd.edu"
__date__ = "5/22/14"


from math import sin, cos, asin, pi
import os

import numpy as np
import json

from pymatgen.symmetry.finder import SymmetryFinder


#XRD wavelengths in angstroms
WAVELENGTHS = {
    "CuKa": 1.54184,
    "CuKa2": 1.54439,
    "CuKa1": 1.54056,
    "CuKb1": 1.39222,
    "MoKa": 0.71073,
    "MoKa2": 0.71359,
    "MoKa1": 0.70930,
    "MoKb1": 0.63229,
    "CrKa": 2.29100,
    "CrKa2": 2.29361,
    "CrKa1": 2.28970,
    "CrKb1": 2.08487,
    "FeKa": 1.93735,
    "FeKa2": 1.93998,
    "FeKa1": 1.93604,
    "FeKb1": 1.75661,
    "CoKa": 1.79026,
    "CoKa2": 1.79285,
    "CoKa1": 1.78896,
    "CoKb1": 1.63079
}

with open(os.path.join(os.path.dirname(__file__),
                       "atomic_scattering_factors.json")) as f:
    ATOMIC_SCATTERING_PARAMS = json.load(f)


class XRDCalculator(object):
    """
    Computes the XRD pattern of a crystal structure.

    This code is implemented by Shyue Ping Ong as part of UCSD's NANO106 -
    Crystallography of Materials. The formalism for this code is based on
    that given in Chapters 11 and 12 of Structure of Materials by Marc De
    Graef and Michael E. McHenry. This takes into account the atomic
    scattering factors and the Lorentz polarization factor, but not
    the Debye-Waller (temperature) factor (for which data is typically not
    available). Note that the multiplicity correction is not needed since
    this code simply goes through all reciprocal points within the limiting
    sphere, which includes all symmetrically equivalent planes. The algorithm
    is as follows

    1. Calculate reciprocal lattice of structure. Find all reciprocal points
       within the limiting sphere given by :math:`\\frac{2}{\\lambda}`.

    2. For each reciprocal point :math:`\\mathbf{g_{hkl}}` corresponding to
       lattice plane :math:`(hkl)`, compute the Bragg condition
       :math:`\\sin(\\theta) = \\frac{\\lambda}{2d_{hkl}}`

    3. Compute the structure factor as the sum of the atomic scattering
       factors. The atomic scattering factors are given by

       .. math::

           f(s) = Z - 41.78214 \\times s^2 \\times \\sum\\limits_{i=1}^n a_i \\exp(-b_is^2)

       where :math:`s = \\frac{\\sin(\\theta)}{\\lambda}` and :math:`a_i`
       and :math:`b_i` are the fitted parameters for each element. The
       structure factor is then given by

       .. math::

           F_{hkl} = \\sum\\limits_{j=1}^N f_j \\exp(2\\pi i \\mathbf{g_{hkl}} \cdot \\mathbf{r})

    4. The intensity is then given by the modulus square of the structure
       factor.

       .. math::

           I_{hkl} = F_{hkl}F_{hkl}^*

    5. Finally, the Lorentz polarization correction factor is applied. This
       factor is given by:

       .. math::

           P(\\theta) = \\frac{1 + \\cos^2(2\\theta)}{\\sin^2(\\theta)\\cos(\\theta)}
    """

    #Tuple of available radiation keywords.
    AVAILABLE_RADIATION = tuple(WAVELENGTHS.keys())

    def __init__(self, radiation="CuKa", symprec=0):
        """
        Initializes the XRD calculator with a given radiation.

        Args:
            radiation: The type of radiation. Choose from any of those
                available in the AVAILABLE_RADIATION class variable. Defaults
                to CuKa, i.e, Cu K_alpha radiation.
            symprec:
                Symmetry precision for structure refinement. If set to 0,
                no refinement is done. Otherwise, refinement is performed
                using spglib with provided precision.

        """
        self.radiation = radiation
        self.wavelength = WAVELENGTHS[radiation]
        self.symprec = symprec

    def get_xrd_data(self, structure):
        """
        Calculates the XRD data for a structure.

        Args:
            structure: Input structure

        Returns:
            {XRD data} in the form of [[two_theta, scaled_intensity, [h, k, l]]]
        """
        if self.symprec:
            finder = SymmetryFinder(structure, symprec=self.symprec)
            structure = finder.get_refined_structure()

        wavelength = self.wavelength
        latt = structure.lattice

        # Obtain crystallographic reciprocal lattice and points within
        # limiting sphere (within 2/wavelength)
        recip_latt = latt.reciprocal_lattice_crystallographic
        recip_pts = recip_latt.get_points_in_sphere(
            [[0, 0, 0]], [0, 0, 0], 2 / wavelength)

        intensities = {}
        two_thetas = []

        # Create a flattened array of zs, coeffs, fcoords and occus. This is
        # used to perform vectorized computation of atomic scattering factors
        # later. Note that these are not necessarily the same size as the
        # structure as each partially occupied species occupies its own
        # position in the flattened array.
        zs = []
        coeffs = []
        fcoords = []
        occus = []
        for site in structure:
            for sp, occu in site.species_and_occu.items():
                zs.append(sp.Z)
                coeffs.append(ATOMIC_SCATTERING_PARAMS[sp.symbol])
                fcoords.append(site.frac_coords)
                occus.append(occu)

        zs = np.array(zs)
        coeffs = np.array(coeffs)
        fcoords = np.array(fcoords)
        occus = np.array(occus)

        for hkl, g_hkl, ind in sorted(
                recip_pts, key=lambda i: (i[1], -i[0][2], -i[0][1], -i[0][0])):
            if g_hkl != 0:
                # Bragg condition
                theta = asin(wavelength * g_hkl / 2)

                # s = sin(theta) / wavelength = |ghkl| / 2 (d = 1/|ghkl|)
                s = g_hkl / 2

                #Store s squared since we are using it a few times.
                s2 = s ** 2

                # Vectorized computation of g.r for all fractional coords and
                # hkl.
                grs = np.dot(fcoords, np.transpose([hkl])).T[0]

                # Highly vectorized computation of atomic scattering factors.
                # Equivalent non-vectorized code is::
                #
                #   for site in structure:
                #      el = site.specie
                #      coeff = ATOMIC_SCATTERING_PARAMS[el.symbol]
                #      fs = el.Z - 41.78214 * s2 * sum(
                #          [d[0] * exp(-d[1] * s2) for d in coeff])
                fs = zs - 41.78214 * s2 * np.sum(
                    coeffs[:, :, 0] * np.exp(-coeffs[:, :, 1] * s2), axis=1)

                # Structure factor = sum of atomic scattering factors (with
                # position factor exp(2j * pi * g.r and occupancies).
                # Vectorized computation.
                f_hkl = np.sum(fs * occus * np.exp(2j * pi * grs))

                # Intensity for hkl is modulus square of structure factor.
                i_hkl = (f_hkl * f_hkl.conjugate()).real

                #Lorentz polarization correction for hkl
                lorentz_factor = (1 + cos(2 * theta) ** 2) / \
                    (sin(theta) ** 2 * cos(theta))

                two_theta = 2 * theta / pi * 180

                #Deal with floating point precision issues.
                ind = np.where(np.abs(np.subtract(two_thetas, two_theta)) <
                               1e-5)
                if len(ind[0]) > 0:
                    intensities[two_thetas[ind[0]]][0] += i_hkl * lorentz_factor
                else:
                    intensities[two_theta] = [i_hkl * lorentz_factor,
                                              tuple(hkl)]
                    two_thetas.append(two_theta)

        # Scale intensities so that the max intensity is 100.
        max_intensity = max([v[0] for v in intensities.values()])
        data = []
        for k in sorted(intensities.keys()):
            v = intensities[k]
            scaled_intensity = v[0] / max_intensity * 100
            if scaled_intensity > 1e-3:
                data.append([k, scaled_intensity, v[1]])
        return data

    def get_xrd_plot(self, structure, two_theta_range=(0, 90),
                     annotate_peaks=True):
        """
        Returns the XRD plot as a matplotlib.pyplot.

        Args:
            structure: Input structure
            two_theta_range: Range of two_thetas for which to plot. Defaults
                to (0, 90).
            annotate_peaks: Whether to annotate the peaks with plane
                information.

        Returns:
            (matplotlib.pyplot)
        """
        from pymatgen.util.plotting_utils import get_publication_quality_plot
        plt = get_publication_quality_plot(16, 10)
        two_theta_range = [-1, float("inf")] if two_theta_range is None \
            else two_theta_range
        for two_theta, i, hkl in self.get_xrd_data(structure):
            if two_theta_range[0] <= two_theta <= two_theta_range[1]:
                plt.plot([two_theta, two_theta], [0, i], color='k',
                         linewidth=3, label=str(hkl))
                if annotate_peaks:
                    plt.annotate(str(hkl), xy=[two_theta, i],
                                 xytext=[two_theta, i], fontsize=16)
        return plt

    def show_xrd_plot(self, structure, two_theta_range=(0, 90),
                      annotate_peaks=True):
        """
        Shows the XRD plot.

        Args:
            structure: Input structure
            two_theta_range: Range of two_thetas for which to plot. Defaults
                to (0, 90).
            annotate_peaks: Whether to annotate the peaks with plane
                information.
        """
        self.get_xrd_plot(structure, two_theta_range=two_theta_range,
                          annotate_peaks=annotate_peaks).show()
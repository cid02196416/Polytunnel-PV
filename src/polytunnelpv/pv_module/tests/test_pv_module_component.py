#!/usr/bin/python3
########################################################################################
# test_pv_module_component.py - Tests for the PV-module component.                     #
#                                                                                      #
# Author: Ben Winchester                                                               #
# Copyright: Ben Winchester, 2024                                                      #
# Date created: 11/04/2024                                                             #
# License: Open source                                                                 #
########################################################################################
"""
test_pv_module_component.py - Tests for the component-level code.

"""

import unittest

from math import degrees, pi
from unittest import mock

from ..pv_module import CircularCurve, CurvedPVModule


class CurvedThinFilmPVModuleTest(unittest.TestCase):
    """Tests the curved PV-module code."""

    def setUp(self) -> None:
        """Setup mocks in common across the test cases."""
        self.curve = CircularCurve(
            curvature_axis_azimuth=180, curvature_axis_tilt=10, radius_of_curvature=10
        )

        super().setUp()

    def test_mainline(self) -> None:
        """Tests the mainline case."""

        module = CurvedPVModule.thin_film_from_cell_number_and_dimensions(
            -15,
            0.02,
            0.02,
            0.5,
            15,
            offset_angle=90,
            polytunnel_curve=self.curve,
            module_centre_offset=0,
        )

    def test_offset_angle_not_allowed(self) -> None:
        """Tests the case where the offset angle is not allowed."""

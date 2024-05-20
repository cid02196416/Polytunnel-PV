#!/usr/bin/python3.10
########################################################################################
# bypass_diode.py - Module to represent bypass diodes.                                 #
#                                                                                      #
# Author: Ben Winchester                                                               #
# Copyright: Ben Winchester, 2024                                                      #
# Date created: 18/05/2024                                                             #
# License: Open source                                                                 #
# Time created: 14:24:00                                                               #
########################################################################################
"""
bypass_diode.py - The bypass-diodde module for Polytunnel-PV.

This module provides functionality for the modelling of bypass diodes within PV modules.

"""

from dataclasses import dataclass

import numpy as np

from .pv_cell import PVCell

__all__ = ("BypassDiode", "BypassedCellString")


@dataclass(kw_only=True)
class BypassDiode:
    """
    Represents a bypass diode.

    .. attribute:: bypass_voltage
        The voltage at which the bypass diode will kick in and bypass the cell series.

    .. attribute:: end_index
        The end index for which to bypass cells.

    .. attribute:: start_index
        The start index for which to bypass cells.

    """

    bypass_voltage: float
    end_index: int
    start_index: int


@dataclass(kw_only=True)
class BypassedCellString:
    """
    Represents a series of cells in a string, bypassed by a single diode.

    .. attribute:: bypass_diode
        The bypass diode installed.

    .. attribute:: pv_cells
        The `list` of PV cells that are in series and bypassed by the diode.

    """

    bypass_diode: BypassDiode
    pv_cells: list[PVCell]

    @property
    def breakdown_voltage(self) -> float:
        """
        Return the breakdown voltage, i.e., the bypass-diode voltage.

        Returns:
            - The breakdown voltage.

        """

        return self.bypass_diode.bypass_voltage

    @property
    def cell_id(self) -> float:
        """
        Return the cell ID for the fist cell in the string.

        Returns:
            - The cell ID of the first cell within the string.

        """

        return min([cell.cell_id for cell in self.pv_cells])

    def __hash__(self) -> int:
        """
        Return a hash of the first cell ID.

        """

        return hash(self.cell_id)

    def calculate_iv_curve(
        self,
        ambient_celsius_temperature: float,
        irradiance_array: np.ndarray,
        *,
        current_series: np.ndarray | None = None,
        voltage_series: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Calculate the IV curve for the bypassed string of cells.

        Inputs:
            - ambient_celsius_temperature:
                The ambient temperature in degrees Celsius.
            - irradiance_array:
                The array of irradiance values across the PV module.

        """

        # Calculate the curves for each cell
        cell_to_iv_series: dict[PVCell, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for pv_cell in self.pv_cells:
            cell_to_iv_series[pv_cell] = pv_cell.calculate_iv_curve(
                ambient_celsius_temperature,
                irradiance_array,
                current_series=current_series,
                voltage_series=voltage_series,
            )

        # Add up the voltage for each cell
        combined_voltage_series = sum(
            cell_to_iv_series[pv_cell][2] for pv_cell in self.pv_cells
        )

        # Bypass based on the diode voltage.
        combined_voltage_series = np.array(
            [
                max(entry, self.bypass_diode.bypass_voltage)
                for entry in combined_voltage_series
            ]
        )

        # Re-compute the combined power series.
        combined_power_series = (
            current_series := cell_to_iv_series[self.pv_cells[0]][0]
        ) * combined_voltage_series

        return current_series, combined_power_series, combined_voltage_series

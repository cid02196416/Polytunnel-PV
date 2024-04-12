#!/usr/bin/python3.10
########################################################################################
# __main__.py - Main module for Polytunnel-PV.                                         #
#                                                                                      #
# Author: Ben Winchester                                                               #
# Copyright: Ben Winchester, 2024                                                      #
# Date created: 21/02/2024                                                             #
# License: Open source                                                                 #
########################################################################################
"""
__main__.py - The main module for Polytunnel-PV.

Polytunnel-PV simulates the performance of curved photovoltaic modules for polytunnel
and greenhouse applications. This main module provides a command-line interface
entrypoint for executing the model.

"""

__version__ = "1.0.0a1"

import functools
import os
import pvlib
import re
import sys
import yaml

from multiprocessing import Pool
from typing import Any, Hashable

import pandas as pd

from tqdm import tqdm

from .pv_module.pv_cell import get_irradiance
from .pv_module.pv_module import (
    Curve,
    CurveType,
    CurvedPVModule,
    ModuleType,
    TYPE_TO_CURVE_MAPPING,
)
from .scenario import Scenario

# FILE_ENCODING:
#   The encoding to use when opening and closing files.
FILE_ENCODING: str = "UTF-8"

# INPUT_DATA_DIRECTORY:
#   The name of the input-data directory.
INPUT_DATA_DIRECTORY: str = "input_data"

# IRRADIANCE_DIFFUSE:
#   Keyword for diffuse irradiance.
IRRADIANCE_DIFFUSE: str = "irradiance_diffuse"

# IRRADIANCE_DIRECT:
#   Keyword for direct irradiance.
IRRADIANCE_DIRECT: str = "irradiance_direct"

# LOCAL_TIME:
#   Column header for local-time column.
LOCAL_TIME: str = "local_time"

# LOCATIONS_FILENAME:
#   The filename for the locations file.
LOCATIONS_FILENAME: str = "locations.yaml"

# POLYTUNNEL_CURVE@
#   Keyword used for parsing the information about the curve on which a solar panel
# sits.
POLYTUNNEL_CURVE: str = "polytunnel_curve"

# POLYTUNNELS_FILENAME:
#   The name of the polytunnels file.
POLYTUNNELS_FILENAME: str = "polytunnels.yaml"

# PV_MODULES_FILENAME:
#   The name of the PV-modules file.
PV_MODULES_FILENAME: str = "pv_modules.yaml"

# SCENARIOS_FILENAME:
#   The name of the scenarios file.
SCENARIOS_FILENAME: str = "scenarios.yaml"

# SOLAR_AZIMUTH:
#   Keyword for solar azimuth.
SOLAR_AZIMUTH: str = "azimuth"

# SOLAR_ZENITH:
#   Keyword for apparent zenith.
SOLAR_ZENITH: str = "apparent_zenith"

# TEMPERATURE:
#   Column header for temperature column.
TEMPERATURE: str = "temperature"

# TYPE:
#   Keyword used to determine the module type of the PV.
TYPE: str = "type"

# WEATHER_DATA_DIRECTORY:
#   The directory where weather data should be found.
WEATHER_DATA_DIRECTORY: str = "weather_data"

# WEATHER_DATA_REGEX:
#   Regex used for parsing location names from weather data.
WEATHER_DATA_REGEX = re.compile(r"ninja_pv_(?P<location_name>.*)\.csv")

# WEATHER_FILE_WITH_SOLAR:
#   The name of the weather file with the solar data.
WEATHER_FILE_WITH_SOLAR: str = os.path.join(
    "auto_generated", "w_with_s_{location_name}.csv"
)


def _parse_locations() -> list[pvlib.location.Location]:
    """Parses the locations based on the input file."""

    with open(
        os.path.join(INPUT_DATA_DIRECTORY, LOCATIONS_FILENAME),
        "r",
        encoding=FILE_ENCODING,
    ) as f:
        locations_data = yaml.safe_load(f)

    try:
        return [pvlib.location.Location(**entry) for entry in locations_data]
    except KeyError:
        raise KeyError("Not all location information present in locations file.")


def _parse_polytunnel_curves() -> list[Curve]:
    """Parse the polytunnel curves from the files."""

    with open(
        os.path.join(INPUT_DATA_DIRECTORY, POLYTUNNELS_FILENAME),
        "r",
        encoding=FILE_ENCODING,
    ) as f:
        polytunnels_data = yaml.safe_load(f)

    try:
        return [
            TYPE_TO_CURVE_MAPPING[CurveType(polytunnel_entry.pop(TYPE))](  # type: ignore [misc]
                **polytunnel_entry
            )
            for polytunnel_entry in polytunnels_data
        ]
    except KeyError:
        raise KeyError(
            f"Missing type entry with key '{TYPE}' for polytunnel curve."
        ) from None


def _parse_pv_modules(polytunnels: dict[str, Curve]) -> list[CurvedPVModule]:
    """
    Parse the curved PV module information from the files.

    Inputs:
        - polytunnels:
            A mapping between polytunnel names and instances.

    Outputs:
        The parsed PV modules as a list.

    """

    with open(
        os.path.join(INPUT_DATA_DIRECTORY, PV_MODULES_FILENAME),
        "r",
        encoding=FILE_ENCODING,
    ) as f:
        pv_module_data = yaml.safe_load(f)

    def _construct_pv_module(pv_module_entry) -> CurvedPVModule:
        try:
            constructor = CurvedPVModule.constructor_from_module_type(
                ModuleType(pv_module_entry.pop(TYPE))
            )
        except KeyError:
            raise KeyError(
                f"Missing type entry with key '{TYPE}' for PV module."
            ) from None

        pv_module_entry[POLYTUNNEL_CURVE] = polytunnels[
            pv_module_entry[POLYTUNNEL_CURVE]
        ]

        return constructor(**pv_module_entry)

    return [_construct_pv_module(pv_module_entry) for pv_module_entry in pv_module_data]


def _parse_scenarios(
    locations: dict[str, pvlib.location.Location], pv_modules: dict[str, CurvedPVModule]
) -> list[Scenario]:
    """
    Parse the scenario information.

    Inputs:
        - locations:
            The `list` of locations to use.
        - pv_modules:
            The `list` of PVModules that can be installed at each location.

    Outputs:
        - scenarios:
            The `list` of scenarios to run.

    """

    with open(
        os.path.join(INPUT_DATA_DIRECTORY, SCENARIOS_FILENAME),
        "r",
        encoding=FILE_ENCODING,
    ) as f:
        scenarios_data = yaml.safe_load(f)

    return [
        Scenario.from_scenarios_file(entry, locations, pv_modules)
        for entry in scenarios_data
    ]


def _parse_solar() -> dict[str, pd.DataFrame]:
    """Parse the downloaded solar data that's in the weather data directory."""

    location_name_to_data_map: dict[str, pd.DataFrame] = {}

    for filename in os.listdir(WEATHER_DATA_DIRECTORY):
        # Skip the file if it's not in the expected format.
        try:
            location_name = WEATHER_DATA_REGEX.match(filename).group("location_name")  # type: ignore [union-attr]
        except AttributeError:
            continue

        with open(
            os.path.join(WEATHER_DATA_DIRECTORY, filename), "r", encoding=FILE_ENCODING
        ) as f:
            location_name_to_data_map[location_name] = pd.read_csv(f, comment="#")

    return location_name_to_data_map


def _solar_angles_from_weather_row(
    row: tuple[Hashable, pd.Series], location: pvlib.location.Location
) -> pd.DataFrame:
    """
    Use a row from the weather data to comopute the solar angles.

    Inputs:
        - row:
            The row in the weather-data frame.

    Outputs:
        The solar angle-frame at this time.

    """

    return location.get_solarposition(  # type: ignore [no-any-return]
        row[1][LOCAL_TIME], temperature=row[1][TEMPERATURE]
    )


def main(unparsed_arguments) -> None:
    """
    Main method for Polytunnel-PV.

    """

    # Parse all of the input files
    locations = _parse_locations()
    polytunnels = _parse_polytunnel_curves()
    pv_modules = _parse_pv_modules(
        {polytunnel.name: polytunnel for polytunnel in polytunnels}
    )
    scenarios = _parse_scenarios(
        {location.name: location for location in locations},
        {module.name: module for module in pv_modules},
    )

    # Parse the weather data.
    # NOTE: When integrated this as a Python package, this line should be suppressable
    # by weather data being passed in.
    weather_data = _parse_solar()

    # Map locations to weather data.
    locations_with_weather: dict[pvlib.location.Location, pd.DataFrame] = {
        location: weather_data[location.name]
        for location in locations
        if location.name in weather_data
    }

    # Map of locations to weather data with solar angles.
    locations_with_weather_and_solar: dict[pvlib.location.Location, pd.DataFrame] = {}

    for location, weather_frame in locations_with_weather.items():
        # Open the existing combined file with solar data if it exists
        if os.path.isfile(
            (
                weather_with_solar_filename := WEATHER_FILE_WITH_SOLAR.format(
                    location_name=location.name
                )
            )
        ):
            with open(weather_with_solar_filename, "r", encoding=FILE_ENCODING) as f:
                locations_with_weather_and_solar[location] = pd.read_csv(f, index_col=0)
        else:
            # Compute the solar-position information using the get-irradiance function.
            # with Pool(8) as worker_pool:
            #     solar_position_map = worker_pool.map(_solar_angles_from_weather_row, weather_frame.to_dict().items())
            # this_map = map(functools.partial(_solar_angles_from_weather_row, location=location), weather_frame.iterrows())
            solar_frame = pd.concat(
                [
                    _solar_angles_from_weather_row(row, location)
                    for row in tqdm(
                        weather_frame.iterrows(),
                        desc=location.name.capitalize(),
                        total=len(weather_frame),
                    )
                ]
            )
            locations_with_weather_and_solar[location] = pd.concat(
                [solar_frame.reset_index(drop=True), weather_frame], axis=1
            )
            with open(weather_with_solar_filename, "w", encoding=FILE_ENCODING) as f:
                locations_with_weather_and_solar[location].to_csv(f)  # type: ignore[arg-type]

    # Convert each entry within the values of the mapping to a `dict` for speed.
    locations_to_weather_and_solar_map: dict[
        pvlib.location.Location, list[dict[str, Any]]
    ] = {
        location: entry.to_dict("records")
        for location, entry in locations_with_weather_and_solar.items()
    }

    # Compute the irradiance on each panel for each location.
    cellwise_irradiances = [
        (
            scenario,
            {
                pv_cell: [
                    get_irradiance(
                        pv_cell,
                        entry[IRRADIANCE_DIFFUSE],
                        entry[IRRADIANCE_DIRECT],
                        entry[SOLAR_AZIMUTH],
                        entry[SOLAR_ZENITH],
                    )
                    for entry in locations_to_weather_and_solar_map[scenario.location]
                ]
                for pv_cell in scenario.pv_module.pv_cells
            },
        )
        for scenario in scenarios
    ]


if __name__ == "__main__":
    main(sys.argv[1:])

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

import argparse
import os
import pvlib
import re
import seaborn as sns
import sys
import warnings
import yaml

from matplotlib import pyplot as plt
from matplotlib import rc
from typing import Any, Hashable

import numpy as np
import pandas as pd

from tqdm import tqdm

from .__utils__ import NAME
from .pv_module.bypass_diode import BypassDiode
from .pv_module.pv_cell import (
    calculate_cell_iv_curve,
    get_irradiance,
    relabel_cell_electrical_parameters,
)
from .pv_module.pv_module import (
    Curve,
    CurveType,
    CurvedPVModule,
    ModuleType,
    TYPE_TO_CURVE_MAPPING,
)
from .scenario import Scenario

# BYPASS_DIODES:
#   Keyword for the bypass-diode parameters.
BYPASS_DIODES: str = "bypass_diodes"

# CELL_ELECTRICAL_PARAMETERS:
#   Keyword for the electrical parameters of a PV cell.
CELL_ELECTRICAL_PARAMETERS: str = "cell_electrical_parameters"

# CELL_TYPE:
#   Keyword for the name of the cell-type to use.
CELL_TYPE: str = "cell_type"

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

# IRRADIANCE_DIRECT_NORMAL:
#   Keyword for the DNI.
IRRADIANCE_DIRECT_NORMAL: str = "irradiance_direct_normal"

# IRRADIANCE_GLOBAL_HORIZONTAL:
#   Keyword for the GHI.
IRRADIANCE_GLOBAL_HORIZONTAL: str = "irradiance_global_horizontal"

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

# PV_CELL:
#   Keyword for parsing cell-id information.
PV_CELL: str = "cell_id"

# PV_CELLS_FILENAME:
#   The name of the PV-cells file.
PV_CELLS_FILENAME: str = "pv_cells.yaml"

# PVLIB_DATABASE_NAME:
#   The database to use when fetching data on PV cells from pvilb.
PVLIB_DATABASE_NAME: str = "CECmod"

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

# VOLTAGE_RESOLUTION:
#   The number of points to use for IV plotting.
VOLTAGE_RESOLUTION: int = 1000

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

# ZERO_CELSIUS_OFFSET:
#   The offset to convert between Celsius and Kelvin.
ZERO_CELSIUS_OFFSET: float = 273.15


class ArgumentError(Exception):
    """Raised when incorrect command-line arguments are passed in."""

    def __init__(self, msg: str) -> None:
        """Instantiate with the message `msg`."""

        super().__init__(f"Incorrect CLI arguments: {msg}")


def _parse_args(unparsed_args: list[str]) -> argparse.Namespace:
    """
    Parse the command-line arguments.

    Inputs:
        - unparsed_args:
            The unparsed command-line arguments.

    """

    parser = argparse.ArgumentParser()

    # Scenario:
    #   The name of the scenario to use.
    parser.add_argument(
        "--scenario", "-s", type=str, help="The name of the scenario to use."
    )

    # Weather-data arguments.
    weather_arguments = parser.add_argument_group("weather-data arguments")
    # Regenerate:
    #   Used to re-calculate the solar weather information.
    weather_arguments.add_argument(
        "--regenerate",
        "-rw",
        action="store_true",
        default=False,
        help="Recalculate the weather and solar information.",
    )

    return parser.parse_args(unparsed_args)


def _parse_cells() -> list[dict[str, float]]:
    """
    Parses the PV cell parameters based on the input file.

    PV cells can either be fetched from a database of `pvlib` information or specified
    by the user. If the user is specifying the cell parameters, then this is done in the
    input file.

    """

    with open(
        os.path.join(INPUT_DATA_DIRECTORY, PV_CELLS_FILENAME),
        "r",
        encoding=FILE_ENCODING,
    ) as f:
        return yaml.safe_load(f)


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


def _parse_pv_modules(
    polytunnels: dict[str, Curve], user_defined_pv_cells: dict[str, dict[str, float]]
) -> list[CurvedPVModule]:
    """
    Parse the curved PV module information from the files.

    Inputs:
        - polytunnels:
            A mapping between polytunnel names and instances.
        - user_defined_pv_cells:
            A mapping between PV cell name and pv cell information.

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

        # Attempt to determine the PV-cell parameters
        try:
            cell_type_name: str = pv_module_entry.pop(CELL_TYPE)
        except KeyError:
            raise KeyError(
                "Need to specify name of PV-cell material in pv-module file."
            ) from None

        # Try first to find the cell definition in a user-defined scope.
        try:
            cell_electrical_parameters = user_defined_pv_cells[cell_type_name]
        except KeyError:
            # Look within the pvlib database for the cell name.
            try:
                cell_electrical_parameters = (
                    pvlib.pvsystem.retrieve_sam(PVLIB_DATABASE_NAME)
                    .loc[:, cell_type_name]
                    .to_dict()
                )
            except KeyError:
                raise Exception(
                    f"Could not find cell name {cell_type_name} within either local or "
                    "pvlib-imported scope."
                ) from None

        # Create bypass diodes based on the information provided.
        try:
            pv_module_entry[BYPASS_DIODES] = (
                [BypassDiode(**entry) for entry in pv_module_entry[BYPASS_DIODES]]
                if BYPASS_DIODES in pv_module_entry
                else []
            )
        except KeyError as caught_error:
            raise Exception(
                "Missing bypass diode information for pv module."
            ) from caught_error

        # Map the parameters to those electrical parameters that the cell is expecting.
        pv_module_entry[CELL_ELECTRICAL_PARAMETERS] = (
            relabel_cell_electrical_parameters(cell_electrical_parameters)
        )

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


def plot_irradiance_with_marginal_means(
    data_to_plot: pd.DataFrame,
    start_index: int = 0,
    *,
    figname: str = "output_figure",
    fig_format: str = "eps",
    heatmap_vmax: float | None = None,
    irradiance_bar_vmax: float | None = None,
    irradiance_scatter_vmax: float | None = None,
    irradiance_scatter_vmin: float | None = None,
    show_figure: bool = True,
) -> None:
    """
    Plot the irradiance heatmap with marginal means.

    Inputs:
        - data_to_plot:
            The data to plot.
        - start_index:
            The index to start plotting from.
        - figname:
            The name to use when saving the figure.
        - fig_format:
            The file extension format to use when saving the high-resolution output
            figures.
        - heatmap_vmax:
            The maximum plotting value to use for the irradiance heatmap.
        - irradiance_bar_vmax:
            The maximum plotting value to use for the irradiance bars.
        - irradiance_scatter_vmax:
            The maximum plotting value to use for the irradiance scatter.
        - irradiance_scatter_vmin:
            The minimum plotting value to use for the irradiance scatter.

    """

    sns.set_style("ticks")
    frame_slice = data_to_plot.iloc[start_index : start_index + 24].set_index("hour")

    # Create a dummy plot and surrounding axes.
    joint_plot_grid = sns.jointplot(
        data=frame_slice,
        kind="hist",
        bins=(len(frame_slice.columns), 24),
        marginal_ticks=True,
    )
    joint_plot_grid.ax_marg_y.cla()
    joint_plot_grid.ax_marg_x.cla()

    # Generate the central heatmap.
    sns.heatmap(
        frame_slice,
        ax=joint_plot_grid.ax_joint,
        cmap=sns.blend_palette(
            ["#144E56", "teal", "#94B49F", "orange", "#E04606"], as_cmap=True
        ),
        vmin=0,
        vmax=heatmap_vmax,
        cbar=True,
        cbar_kws={"label": "Irradiance / kWm$^{-2}$"},
    )

    # Plot the irradiance bars on the RHS of the plot.
    joint_plot_grid.ax_marg_y.barh(
        np.arange(0.5, 24.5), frame_slice.mean(axis=1).to_numpy(), color="#E04606"
    )
    joint_plot_grid.ax_marg_y.set_xlim(0, irradiance_bar_vmax)

    # Plot the scatter at the top of the plot.
    joint_plot_grid.ax_marg_x.scatter(
        np.arange(0.5, len(frame_slice.columns) + 0.5),
        (cellwise_means := frame_slice.sum(axis=0).to_numpy()),
        color="#144E56",
        marker="D",
        s=60,
        alpha=0.7,
    )
    joint_plot_grid.ax_marg_x.set_ylim(irradiance_scatter_vmin, irradiance_scatter_vmax)

    joint_plot_grid.ax_joint.set_xlabel("Mean angle from polytunnel axis")
    joint_plot_grid.ax_joint.set_ylabel("Hour of the day")
    joint_plot_grid.ax_joint.legend().remove()

    # Remove ticks from axes
    joint_plot_grid.ax_marg_x.tick_params(axis="x", bottom=False, labelbottom=False)
    joint_plot_grid.ax_marg_x.set_xlabel("Average irradiance / kWm$^{-2}$")
    joint_plot_grid.ax_marg_y.tick_params(axis="y", left=False, labelleft=False)
    # joint_plot_grid.ax_marg_y.set_xlabel("Average irradiance / kWm$^{-2}$")
    # remove ticks showing the heights of the histograms
    # joint_plot_grid.ax_marg_x.tick_params(axis='y', left=False, labelleft=False)
    # joint_plot_grid.ax_marg_y.tick_params(axis='frame_slice', bottom=False, labelbottom=False)

    joint_plot_grid.ax_marg_x.grid("on")
    # joint_plot_grid.ax_marg_x.set_ylabel("Average irradiance")  #

    joint_plot_grid.figure.tight_layout()

    # Adjust the plot such that the colourbar appears to the RHS.
    # Solution from JohanC (https://stackoverflow.com/users/12046409/johanc)
    # Obtained with permission from stackoverflow:
    # https://stackoverflow.com/questions/60845764/how-to-add-a-colorbar-to-the-side-of-a-kde-jointplot
    #
    plt.subplots_adjust(left=0.1, right=0.8, top=0.9, bottom=0.1)
    pos_joint_ax = joint_plot_grid.ax_joint.get_position()
    pos_marg_x_ax = joint_plot_grid.ax_marg_x.get_position()
    joint_plot_grid.ax_joint.set_position(
        [pos_joint_ax.x0, pos_joint_ax.y0, pos_marg_x_ax.width, pos_joint_ax.height]
    )
    joint_plot_grid.figure.axes[-1].set_position(
        [0.83, pos_joint_ax.y0, 0.07, pos_joint_ax.height]
    )

    # Save the figure in high- and low-resolution formats.
    plt.savefig(
        f"{figname}.{fig_format}",
        transparent=True,
        format=fig_format,
        dpi=300,
        bbox_inches="tight",
    )
    plt.savefig(
        f"{figname}.png",
        transparent=True,
        format="png",
        dpi=300,
        bbox_inches="tight",
    )

    if show_figure:
        plt.show()


def main(unparsed_arguments) -> None:
    """
    Main method for Polytunnel-PV.

    """

    # Matplotlib setup
    rc("font", **{"family": "sans-serif", "sans-serif": ["Arial"]})
    sns.set_context("paper")
    sns.set_style("whitegrid")

    # Parse the command-line arguments.
    parsed_args = _parse_args(unparsed_arguments)

    # Parse all of the input files
    locations = _parse_locations()
    polytunnels = _parse_polytunnel_curves()
    user_defined_pv_cells = _parse_cells()
    pv_modules = _parse_pv_modules(
        {polytunnel.name: polytunnel for polytunnel in polytunnels},
        {entry[NAME]: entry for entry in user_defined_pv_cells},
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
        if (
            os.path.isfile(
                (
                    weather_with_solar_filename := WEATHER_FILE_WITH_SOLAR.format(
                        location_name=location.name
                    )
                )
            )
            and not parsed_args.regenerate
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

            # Compute the GHI from this information.
            weather_frame[IRRADIANCE_GLOBAL_HORIZONTAL] = (
                weather_frame[IRRADIANCE_DIRECT] + weather_frame[IRRADIANCE_DIFFUSE]
            )

            # Compute the DNI from this information.
            weather_frame[IRRADIANCE_DIRECT_NORMAL] = pvlib.irradiance.dni(
                weather_frame[IRRADIANCE_GLOBAL_HORIZONTAL].reset_index(drop=True),
                pd.Series(weather_frame[IRRADIANCE_DIFFUSE]).reset_index(drop=True),
                pd.Series(solar_frame[SOLAR_ZENITH]).reset_index(drop=True),
            )

            # Generate and save the combined frame.
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
            [
                {
                    entry[LOCAL_TIME]: get_irradiance(
                        pv_cell,
                        entry[IRRADIANCE_DIFFUSE],
                        entry[IRRADIANCE_GLOBAL_HORIZONTAL],
                        entry[SOLAR_AZIMUTH],
                        entry[SOLAR_ZENITH],
                        direct_normal_irradiance=entry[IRRADIANCE_DIRECT_NORMAL],
                    )
                    for entry in locations_to_weather_and_solar_map[scenario.location]
                }
                for pv_cell in scenario.pv_module.pv_cells
            ],
        )
        for scenario in scenarios
    ]

    # Transform to a pandas DataFrame for plotting.
    cellwise_irradiance_frames: list[tuple[Scenario, pd.DataFrame]] = []
    for scenario, irradiances_list in cellwise_irradiances:
        hourly_frames: list[pd.DataFrame] = []
        for cell_id, hourly_irradiances in enumerate(irradiances_list):
            hourly_frame = pd.DataFrame.from_dict(hourly_irradiances, orient="index")
            hourly_frame.columns = pd.Index([cell_id])
            hourly_frames.append(hourly_frame)

        combined_frame = pd.concat(hourly_frames, axis=1)
        combined_frame.sort_index(axis=1, inplace=True, ascending=False)
        combined_frame["hour"] = [
            int(entry.split(" ")[1].split(":")[0])
            for entry in hourly_frame.index.to_series()
        ]

        # Use the cell angle from the axis as the column header
        combined_frame.columns = [
            f"{'-' if pv_cell.cell_id / len(scenario.pv_module.pv_cells) < 0.5 else ''}{str(round(pv_cell.tilt, 3))}"
            for pv_cell in scenario.pv_module.pv_cells
        ] + ["hour"]

        cellwise_irradiance_frames.append((scenario, combined_frame))

    # Extract the information for just the scenario that should be plotted.
    try:
        scenario = {scenario.name: scenario for scenario in scenarios}[
            parsed_args.scenario
        ]
    except KeyError:
        if parsed_args.scenario is None:
            raise ArgumentError(
                "Scenario must be specified on the command-line."
            ) from None
        raise KeyError(
            f"Scenario {parsed_args.scenario} not found in scenarios file. Valid scenarios: {', '.join([s.name for s in scenarios])}"
        ) from None

    try:
        irradiance_frame = [
            entry[1] for entry in cellwise_irradiance_frames if entry[0] == scenario
        ][0]
    except IndexError:
        raise Exception("Internal error occurred.") from None

    current_series = np.linspace(
        0,
        2
        * np.max(
            [pv_cell.short_circuit_current for pv_cell in scenario.pv_module.pv_cells]
        ),
        VOLTAGE_RESOLUTION,
    )
    voltage_series = np.linspace(
        np.min(
            [
                pv_cell.breakdown_voltage
                for pv_cell in scenario.pv_module.pv_cells_and_cell_strings
            ]
        ),
        100,
        VOLTAGE_RESOLUTION,
    )

    sns.set_palette(
        sns.cubehelix_palette(
            start=-0.2, rot=-0.2, n_colors=len(scenario.pv_module.pv_cells)
        )
    )

    time_of_day: int = 8 + 24 * 31 * 6

    for pv_cell in tqdm(scenario.pv_module.pv_cells, desc="Plotting PV cell"):
        # Determine the cell temperature
        cell_temperature = pv_cell.average_cell_temperature(
            (
                ambient_celsius_temperature := locations_to_weather_and_solar_map[
                    scenario.location
                ][time_of_day][TEMPERATURE]
            )
            + ZERO_CELSIUS_OFFSET,
            (
                solar_irradiance := (
                    1000
                    * irradiance_frame.set_index("hour")
                    .iloc[time_of_day]
                    .values[pv_cell.cell_id]
                )
            ),
            0,
        )
        current_series, power_series, voltage_series = calculate_cell_iv_curve(
            cell_temperature, solar_irradiance, pv_cell, current_series=current_series
        )
        plt.plot(
            # pv_cell.rescale_voltage(voltage_series),
            current_series,
            power_series,
            label=f"Cell #{pv_cell.cell_id}",
        )

    plt.legend()

    plt.show()

    plt.bar(
        [pv_cell.cell_id for pv_cell in scenario.pv_module.pv_cells],
        [
            1000
            * irradiance_frame.set_index("hour")
            .iloc[time_of_day]
            .values[pv_cell.cell_id]
            for pv_cell in scenario.pv_module.pv_cells
        ],
    )

    import pdb

    pdb.set_trace()

    # import matplotlib.patches as mpatches

    # def _post_process_split_axes(ax1, ax2):
    #     """
    #     Function to post-process the joining of axes.
    #     Adapted from:
    #         https://matplotlib.org/stable/gallery/subplots_axes_and_figures/broken_axis.html
    #     """
    #     # hide the spines between ax and ax2
    #     ax1.spines.bottom.set_visible(False)
    #     ax1.spines.top.set_visible(False)
    #     ax2.spines.top.set_visible(False)
    #     ax1.tick_params(
    #         labeltop=False, labelbottom=False
    #     )  # don't put tick labels at the top
    #     ax2.xaxis.tick_bottom()
    #     # Now, let's turn towards the cut-out slanted lines.
    #     # We create line objects in axes coordinates, in which (0,0), (0,1),
    #     # (1,0), and (1,1) are the four corners of the axes.
    #     # The slanted lines themselves are markers at those locations, such that the
    #     # lines keep their angle and position, independent of the axes size or scale
    #     # Finally, we need to disable clipping.
    #     d = 0.5  # proportion of vertical to horizontal extent of the slanted line
    #     kwargs = dict(
    #         marker=[(-1, -d), (1, d)],
    #         markersize=12,
    #         linestyle="none",
    #         color="k",
    #         mec="k",
    #         mew=1,
    #         clip_on=False,
    #     )
    #     ax1.plot([0], [0], transform=ax1.transAxes, **kwargs)
    #     ax2.plot([0], [1], transform=ax2.transAxes, **kwargs)

    # # Joo Plot
    # gridspec = {"hspace": 0.1, "height_ratios": [1, 1, 0.4, 1, 1]}
    # fig, axes = plt.subplots(5, 2, figsize=(48 / 5, 32 / 5), gridspec_kw=gridspec)
    # fig.subplots_adjust(hspace=0, wspace=0.25)

    # axes[2, 0].set_visible(False)
    # axes[2, 1].set_visible(False)
    # y_label_coord: int = int(-850)

    # axes[0, 0].get_shared_x_axes().join(axes[0, 0], axes[1, 0])
    # axes[3, 0].get_shared_x_axes().join(axes[3, 0], axes[4, 0])
    # axes[3, 1].get_shared_x_axes().join(axes[3, 1], axes[4, 1])
    # axes[0, 1].get_shared_x_axes().join(axes[0, 1], axes[1, 1])

    # curve_info = pvlib.pvsystem.singlediode(
    #     photocurrent=IL,
    #     saturation_current=I0,
    #     resistance_series=Rs,
    #     resistance_shunt=Rsh,
    #     nNsVth=nNsVth,
    #     ivcurve_pnts=100,
    #     method="lambertw",
    # )
    # plt.plot(curve_info["v"], curve_info["i"])
    # plt.show()

    # pvlib.singlediode.bishop88_i_from_v(
    #     -14.95,
    #     photocurrent=IL,
    #     saturation_current=I0,
    #     resistance_series=Rs,
    #     resistance_shunt=Rsh,
    #     nNsVth=nNsVth,
    #     breakdown_voltage=-15,
    #     breakdown_factor=2e-3,
    #     breakdown_exp=3,
    # )

    # v_oc = pvlib.singlediode.bishop88_v_from_i(
    #     0.0,
    #     photocurrent=IL,
    #     saturation_current=I0,
    #     resistance_series=Rs,
    #     resistance_shunt=Rsh,
    #     nNsVth=nNsVth,
    #     method="lambertw",
    # )
    # voltage_array = np.linspace(-15 * 0.999, v_oc, 1000)
    # ivcurve_i, ivcurve_v, _ = pvlib.singlediode.bishop88(
    #     voltage_array,
    #     photocurrent=IL,
    #     saturation_current=I0,
    #     resistance_series=Rs,
    #     resistance_shunt=Rsh,
    #     nNsVth=nNsVth,
    #     breakdown_voltage=-15,
    # )

    start_index: int = 0
    frame_slice = (
        cellwise_irradiance_frames[0][1]
        .iloc[start_index : start_index + 24]
        .set_index("hour")
    )
    sns.heatmap(
        frame_slice,
        cmap=sns.blend_palette(
            [
                "#144E56",
                "#28769C",
                "teal",
                "#94B49F",
                "grey",
                "silver",
                "orange",
                "#E04606",
            ],
            as_cmap=True,
        ),
        vmin=0,
        cbar_kws={"label": "Irradiance / kWm$^{-2}$"},
    )
    plt.xlabel("Cell index within panel")
    plt.ylabel("Hour of the day")
    plt.show()

    plot_irradiance_with_marginal_means(
        cellwise_irradiance_frames[0][1],
        start_index=(start_index := 24 * 31 * 6 + 48),
        figname="july_eight_small_panel",
        heatmap_vmax=(
            heatmap_vmax := cellwise_irradiance_frames[2][1]
            .set_index("hour")
            .iloc[start_index : start_index + 24]
            .max()
            .max()
        ),
        irradiance_bar_vmax=(
            irradiance_bar_vmax := (
                max(
                    cellwise_irradiance_frames[0][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .mean(axis=1)
                    .max(),
                    cellwise_irradiance_frames[1][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .mean(axis=1)
                    .max(),
                    cellwise_irradiance_frames[2][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .mean(axis=1)
                    .max(),
                )
            )
        ),
        irradiance_scatter_vmin=0,
        irradiance_scatter_vmax=(
            irradiance_scatter_vmax := 1.25
            * (
                max(
                    cellwise_irradiance_frames[0][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .sum(axis=0)
                    .max(),
                    cellwise_irradiance_frames[1][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .sum(axis=0)
                    .max(),
                    cellwise_irradiance_frames[2][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .sum(axis=0)
                    .max(),
                )
            )
        ),
    )
    plot_irradiance_with_marginal_means(
        cellwise_irradiance_frames[1][1],
        start_index=start_index,
        figname="july_eighth_medium_panel",
        heatmap_vmax=heatmap_vmax,
        irradiance_bar_vmax=irradiance_bar_vmax,
        irradiance_scatter_vmin=0,
        irradiance_scatter_vmax=irradiance_scatter_vmax,
    )
    plot_irradiance_with_marginal_means(
        cellwise_irradiance_frames[2][1],
        start_index=start_index,
        figname="july_eighth_large_panel",
        heatmap_vmax=heatmap_vmax,
        irradiance_bar_vmax=irradiance_bar_vmax,
        irradiance_scatter_vmin=0,
        irradiance_scatter_vmax=irradiance_scatter_vmax,
    )

    plot_irradiance_with_marginal_means(
        cellwise_irradiance_frames[0][1],
        start_index=(start_index := 24 * 31 * 7 + 48),
        figname="august_eight_small_panel",
        heatmap_vmax=(
            heatmap_vmax := cellwise_irradiance_frames[2][1]
            .set_index("hour")
            .iloc[start_index : start_index + 24]
            .max()
            .max()
        ),
        irradiance_bar_vmax=(
            irradiance_bar_vmax := (
                max(
                    cellwise_irradiance_frames[0][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .mean(axis=1)
                    .max(),
                    cellwise_irradiance_frames[1][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .mean(axis=1)
                    .max(),
                    cellwise_irradiance_frames[2][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .mean(axis=1)
                    .max(),
                )
            )
        ),
        irradiance_scatter_vmin=0,
        irradiance_scatter_vmax=(
            irradiance_scatter_vmax := 1.25
            * (
                max(
                    cellwise_irradiance_frames[0][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .sum(axis=0)
                    .max(),
                    cellwise_irradiance_frames[1][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .sum(axis=0)
                    .max(),
                    cellwise_irradiance_frames[2][1]
                    .set_index("hour")
                    .iloc[start_index : start_index + 24]
                    .sum(axis=0)
                    .max(),
                )
            )
        ),
    )
    plot_irradiance_with_marginal_means(
        cellwise_irradiance_frames[1][1],
        start_index=start_index,
        figname="august_eighth_medium_panel",
        heatmap_vmax=heatmap_vmax,
        irradiance_bar_vmax=irradiance_bar_vmax,
        irradiance_scatter_vmin=0,
        irradiance_scatter_vmax=irradiance_scatter_vmax,
    )
    plot_irradiance_with_marginal_means(
        cellwise_irradiance_frames[2][1],
        start_index=start_index,
        figname="august_eighth_large_panel",
        heatmap_vmax=heatmap_vmax,
        irradiance_bar_vmax=irradiance_bar_vmax,
        irradiance_scatter_vmin=0,
        irradiance_scatter_vmax=irradiance_scatter_vmax,
    )

    weather = list(locations_with_weather_and_solar.values())[0]
    data_to_scatter = weather.iloc[start_index : start_index + 24]
    plt.scatter(
        range(24),
        data_to_scatter["irradiance_direct"],
        marker="H",
        s=40,
        label="Direct irradiance",
    )
    plt.scatter(
        range(24),
        data_to_scatter["irradiance_diffuse"],
        marker="H",
        s=40,
        label="Diffuse irradiance",
    )
    plt.scatter(
        range(24),
        data_to_scatter["irradiance_direct_normal"],
        marker="H",
        s=40,
        label="DNI irradiance",
    )
    plt.legend()
    plt.show()

    (
        frame_slice := cellwise_irradiance_frames[2][1].iloc[
            start_index : start_index + 24
        ]
    ).plot(
        x="hour",
        y=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        colormap=sns.color_palette("PuBu_r", n_colors=18, as_cmap=True),
    )


if __name__ == "__main__":
    main(sys.argv[1:])

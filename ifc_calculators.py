# ifc_calculators.py

import pvlib
import pandas as pd
from typing import Any
from ifc_parsers import Site, Window
from typing import Tuple, List, Dict

# def window_solar_inflow(window: Window, site: Site, timestamp: pd.Timestamp) -> float:
#     """
#     Calculate the solar inflow through a single window over a fixed 5-minute interval,
#     using the site’s location metadata and the window’s area and SHGC.
#     """
#     # get “now” in the site’s timezone
#     # solar_in_time = pd.Timestamp.now(tz=site.timezone)

#     # using specific timestamp for testing
#     solar_in_time = timestamp.tz_convert(site.timezone) if timestamp.tzinfo else timestamp.tz_localize(site.timezone)

#     # compute sun position
#     solpos = pvlib.solarposition.get_solarposition(
#         solar_in_time, site.latitude, site.longitude, site.elevation
#     )
#     apparent_zenith = float(solpos["apparent_zenith"].iloc[0])

#     # very simple direct-beam model (800 W/m² if above horizon)
#     I_direct = 800.0 if apparent_zenith < 90 else 0.0

#     # 5-minute duration
#     duration_seconds = 5 * 60  

#     # J = W/m² * m² * SHGC * s
#     return window.area * window.SHGC * I_direct * duration_seconds




def window_solar_inflow(window: Window, site: Site, timestamp: pd.Timestamp) -> Tuple[float, float, float, float, float]:
    """
    Calculate the solar inflow through a single window over a fixed 5-minute interval,
    using the site’s location metadata and the window’s area and SHGC.
    Returns: area, shgc, tilt, azimuth, inflow 
    inflow, window.area, window.SHGC
    """
    # get “now” in the site’s timezone
    # solar_in_time = pd.Timestamp.now(tz=site.timezone)

    # using specific timestamp for testing
    solar_in_time = timestamp.tz_convert(site.timezone) if timestamp.tzinfo else timestamp.tz_localize(site.timezone)

    # Create a time index
    time = pd.DatetimeIndex([solar_in_time])

    # Solar position
    solpos = pvlib.solarposition.get_solarposition(time, site.latitude, site.longitude)

    # Airmass (absolute)
    airmass = pvlib.atmosphere.get_absolute_airmass(
        pvlib.atmosphere.get_relative_airmass(solpos["apparent_zenith"])
    )

    # Linke turbidity
    linke_turbidity = pvlib.clearsky.lookup_linke_turbidity(time, site.latitude, site.longitude)

    altitude = site.elevation if site.elevation is not None else 0
    # Now use ineichen correctly
    clearsky = pvlib.clearsky.ineichen(
        apparent_zenith=solpos["apparent_zenith"],
        airmass_absolute=airmass,
        linke_turbidity=linke_turbidity,
        altitude=altitude
    )

    # Get direct normal irradiance (DNI), diffuse horizontal (DHI), global horizontal (GHI)
    dni = clearsky["dni"].iloc[0]
    dhi = clearsky["dhi"].iloc[0]

    # Get window tilt and azimuth (assuming vertical south-facing for simplicity)
    tilt = window.tilt # degrees
    azimuth = window.azimuth
    if tilt is None:
        tilt = 90.0
    if azimuth is None:
        error_msg = f"Window {window.global_id} has no azimuth set, cannot calculate solar inflow."
        raise ValueError(error_msg)
    # Calculate plane-of-array (POA) irradiance
    poa_irradiance = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        dni=dni,
        ghi=clearsky["ghi"].iloc[0],
        dhi=dhi,
        solar_zenith=solpos["apparent_zenith"].iloc[0],
        solar_azimuth=solpos["azimuth"].iloc[0]
    )
    # extract the single irradiance value as a float
    I_poa = float(poa_irradiance["poa_global"])
    # I_poa = float(poa_irradiance["poa_global"]) #can use this if only one timestamp is passed
    # 5-minute duration
    duration_seconds = 5 * 60  
    inflow = window.area * window.SHGC * I_poa * duration_seconds
    # J = W/m² * m² * SHGC * s
    area = window.area if window.area else 0.0
    shgc = window.SHGC if window.SHGC else 0.0
    tilt = window.tilt if window.tilt else tilt
    azimuth = window.azimuth if window.azimuth else azimuth
    
#  area, shgc, tilt, azimuth, inflow
    return area, shgc, tilt, azimuth, inflow
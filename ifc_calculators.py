# ifc_calculators.py

import pvlib
import pandas as pd
from typing import Any
from ifc_parsers import Site, Window

def window_solar_inflow(window: Window, site: Site, timestamp: pd.Timestamp) -> float:
    """
    Calculate the solar inflow through a single window over a fixed 5-minute interval,
    using the site’s location metadata and the window’s area and SHGC.
    """
    # get “now” in the site’s timezone
    # solar_in_time = pd.Timestamp.now(tz=site.timezone)

    # using specific timestamp for testing
    solar_in_time = timestamp.tz_convert(site.timezone) if timestamp.tzinfo else timestamp.tz_localize(site.timezone)

    # compute sun position
    solpos = pvlib.solarposition.get_solarposition(
        solar_in_time, site.latitude, site.longitude, site.elevation
    )
    apparent_zenith = float(solpos["apparent_zenith"].iloc[0])

    # very simple direct-beam model (800 W/m² if above horizon)
    I_direct = 800.0 if apparent_zenith < 90 else 0.0

    # 5-minute duration
    duration_seconds = 5 * 60  

    # J = W/m² * m² * SHGC * s
    return window.area * window.SHGC * I_direct * duration_seconds
import os
import ifcopenshell
from pathlib import Path
from typing import Union, Optional
from typing import Any
import pandas as pd
from datetime import datetime
import pytz
from meteostat import Point, Hourly

#  for xgboost
import joblib
from pathlib import Path

# Import mediator functions
from ifc_parsers import parse_room, BoundingBox, Window, Room, Site
from ifc_calculators import window_solar_inflow

IFC_PATH = os.path.join("static", "IFC", "BK_v2_vb_updated.ifc")

def get_current_external_temp(site: Site, timestamp: pd.Timestamp) -> Optional[float]:
    loc = Point(site.latitude, site.longitude, site.elevation)
    rounded_time = timestamp.floor('h')
    if rounded_time.tzinfo:
        rounded_time = rounded_time.tz_convert('UTC').tz_localize(None)
    df_weather = Hourly(loc, rounded_time, rounded_time).fetch()
    if not df_weather.empty:
        return float(df_weather['temp'].iloc[0])
    print(f"[WARNING] No external temperature data found for {rounded_time}")
    return None

def get_latest_model(path: str = "xgboost_models") -> Optional[Any]:
    models = sorted(Path(path).glob("xgb_pipeline_*.joblib"), reverse=True)
    if not models:
        raise FileNotFoundError("No XGBoost model found in 'xgboost_models/'")
    return joblib.load(models[0])

def predict_internal_temp(room_name: str, ifc_path: Union[str, Path] = IFC_PATH) -> float:
    """
    Mediator function: given a room_name, extracts site and room details from corrected BK IFC
    """

    # Parse SELECTED ROOM into a Site object that has locational data
    site: Site = parse_room(ifc_path, room_name)
    # parse_room invokes extract_site_details internally to add locational data

    # Attempt to find the room by its long_name key
    room: Optional[Room] = site.rooms.get(room_name)
    # If eaxct match not found - try case-insensitive match
    if room is None:
        for key, r in site.rooms.items():
            if key.lower() == room_name.strip().lower():
                room = r
                break
    if room is None:
        raise ValueError(f"No room named '{room_name}' found in IFC rooms")

    # Serialize windows for output along with solar_inflow for each
    now = datetime.now(pytz.timezone(site.timezone))
    timestamp = pd.Timestamp(now)
    windows_out = []
    total_solar_inflow = 0.0
    if room.windows:
        for w in room.windows:
            # compute solar inflow for this window
            inflow = window_solar_inflow(w, site, timestamp)
            total_solar_inflow += inflow
    # Get external temperature
    external_temp = get_current_external_temp(site, timestamp)
    if external_temp is None:
        raise ValueError("Failed to retrieve external temperature")
    
    # Load latest model
    model = get_latest_model()

    # Construct input for prediction
    input_df = pd.DataFrame([{
        "external_temp": external_temp,
        "volume": room.volume,
        "solar_inflow": total_solar_inflow
    }])
    # Run prediction
    predicted_temp = model.predict(input_df)[0]
    return float(predicted_temp)
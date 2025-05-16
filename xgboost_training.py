import os
import pandas as pd
import requests
from typing import Optional
from xgboost import XGBRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
import joblib
from pathlib import Path
from ifc_parsers import Site, Room, Window
from ifc_calculators import window_solar_inflow
from meteostat import Point, Hourly
from datetime import datetime

#  THIS FILE IS FOR TRAINING THE XGBOOST MODEL - IT IS A STANDALONE SCRIPT

def fetch_sensor_data(url: str, limit: int = 100) -> pd.DataFrame:
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    observations = data.get('value', [])
    df = pd.DataFrame([
        {'timestamp': obs.get('phenomenonTime'), 'internal_temp': obs.get('result')}
        for obs in observations
    ])
    df = df.drop_duplicates(subset='timestamp')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def fetch_external_temp(site: Site, timestamp: pd.Timestamp) -> Optional[float]:
    loc = Point(site.latitude, site.longitude, site.elevation)
    # round to the nearest hour
    # Meteostat requires a timezone-aware timestamp
    rounded_time = timestamp.floor('h')
    # Ensure timestamp is tz-naive in UTC (for Meteostat)
    if rounded_time.tzinfo:
        rounded_time = rounded_time.tz_convert('UTC').tz_localize(None)
    df_weather = Hourly(loc, rounded_time, rounded_time).fetch()
    if not df_weather.empty:
        return float(df_weather['temp'].iloc[0])
    print(f"[WARNING] No external temperature data found for {rounded_time}")
    return None


def calculate_total_solar_inflow(site: Site, room: Room, timestamp: pd.Timestamp) -> float:
    total_inflow = 0.0
    if not room.windows:
        print(f"[INFO] No windows found for room '{room.long_name}' at {timestamp}")
        return total_inflow
    for window in room.windows:
        inflow = window_solar_inflow(window, site, timestamp)
        total_inflow += inflow
    print(f"[INFO] Total solar inflow at {timestamp}: {total_inflow:.2f} J")
    return total_inflow


def prepare_training_data(df: pd.DataFrame, site: Site, room: Room) -> pd.DataFrame:
    records = []
    for _, row in df.iterrows():
        timestamp = row['timestamp']
        internal_temp = row['internal_temp']
        external_temp = fetch_external_temp(site, timestamp)
        if external_temp is None:
            continue
        solar_inflow = calculate_total_solar_inflow(site, room, timestamp)
        records.append({
            'timestamp': timestamp,
            'internal_temp': internal_temp,
            'external_temp': external_temp,
            'volume': room.volume,
            'solar_inflow': solar_inflow
        })
    return pd.DataFrame(records)


def train_and_save_model(df: pd.DataFrame, model_dir: str = "xgboost_models") -> float:
    X = df[['external_temp', 'volume', 'solar_inflow']]
    y = df['internal_temp']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('xgb', XGBRegressor(n_estimators=100, learning_rate=0.1, max_depth=3, random_state=42))
    ])

    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    # Create model folder if it doesn't exist
    os.makedirs(model_dir, exist_ok=True)
    # Format filename with date
    today = datetime.now().strftime("%Y%m%d")
    model_path = os.path.join(model_dir, f"xgb_pipeline_{today}.joblib")
    # Save model
    joblib.dump(pipeline, model_path)
    print(f"Model saved to {model_path}. MSE: {mse:.2f}")
    return mse


# usage
if __name__ == "__main__":
    from ifc_parsers import parse_room

    # IFC file and room
    ifc_file = Path("static/IFC/BK_v2_vb_updated.ifc")
    room_1 = "BG.West.010"
    site = parse_room(ifc_file, room_1)
    room = site.rooms[room_1]

    # Fetch + process data
    url_1 = "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(1)/Observations?$orderby=phenomenonTime desc"
    df_sensor = fetch_sensor_data(url_1)
    df_train = prepare_training_data(df_sensor, site, room)
    
    # Train + save model
    train_and_save_model(df_train)

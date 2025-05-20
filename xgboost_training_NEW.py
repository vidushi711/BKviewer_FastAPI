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
from ifc_parsers import Site, Room, Window, parse_room
from ifc_calculators import window_solar_inflow
from meteostat import Point, Hourly
from datetime import datetime

# THIS FILE IS FOR TRAINING THE XGBOOST MODEL - IT IS A STANDALONE SCRIPT

def fetch_sensor_data(url: str, limit: int = 100) -> pd.DataFrame:
    """
    Fetch sensor observations from the given URL, optionally limiting the number of records.
    """
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    observations = data.get('value', [])[:limit]
    df = pd.DataFrame([
        {'timestamp': obs.get('phenomenonTime'), 'internal_temp': obs.get('result')}
        for obs in observations
    ])
    df = df.drop_duplicates(subset='timestamp')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def fetch_external_temp(site: Site, timestamp: pd.Timestamp) -> Optional[float]:
    loc = Point(site.latitude, site.longitude, site.elevation)
    rounded_time = timestamp.floor('h')  # use 'h' to avoid deprecation
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
    """
    Given raw observations and IFC room/site info, compute features and tag with room name.
    """
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
            'room_name': room.long_name,
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

    os.makedirs(model_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    model_path = os.path.join(model_dir, f"xgb_pipeline_{today}.joblib")
    joblib.dump(pipeline, model_path)
    print(f"Model saved to {model_path}. MSE: {mse:.2f}")
    return mse


if __name__ == "__main__":
    # Path to IFC file
    IFC_FILE = Path("static/IFC/BK_v2_vb_updated.ifc")

    # Set a higher limit for sensor entries
    SENSOR_LIMIT = 500  # increase from default 100

    # Room definitions
    rooms = [
        ("BG.West.010", "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(1)/Observations?$orderby=phenomenonTime desc"),
        ("BG.West.270", "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(7)/Observations?$orderby=phenomenonTime desc"),
        ("01.West.120", "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(13)/Observations?$orderby=phenomenonTime desc"),
    ]

    df_list = []
    for room_code, url in rooms:
        site = parse_room(IFC_FILE, room_code)
        room = site.rooms[room_code]
        df_raw = fetch_sensor_data(url, limit=SENSOR_LIMIT)
        df_prepared = prepare_training_data(df_raw, site, room)
        df_list.append(df_prepared)

    # Merge all rooms into a single DataFrame
    df_train = pd.concat(df_list, ignore_index=True)

    # Save combined data with room names included
    OUTPUT_DIR = Path("output")
    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUT_DIR / f"combined_training_data_{datetime.now().strftime('%Y%m%d')}.csv"
    df_train.to_csv(csv_path, index=False)
    print(f"Combined training data saved to {csv_path}")

    # Train and save model
    train_and_save_model(df_train)
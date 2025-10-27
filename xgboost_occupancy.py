# pulls CO₂ and Noise from FROST with server-side filtering ($filter, $select, $orderby, $top + pagination),
# builds one  DataFrame with room, timestamp (hourly), co2, noise,
# trains a minimal XGBoost model per room to output an occupancy index,
# lets user scale the index to “people” with a provided constant k



from xgboost import XGBRegressor
import numpy as np
import pandas as pd
import requests
from pathlib import Path

from ifc_parsers import parse_room, Room

# ---------------- config ----------------
LOCAL_TZ = "Europe/Amsterdam"
# IFC is next to this script: ./static/IFC/...
IFC_PATH = (Path(__file__).parent / "static" / "IFC" / "BK_v6_ifc4_georef_transformed.ifc").resolve()

ROOMS = [
    {
        "name": "BG.West.010",
        "co2_url":   "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(3)/Observations",
        "noise_url": "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(6)/Observations",
    },
    {
        "name": "BG.West.270",
        "co2_url":   "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(9)/Observations",
        "noise_url": "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(12)/Observations",
    },
    {
        "name": "01.West.120",
        "co2_url":   "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(15)/Observations",
        "noise_url": "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(18)/Observations",
    },
]

# Analysis window (LOCAL time)
START_LOCAL = pd.Timestamp("2025-04-01 00:00", tz=LOCAL_TZ)
END_LOCAL   = pd.Timestamp("2025-10-01 00:00", tz=LOCAL_TZ)
START_UTC   = START_LOCAL.tz_convert("UTC")
END_UTC     = END_LOCAL.tz_convert("UTC")

# ---------------- IFC → room geometry ----------------
room_objs: list[Room] = []
for cfg in ROOMS:
    site = parse_room(str(IFC_PATH), cfg["name"])  # Site with one Room in .rooms
    room = next(iter(site.rooms.values()))
    room_objs.append(room)

# name map (match either Name or LongName, case-insensitive)
name_to_geom = {}
for r in room_objs:
    if r.short_name:
        name_to_geom[r.short_name.strip().lower()] = r
    if r.long_name:
        name_to_geom[r.long_name.strip().lower()] = r

# ---------------- FROST helpers (OData/STA) ----------------
def _get_json(url, params=None, timeout=20):
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _page_all(url, params):
    """Follow @iot.nextLink to collect all pages (server does filtering/order)."""
    out = []
    data = _get_json(url, params=params)
    while True:
        out.extend(data.get("value", []))
        nxt = data.get("@iot.nextLink")
        if not nxt:
            break
        data = _get_json(nxt, params=None)
    return out

def fetch_sta_series(observations_url: str,
                     start_utc: pd.Timestamp, end_utc: pd.Timestamp,
                     local_tz: str, value_col: str) -> pd.Series:
    """
    Server-side: filter by [start,end), select only needed fields, order asc, page small.
    Client-side: convert to LOCAL tz and hourly-average.
    """
    f_start = start_utc.isoformat().replace("+00:00", "Z")
    f_end   = end_utc.isoformat().replace("+00:00", "Z")
    params = {
        # STA/OData server-side filtering + small payload
        "$filter": f"phenomenonTime ge {f_start} and phenomenonTime lt {f_end}",
        "$select": "phenomenonTime,result",
        "$orderby": "phenomenonTime asc",
        "$top": 1000
    }
    obs = _page_all(observations_url, params)

    if not obs:
        return pd.Series(dtype=float)

    df = pd.DataFrame(
        [{"t": o.get("phenomenonTime"), value_col: o.get("result")}
         for o in obs if "phenomenonTime" in o and "result" in o]
    )
    if df.empty:
        return pd.Series(dtype=float)

    df["t"] = pd.to_datetime(df["t"], utc=True, errors="coerce")
    df = df.dropna(subset=["t"]).set_index("t").sort_index()
    # LOCAL alignment + hourly mean
    df.index = df.index.tz_convert(local_tz)
    return df[value_col].astype(float).resample("1h").mean()

# ---------------- Feature engineering (minimal) ----------------
def nightly_baseline(series: pd.Series) -> pd.Series:
    """Nightly (00–05) rolling 10th percentile as CO₂ baseline; reindex to all hours."""
    if series.empty:
        return series
    night = series.between_time("00:00", "05:00")
    baseline = (night.rolling(24*7, min_periods=8).quantile(0.10)
                      .reindex(series.index, method="nearest"))
    return baseline

def build_features(df_room_hourly: pd.DataFrame, volume: float, area: float) -> pd.DataFrame:
    """
    Inputs df_room_hourly with columns: ['co2','noise'], hourly index in LOCAL tz.
    Output adds features + a simple supervised target 'occ_target' (index proxy).
    """
    out = df_room_hourly.copy()
    # Ensure required cols
    for c in ("co2", "noise"):
        if c not in out:
            out[c] = np.nan

    # Minimal signals for XGB
    C = out["co2"]
    Cout = nightly_baseline(C)
    out["excess"] = (C - Cout).clip(lower=0)         # how far above baseline
    out["dco2"]   = C.diff().fillna(0)               # hourly slope
    # Simple noise signal (keep raw avg; can add features later)
    out["noise"]  = out["noise"].astype(float)

    # Calendar + geometry
    idx = out.index
    out["hour"] = idx.hour
    out["dow"]  = idx.dayofweek
    out["is_weekend"] = (out["dow"] >= 5).astype(int)
    out["volume"] = float(volume)
    out["area"]   = float(area)

    # A simple training target = “occupancy index” (no ACH math)
    # You can keep it this simple; XGB handles nonlinearities.
    out["occ_target"] = out["excess"] + 0.5 * out["dco2"].clip(lower=0)

    return out

# ---------------- Build the training dataframe (room, ts, co2, noise) ----------------
rows = []
for cfg in ROOMS:
    key = cfg["name"].strip().lower()
    geom = name_to_geom.get(key)
    if geom is None:
        print(f"WARNING: geometry not found for room {cfg['name']}; skipping")
        continue

    co2 = fetch_sta_series(cfg["co2_url"], START_UTC, END_UTC, LOCAL_TZ, "co2") if cfg.get("co2_url") else pd.Series(dtype=float)
    noise = fetch_sta_series(cfg["noise_url"], START_UTC, END_UTC, LOCAL_TZ, "noise") if cfg.get("noise_url") else pd.Series(dtype=float)

    # Union of time axes; keep hourly
    idx = co2.index.union(noise.index) if not co2.empty or not noise.empty else pd.DatetimeIndex([], tz=LOCAL_TZ)
    if len(idx) == 0:
        print(f"WARNING: no time series for {cfg['name']}")
        continue

    df_hourly = pd.DataFrame(index=idx).sort_index()
    if not co2.empty:   df_hourly["co2"] = co2.reindex(idx)
    if not noise.empty: df_hourly["noise"] = noise.reindex(idx)

    # Build features + target
    feats = build_features(df_hourly, geom.volume, geom.area)
    feats.insert(0, "room", cfg["name"])
    rows.append(feats.reset_index(names="ts"))

df_all = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
print("Built dataframe shape:", df_all.shape)
if df_all.empty:
    raise RuntimeError("No CO₂/Noise data fetched for the selected window/rooms.")

# ---------------- Train XGB per room and produce indices ----------------
def train_room_model(df_room_long: pd.DataFrame):
    # Minimal, stable feature set
    FEATURES = ["co2", "noise", "excess", "dco2", "hour", "dow", "is_weekend", "volume", "area"]
    X = df_room_long[FEATURES].fillna(0.0)
    y = df_room_long["occ_target"].fillna(0.0)
    w = np.where(df_room_long["is_weekend"] == 1, 0.3, 1.0)  # downweight weekends (likely empty)

    model = XGBRegressor(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.9,
        objective="reg:absoluteerror", n_jobs=-1
    )
    model.fit(X, y, sample_weight=w)
    # Predicted occupancy index (unitless, ≥0)
    pred = pd.Series(model.predict(X), index=df_room_long.index, name="occ_index")
    return model, pred

models = {}
preds  = {}
for room_name, grp in df_all.groupby("room", sort=False):
    model, pred = train_room_model(grp)
    models[room_name] = model
    # Attach timestamps for convenience
    p = pd.Series(pred.values, index=grp["ts"].values, name="occ_index")
    preds[room_name] = p

# ---------------- Summarize robust weekday maxima (useful for calibration) ----------------
summ_rows = []
for room_name, grp in df_all.groupby("room", sort=False):
    # Build a Series indexed by timestamps (ensure proper DateTimeIndex)
    s = pd.Series(preds[room_name].values,
                  index=pd.to_datetime(grp["ts"].values)).sort_index()

    # Keep weekdays only
    wk_mask = (grp["is_weekend"].values == 0)
    s_wk = s[wk_mask]

    # Daily max using resample (much simpler than .dt.date groupby)
    daily_max = s_wk.resample("D").max()

    p95 = float(np.nanpercentile(daily_max, 95)) if len(daily_max) else np.nan
    p99 = float(np.nanpercentile(daily_max, 99)) if len(daily_max) else np.nan
    summ_rows.append({"room": room_name, "p95_daily_max": p95, "p99_daily_max": p99})

summary = pd.DataFrame(summ_rows).set_index("room")
print("\nRobust weekday max occupancy index (per room):")
print(summary)


# ---------------- Simple calibration: scale index → people with user k ----------------
def apply_k_to_predictions(pred_series_by_room: dict[str, pd.Series], k: float) -> dict[str, pd.Series]:
    """
    Multiply each room's occupancy index by a user-specified factor k to estimate people.
    Returns a dict of Series named 'people_est'.
    """
    out = {}
    for room, s in pred_series_by_room.items():
        out[room] = (s * float(k)).rename("people_est")
    return out

# Example:
k = 0.10  # user-set calibration (people per index unit)
people_preds = apply_k_to_predictions(preds, k)
print(people_preds["01.West.120"].head())

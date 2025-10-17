# export_window_normals_geojson.py
from pathlib import Path
import json, math
from typing import Tuple
from pyproj import CRS, Transformer

from ifc_parsers import parse_room, get_georef_info, rotate_xy_vec
import ifcopenshell  # just to open and pass model to get_georef_info

# ---------- CONFIG ----------
IFC_PATH     = Path("static/IFC/BK_v6_ifc4_georef_transformed.ifc")
ROOM_NAME    = "BG.West.010"
OUTPUT_PATH  = Path("window_normals.geojson")
ARROW_LEN_M  = 10.0 # length of normal arrows in meters
OUTPUT_CRS   = "EPSG:28992" # or "EPSG:4326" for lon/lat
# --------------------------------

def map_from_model_xy(x: float, y: float, yaw_deg: float, scale: float,
                      east0: float, north0: float) -> Tuple[float, float]:
    """Rotate model (x,y) by yaw (CCW), apply scale, add offset -> (E,N)."""
    xr, yr = rotate_xy_vec(x, y, yaw_deg)   # rotation project->map
    e = east0  + scale * xr
    n = north0 + scale * yr
    return e, n

def main():
    # Parse room/windows (this computes window tilt/azimuth already vs True North)
    site = parse_room(IFC_PATH, ROOM_NAME)

    # Open model once to fetch map conversion for coordinates
    model = ifcopenshell.open(str(IFC_PATH))
    georef = get_georef_info(model)
    yaw   = georef["yaw_deg"]          # rotation project -> map (CCW)
    east0, north0, h0 = georef["offset"]
    scale = 1.0                        # IfcMapConversion.Scale (you can read it if needed)

    # Set up CRS transforms if writing 4326
    # if OUTPUT_CRS.upper() == "EPSG:4326":
    #     crs_src = CRS.from_epsg(28992)   # map coords after MapConversion are in RD New for file
    #     crs_dst = CRS.from_epsg(4326)
    #     to_wgs  = Transformer.from_crs(crs_src, crs_dst, always_xy=True)
    #     emit_wgs84 = True
    # else:
    #     emit_wgs84 = False
    
    emit_wgs84 = False

    features = []
    for room in site.rooms.values():
        if not room.windows:
            continue
        for w in room.windows or []:
            if not w.bounding_box:
                continue

            # window center in MODEL space (meters)
            cx = (w.bounding_box.x_min + w.bounding_box.x_max) / 2.0
            cy = (w.bounding_box.y_min + w.bounding_box.y_max) / 2.0
            cz = (w.bounding_box.z_min + w.bounding_box.z_max) / 2.0

            # normal direction in True-North frame (already rotated inside parse_room)
            tilt = float(w.tilt or 0.0)
            az   = float(w.azimuth or 0.0)
            t = math.radians(tilt)
            a = math.radians(az)
            nx = math.sin(t) * math.sin(a)
            ny = math.sin(t) * math.cos(a)
            nz = math.cos(t)

            # Build end point in MODEL space
            ex_m = cx + nx * ARROW_LEN_M
            ey_m = cy + ny * ARROW_LEN_M
            ez_m = cz + nz * ARROW_LEN_M

            # Convert start/end MODEL -> MAP (RD) using IfcMapConversion
            sx_rd, sy_rd = map_from_model_xy(cx,  cy,  yaw, scale, east0, north0)
            ex_rd, ey_rd = map_from_model_xy(ex_m, ey_m, yaw, scale, east0, north0)
            sz_rd = h0 + cz
            ez_rd = h0 + ez_m

            # Optionally transform RD -> WGS84 for GeoJSON friendliness
            if emit_wgs84:
                sx, sy = to_wgs.transform(sx_rd, sy_rd)
                ex, ey = to_wgs.transform(ex_rd, ey_rd)
                sz, ez = sz_rd, ez_rd  # keep Z in meters; GeoJSON ignores Z CRS anyway
            else:
                sx, sy, sz = sx_rd, sy_rd, sz_rd
                ex, ey, ez = ex_rd, ey_rd, ez_rd

            features.append({
                "type": "Feature",
                "properties": {
                    "window_id": w.global_id,
                    "room": w.room_name,
                    "tilt_deg": tilt,
                    "azimuth_deg_trueN": az,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[sx, sy, sz], [ex, ey, ez]],
                },
            })

    fc = {"type": "FeatureCollection", "features": features}
    OUTPUT_PATH.write_text(json.dumps(fc, indent=2))
    print(f"✅ Exported {len(features)} window normals to {OUTPUT_PATH}")
    if emit_wgs84:
        print("Note: Output is EPSG:4326 (lon/lat).")
    else:
        print("Note: Output numeric coords are EPSG:28992. In QGIS, set layer CRS to 28992 on load.")

if __name__ == "__main__":
    main()
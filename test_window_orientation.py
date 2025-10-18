#test_window_orientation_room.py
from __future__ import annotations
from pathlib import Path
import math, json
from typing import Tuple, Optional
import numpy as np
import ifcopenshell
import ifcopenshell.geom
from ifcopenshell.util.element import get_psets

# -------------------- CONFIG --------------------
IFC_PATH         = Path("static/IFC/BK_v6_ifc4_georef_transformed.ifc")
ROOM_NAME        = "BG.West.010"          # short or long space name
OUTPUT_GEOJSON   = Path("window_normals_room.geojson")
NORMAL_LENGTH_M  = 2.0                    # arrow length
BBOX_TOLERANCE_M = 2.0                    # bbox inclusion tolerance
# ------------------------------------------------

# ============ small helpers ============
def axis2placement3d_to_matrix(ax) -> np.ndarray:
    p = ax.Location.Coordinates if getattr(ax, "Location", None) else (0.0, 0.0, 0.0)
    px, py, pz = map(float, p)
    if getattr(ax, "Axis", None) and getattr(ax.Axis, "DirectionRatios", None):
        zx, zy, zz = (ax.Axis.DirectionRatios + (0.0, 0.0))[:3]
    else:
        zx, zy, zz = 0.0, 0.0, 1.0
    if getattr(ax, "RefDirection", None) and getattr(ax.RefDirection, "DirectionRatios", None):
        xx, xy, xz = (ax.RefDirection.DirectionRatios + (0.0, 0.0))[:3]
    else:
        xx, xy, xz = 1.0, 0.0, 0.0
    Z = np.array([zx, zy, zz], float); Z /= (np.linalg.norm(Z) or 1.0)
    X = np.array([xx, xy, xz], float); X = X - Z * np.dot(X, Z); X /= (np.linalg.norm(X) or 1.0)
    Y = np.cross(Z, X)
    M = np.eye(4); M[0:3,0]=X; M[0:3,1]=Y; M[0:3,2]=Z; M[0:3,3]=[px,py,pz]
    return M

def placement_chain_matrix(lp) -> np.ndarray:
    M = np.eye(4); cur = lp
    while cur is not None:
        ax = getattr(cur, "RelativePlacement", None)
        if ax and ax.is_a("IfcAxis2Placement3D"):
            M = axis2placement3d_to_matrix(ax) @ M
        cur = getattr(cur, "PlacementRelTo", None)
    return M

def get_true_north_deg(model) -> float:
    for ctx in model.by_type("IfcGeometricRepresentationContext"):
        tn = getattr(ctx, "TrueNorth", None)
        if tn and hasattr(tn, "DirectionRatios"):
            x, y = (tn.DirectionRatios + (0, 0))[:2]
            return (math.degrees(math.atan2(float(x), float(y))) % 360.0)
    raise ValueError("TrueNorth missing in IfcGeometricRepresentationContext")

def compute_window_from_placement(win):
    lp = getattr(win, "ObjectPlacement", None)
    if not lp or not lp.is_a("IfcLocalPlacement"):
        return 0.0, 0.0, np.zeros(3), np.array([0.0,1.0,0.0])
    M = placement_chain_matrix(lp)
    Y = M[0:3,1].astype(float); Y /= (np.linalg.norm(Y) or 1.0)
    O = M[0:3,3].astype(float)
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, Y[2]))))
    az_proj = math.degrees(math.atan2(Y[0], Y[1])) % 360.0  # 0°=+Y
    return tilt, az_proj, O, Y

def get_mapconversion(model):
    mcs = model.by_type("IfcMapConversion")
    return mcs[0] if mcs else None

def model_xy_to_rd_new(mc, x: float, y: float) -> Tuple[float,float]:
    a = float(mc.XAxisAbscissa or 1.0); b = float(mc.XAxisOrdinate or 0.0)
    s = float(mc.Scale or 1.0); E0 = float(mc.Eastings or 0.0); N0 = float(mc.Northings or 0.0)
    E = E0 + s * (a * x - b * y); N = N0 + s * (b * x + a * y)
    return E, N

def compute_bbox(entity) -> Optional[Tuple[float,float,float,float,float,float]]:
    settings = ifcopenshell.geom.settings(); settings.set(settings.USE_WORLD_COORDS, True)
    try:
        shape = ifcopenshell.geom.create_shape(settings, entity)
        v = shape.geometry.verts
        xs, ys, zs = v[0::3], v[1::3], v[2::3]
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
    except Exception:
        return None

def inside_bbox(wb, sb, tol) -> bool:
    wx0, wx1, wy0, wy1, wz0, wz1 = wb
    sx0, sx1, sy0, sy1, sz0, sz1 = sb
    return (wx0 >= sx0 - tol and wy0 >= sy0 - tol and wz0 >= sz0 - tol and
            wx1 <= sx1 + tol and wy1 <= sy1 + tol and wz1 <= sz1 + tol)

def name_matches(space, name: str) -> bool:
    t = name.strip().lower()
    return t in ((space.Name or "").strip().lower(), (space.LongName or "").strip().lower())

# ============ main ============
def run():
    print(f"Opening IFC: {IFC_PATH}")
    m = ifcopenshell.open(str(IFC_PATH))
    tn = get_true_north_deg(m)
    print(f"True North: {tn:.2f}°")

    # target room
    space = next((s for s in m.by_type("IfcSpace") if name_matches(s, ROOM_NAME)), None)
    if not space:
        raise RuntimeError(f"Space '{ROOM_NAME}' not found.")
    sb = compute_bbox(space)
    if not sb:
        raise RuntimeError(f"Could not compute bbox for space '{ROOM_NAME}'.")

    mc = get_mapconversion(m)
    wins = m.by_type("IfcWindow")

    feats = []
    kept = 0
    for w in wins:
        # only external windows (same check as your project)
        is_ext = get_psets(w).get("Pset_WindowCommon", {}).get("IsExternal", False)
        if not is_ext:
            continue

        wb = compute_bbox(w)
        if not wb or not inside_bbox(wb, sb, BBOX_TOLERANCE_M):
            continue

        tilt, az_proj, O, Y = compute_window_from_placement(w)
        az_geo = (az_proj - tn) % 360.0  # correct only by True North

        start = O
        end   = O + Y * NORMAL_LENGTH_M

        if mc:
            x0, y0 = model_xy_to_rd_new(mc, float(start[0]), float(start[1]))
            x1, y1 = model_xy_to_rd_new(mc, float(end[0]),   float(end[1]))
            z0, z1 = float(start[2]), float(end[2])
            coords = [[x0, y0, z0], [x1, y1, z1]]
            crs_name = "EPSG:28992"
        else:
            coords = [[float(start[0]), float(start[1]), float(start[2])],
                      [float(end[0]),   float(end[1]),   float(end[2])]]
            crs_name = "MODEL-UNITS"

        feats.append({
            "type": "Feature",
            "properties": {
                "window_id": w.GlobalId,
                "room": ROOM_NAME,
                "tilt_deg": tilt,
                "azimuth_deg_trueN": az_geo
            },
            "geometry": {"type":"LineString","coordinates": coords}
        })
        kept += 1

    fc = {"type":"FeatureCollection",
          "name":"window_normals_room",
          "crs":{"type":"name","properties":{"name":crs_name}},
          "features": feats}
    OUTPUT_GEOJSON.write_text(json.dumps(fc, indent=2))
    print(f"✅ Kept {kept} external windows for room '{ROOM_NAME}'.")
    print(f"➡  Wrote {OUTPUT_GEOJSON} (CRS {crs_name}). Open in QGIS with project CRS = EPSG:28992.")

if __name__ == "__main__":
    run()




# FOLLOWING SCROIPT IS TO WRITE ALL NORMALS (FROM ALL WINDOWS) INTO A GEOJSON
# from __future__ import annotations
# from pathlib import Path
# import math
# import json
# from typing import Iterable, Tuple, List, Optional

# import numpy as np
# import ifcopenshell
# from ifcopenshell.util.element import get_psets

# # -------------------------------
# # CONFIG (edit these as needed)
# # -------------------------------
# IFC_PATH     = Path("static/IFC/BK_v6_ifc4_georef_transformed.ifc")
# ROOM_FILTER  = "BG.West.010"      # set to None to include all windows
# OUTPUT_GEOJSON = Path("debug_window_normals.geojson")
# NORMAL_LENGTH_M = 20.0             # metres
# OUTPUT_CRS = "EPSG:28992"         # for QGIS; exporter applies MapConversion → RD New
# # -------------------------------


# # ---------- helpers: placements & orientation ----------
# def axis2placement3d_to_matrix(ax) -> np.ndarray:
#     p = ax.Location.Coordinates if getattr(ax, "Location", None) else (0.0, 0.0, 0.0)
#     px, py, pz = map(float, p)

#     # Z axis
#     if getattr(ax, "Axis", None) and getattr(ax.Axis, "DirectionRatios", None):
#         zx, zy, zz = (ax.Axis.DirectionRatios + (0.0, 0.0))[:3]
#     else:
#         zx, zy, zz = 0.0, 0.0, 1.0
#     # X axis
#     if getattr(ax, "RefDirection", None) and getattr(ax.RefDirection, "DirectionRatios", None):
#         xx, xy, xz = (ax.RefDirection.DirectionRatios + (0.0, 0.0))[:3]
#     else:
#         xx, xy, xz = 1.0, 0.0, 0.0

#     Z = np.array([zx, zy, zz], float)
#     Z /= (np.linalg.norm(Z) or 1.0)
#     X = np.array([xx, xy, xz], float)
#     X = X - Z * np.dot(X, Z)
#     X /= (np.linalg.norm(X) or 1.0)
#     Y = np.cross(Z, X)

#     M = np.eye(4)
#     M[0:3, 0] = X
#     M[0:3, 1] = Y
#     M[0:3, 2] = Z
#     M[0:3, 3] = [px, py, pz]
#     return M


# def placement_chain_matrix(lp) -> np.ndarray:
#     M = np.eye(4)
#     cur = lp
#     while cur is not None:
#         ax = getattr(cur, "RelativePlacement", None)
#         if ax and ax.is_a("IfcAxis2Placement3D"):
#             M = axis2placement3d_to_matrix(ax) @ M
#         cur = getattr(cur, "PlacementRelTo", None)
#     return M


# def get_true_north_deg(model) -> float:
#     ctxs = model.by_type("IfcGeometricRepresentationContext")
#     for ctx in ctxs:
#         tn = getattr(ctx, "TrueNorth", None)
#         if tn and hasattr(tn, "DirectionRatios"):
#             x, y = (tn.DirectionRatios + (0, 0))[:2]
#             return (math.degrees(math.atan2(float(x), float(y))) % 360.0)
#     raise ValueError("TrueNorth not defined in IfcGeometricRepresentationContext.")


# def compute_window_tilt_az_from_placement(win) -> Tuple[float, float, np.ndarray, np.ndarray]:
#     """Returns (tilt_deg, az_deg_project, origin_xyz, dir_unit_xyz).
#     az_deg_project is azimuth vs project axes (0°=+Y). We'll correct by TrueNorth outside.
#     """
#     lp = getattr(win, "ObjectPlacement", None)
#     if not lp or not lp.is_a("IfcLocalPlacement"):
#         # fallback: straight up
#         return 0.0, 0.0, np.zeros(3), np.array([0.0, 1.0, 0.0])

#     M = placement_chain_matrix(lp)
#     # axes
#     X = M[0:3, 0].astype(float)
#     Y = M[0:3, 1].astype(float)  # facing
#     O = M[0:3, 3].astype(float)  # origin

#     Y /= (np.linalg.norm(Y) or 1.0)
#     tilt = math.degrees(math.acos(max(-1.0, min(1.0, Y[2]))))  # 0=up, 90=vertical
#     az_proj = math.degrees(math.atan2(Y[0], Y[1])) % 360.0     # 0°=+Y, 90°=+X
#     return tilt, az_proj, O, Y


# # ---------- MapConversion (debug export only) ----------
# def get_mapconversion(model):
#     mcs = model.by_type("IfcMapConversion")
#     return mcs[0] if mcs else None


# def model_xy_to_rd_new(mc, x: float, y: float) -> Tuple[float, float]:
#     """Apply IfcMapConversion (rotation+scale+offset) to model XY → RD New (28992)."""
#     a = float(mc.XAxisAbscissa or 1.0)
#     b = float(mc.XAxisOrdinate or 0.0)
#     s = float(mc.Scale or 1.0)
#     E0 = float(mc.Eastings or 0.0)
#     N0 = float(mc.Northings or 0.0)
#     E = E0 + s * (a * x - b * y)
#     N = N0 + s * (b * x + a * y)
#     return E, N


# # ---------- room filter ----------
# def space_name_matches(space, target: str) -> bool:
#     t = target.strip().lower()
#     longn = (space.LongName or "").strip().lower()
#     shortn = (space.Name or "").strip().lower()
#     return (t == longn) or (t == shortn)


# def window_belongs_to_room(win, target_space) -> bool:
#     # Fast pragmatic approach: compare placements’ Z (storeys) or bounding boxes would be heavy.
#     # Here we take a simple heuristic: windows whose placement chain includes the target_space placement.
#     # If your model has strict containment relations, you could traverse spatial structure instead.
#     w_lp = getattr(win, "ObjectPlacement", None)
#     s_lp = getattr(target_space, "ObjectPlacement", None)
#     return bool(w_lp) and bool(s_lp)  # keep all; room matching is tricky in generic IFCs


# # ---------- main test routine ----------
# def run():
#     print(f"Opening IFC: {IFC_PATH}")
#     model = ifcopenshell.open(str(IFC_PATH))
#     if not model:
#         raise RuntimeError("Could not open IFC file.")

#     true_north_deg = get_true_north_deg(model)
#     print(f"TrueNorth: {true_north_deg:.2f}°")

#     # Optional room filter
#     target_space = None
#     if ROOM_FILTER:
#         for sp in model.by_type("IfcSpace"):
#             if space_name_matches(sp, ROOM_FILTER):
#                 target_space = sp
#                 break
#         if target_space:
#             print(f"Room filter matched: {ROOM_FILTER}")
#         else:
#             print(f"Room filter '{ROOM_FILTER}' not found. Proceeding with all windows.")

#     windows = model.by_type("IfcWindow")
#     print(f"Total windows in model: {len(windows)}")

#     features = []
#     printed = 0
#     for w in windows:
#         if target_space and not window_belongs_to_room(w, target_space):
#             # if you want a stricter filter, replace with a spatial-containment traversal
#             pass  # keep windows; room membership is model-dependent

#         tilt, az_proj, O, Y = compute_window_tilt_az_from_placement(w)
#         az_geo = (az_proj - true_north_deg) % 360.0  # correction ONLY by True North

#         # print a few for sanity
#         if printed < 6:
#             print(f"- {w.GlobalId[:8]}  tilt={tilt:6.2f}°  azimuth_geo={az_geo:6.2f}°  (proj={az_proj:6.2f}°)")
#             printed += 1

#         # make a short line (model coords)
#         start = O
#         end = O + Y * NORMAL_LENGTH_M

#         # to GeoJSON coordinates (28992 by default) using MapConversion
#         mc = get_mapconversion(model)
#         if mc:
#             x0, y0 = model_xy_to_rd_new(mc, float(start[0]), float(start[1]))
#             x1, y1 = model_xy_to_rd_new(mc, float(end[0]),   float(end[1]))
#             z0 = float(start[2]); z1 = float(end[2])  # keep Z for 3D LineString; QGIS will ignore or can use 3D
#             coords = [[x0, y0, z0], [x1, y1, z1]]
#             crs_name = "EPSG:28992" if OUTPUT_CRS.upper() == "EPSG:28992" else OUTPUT_CRS
#         else:
#             # No MapConversion (e.g., IFC2x3). Emit model coords as a fallback.
#             x0, y0, z0 = float(start[0]), float(start[1]), float(start[2])
#             x1, y1, z1 = float(end[0]),   float(end[1]),   float(end[2])
#             coords = [[x0, y0, z0], [x1, y1, z1]]
#             crs_name = "MODEL-UNITS"

#         features.append({
#             "type": "Feature",
#             "properties": {
#                 "window_id": w.GlobalId,
#                 "tilt_deg": tilt,
#                 "azimuth_geo_deg": az_geo,
#                 "azimuth_project_deg": az_proj,
#             },
#             "geometry": {"type": "LineString", "coordinates": coords}
#         })

#     fc = {
#         "type": "FeatureCollection",
#         "name": "window_normals",
#         "crs": {"type": "name", "properties": {"name": crs_name}},
#         "features": features
#     }
#     OUTPUT_GEOJSON.write_text(json.dumps(fc, indent=2))
#     print(f"\n✅ Wrote {len(features)} normals → {OUTPUT_GEOJSON}")
#     print("Open in QGIS with project CRS = EPSG:28992. Style as thick arrows to inspect.")


# if __name__ == "__main__":
#     run()
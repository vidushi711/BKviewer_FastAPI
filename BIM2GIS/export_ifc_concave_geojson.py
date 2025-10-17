# builds a concave hull (alpha-shape) footprint from IFC, with two quality boosts:
	# 1.	it prefers ground slabs (BASESLAB) to avoid roof points;
	# 2.	if no explicit base slab is found, it falls back to lowest-Z geometry (walls/slabs/roofs) and then makes a concave hull.


# make_ifc_envelope.py
from pathlib import Path
import math
import json
from typing import Iterable, List, Tuple, Optional

import numpy as np
import ifcopenshell
import ifcopenshell.geom
from shapely.geometry import Polygon, MultiPoint, LineString, mapping
from shapely.ops import unary_union
from pyproj import CRS, Transformer

# --- optional: use alphashape if available (faster/nicer concave hull) ---
try:
    import alphashape  # pip/uv: alphashape
    HAS_ALPHASHAPE = True
except Exception:
    HAS_ALPHASHAPE = False

# ---------- helpers ----------
def dms_to_decimal(dms) -> float:
    """IFC stores site ref lat/lon as DMS tuples."""
    if not dms or len(dms) < 3:
        return 0.0
    return float(dms[0]) + float(dms[1]) / 60.0 + float(dms[2]) / 3600.0

def project_north_yaw_degrees(model) -> float:
    """
    Return yaw (deg) from IFC +Y to True North (0°=North, 90°=East).
    Positive yaw means rotate model CCW by yaw to align +Y to True North.
    """
    ctxs = model.by_type("IfcGeometricRepresentationContext")
    for ctx in ctxs:
        tn = getattr(ctx, "TrueNorth", None)
        if tn and hasattr(tn, "DirectionRatios"):
            x, y = (tn.DirectionRatios + (0, 0))[:2]
            az = math.degrees(math.atan2(x, y)) % 360.0
            return az
    # Your earlier diagnostics showed ~90° deviation; use that if TrueNorth missing.
    return 90.0

def rotate_xy(points: Iterable[Tuple[float, float]], yaw_deg: float) -> List[Tuple[float, float]]:
    """Rotate XY around origin by +yaw_deg (CCW)."""
    th = math.radians(yaw_deg)
    c, s = math.cos(th), math.sin(th)
    return [(c * x - s * y, s * x + c * y) for (x, y) in points]

def collect_xy_from_shape(shape) -> List[Tuple[float, float, float]]:
    """Extract (x,y,z) triplets from an IfcOpenShell mesh shape."""
    vs = shape.geometry.verts  # flat list [x0,y0,z0,x1,y1,z1,...]
    xs = vs[0::3]; ys = vs[1::3]; zs = vs[2::3]
    return list(zip(xs, ys, zs))

def get_shapes(model, ifc_types: List[str]) -> List:
    """Collect IfcOpenShell geom shapes for the given IFC types."""
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    shapes = []
    for t in ifc_types:
        for e in model.by_type(t):
            try:
                shapes.append(ifcopenshell.geom.create_shape(settings, e))
            except Exception:
                pass
    return shapes

def concave_hull(points_xy: List[Tuple[float, float]], alpha: float) -> Polygon:
    """
    Build a concave hull polygon from XY points.
    - If alphashape is available, use it.
    - Otherwise, crude fallback: buffer small → union → buffer back (acts like concavity).
    """
    if len(points_xy) < 4:
        return MultiPoint(points_xy).convex_hull

    if HAS_ALPHASHAPE:
        poly = alphashape.alphashape(points_xy, alpha)
        # alphashape can return MultiPolygon; unify
        if poly.is_empty:
            return MultiPoint(points_xy).convex_hull
        return poly.buffer(0)  # clean topology
    else:
        # Fallback: morphological trick
        mp = MultiPoint(points_xy)
        # Heuristic buffer value proportional to point spacing
        # alpha here ~ metres; tweak to taste
        shrink = max(0.2, alpha)
        poly = mp.buffer(shrink).buffer(-shrink)
        if poly.is_empty:
            return mp.convex_hull
        # If multi, union to single outline
        return unary_union([poly]).buffer(0)

def choose_ground_points(model) -> List[Tuple[float, float]]:
    """
    Prefer ground/base slabs; otherwise use lowest-Z vertices from exterior-ish classes.
    Returns XY points in model coordinates (metres).
    """
    # 1) Try explicit ground slabs
    base_shapes = []
    for slab in model.by_type("IfcSlab") or []:
        if getattr(slab, "PredefinedType", None) == "BASESLAB":
            try:
                settings = ifcopenshell.geom.settings()
                settings.set(settings.USE_WORLD_COORDS, True)
                base_shapes.append(ifcopenshell.geom.create_shape(settings, slab))
            except Exception:
                pass

    if base_shapes:
        pts = []
        for sh in base_shapes:
            for x, y, z in collect_xy_from_shape(sh):
                pts.append((x, y))
        if pts:
            return pts

    # 2) Fallback: gather common exterior-ish elements and select those near the global min-Z
    exterior_types = ["IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcRoof", "IfcCurtainWall"]
    shapes = get_shapes(model, exterior_types)
    all_xyz = []
    for sh in shapes:
        all_xyz.extend(collect_xy_from_shape(sh))
    if not all_xyz:
        return []

    # find near-ground band (e.g., within 1.0 m of min z)
    zs = [z for (_, _, z) in all_xyz]
    zmin = min(zs)
    band = zmin + 1.0  # metres above min
    ground_xy = [(x, y) for (x, y, z) in all_xyz if z <= band]
    return ground_xy

def export_envelope_geojson(ifc_path: Path, out_geojson: Path, alpha: float = 2.0):
    """
    alpha: concavity control (metres). Smaller → tighter/more detailed.
           If using 'alphashape', alpha is unitless but behaves similarly:
           smaller → more detail, larger → smoother.
    """
    model = ifcopenshell.open(str(ifc_path))
    if not model:
        raise RuntimeError(f"Could not open {ifc_path}")

    # Site lat/lon (WGS84) for local projection
    site = (model.by_type("IfcSite") or [None])[0]
    lat = dms_to_decimal(getattr(site, "RefLatitude", (0, 0, 0))) if site else 0.0
    lon = dms_to_decimal(getattr(site, "RefLongitude", (0, 0, 0))) if site else 0.0

    # Model yaw (project +Y → True North)
    yaw_deg = project_north_yaw_degrees(model)

    # Collect ground-level points and rotate them to align with True North
    xy = choose_ground_points(model)
    if not xy:
        raise RuntimeError("No geometry vertices found to build a footprint.")
    xy_rot = rotate_xy(xy, yaw_deg)

    # Build concave hull
    hull = concave_hull(xy_rot, alpha=alpha)
    if hull.is_empty:
        raise RuntimeError("Footprint hull is empty.")
    # If multipolygon (rare), take the largest area part
    if hull.geom_type == "MultiPolygon":
        hull = max(list(hull.geoms), key=lambda p: p.area)

    # Local equal-area/azimuthal projection centered at site → then to WGS84
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs")
    wgs84 = CRS.from_epsg(4326)
    to_wgs84 = Transformer.from_crs(aeqd, wgs84, always_xy=True)

    lonlat_coords = [to_wgs84.transform(x, y) for (x, y) in hull.exterior.coords]

    feature = {
        "type": "Feature",
        "properties": {
            "name": ifc_path.name,
            "source_ifc": str(ifc_path),
            "yaw_deg_projectY_to_trueN": yaw_deg,
            "alpha_param": alpha,
            "method": "concave hull (alpha-shape)" if HAS_ALPHASHAPE else "concave (morphological fallback)",
            "note": "Footprint uses ground slabs if present; else lowest-Z band of exterior geometry.",
        },
        "geometry": {"type": "Polygon", "coordinates": [lonlat_coords]},
    }

    fc = {"type": "FeatureCollection", "features": [feature]}
    out_geojson.write_text(json.dumps(fc, indent=2))
    print(f"✅ Wrote {out_geojson}  |  points={len(xy_rot)}  yaw={yaw_deg:.2f}°  alpha={alpha}")

if __name__ == "__main__":
    ifc = Path("BK_v2_vb_updated.ifc")
    out = Path("bk_envelope_v2.geojson")
    export_envelope_geojson(ifc, out, alpha=2.0)
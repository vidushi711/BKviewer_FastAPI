from pathlib import Path
import math
import json
from typing import List, Tuple

import ifcopenshell
import ifcopenshell.geom
from shapely.geometry import Polygon, MultiPoint, mapping
from shapely.ops import unary_union
from pyproj import CRS, Transformer

# ---------- helpers ----------
def dms_to_decimal(dms):
    if not dms or len(dms) < 3:
        return 0.0
    return float(dms[0]) + float(dms[1])/60.0 + float(dms[2])/3600.0

def project_north_yaw_degrees(model) -> float:
    """Return yaw (deg) from IFC +Y to True North (0°=North, 90°=East)."""
    # Try IfcGeometricRepresentationContext.TrueNorth
    ctxs = model.by_type("IfcGeometricRepresentationContext")
    for ctx in ctxs:
        tn = getattr(ctx, "TrueNorth", None)
        if tn and hasattr(tn, "DirectionRatios"):
            x, y = (tn.DirectionRatios + (0, 0))[:2]
            # Convert vector to azimuth degrees (0=N, 90=E)
            az = math.degrees(math.atan2(x, y)) % 360.0
            # The yaw from +Y (project north) to true north is:
            # +Y is azimuth 0; true north has azimuth 'az'.
            # Positive yaw means you must rotate model CCW by yaw to align +Y to true north.
            return az
    # Fallback: assume +Y ≙ East (90° off) if not specified (your earlier check showed ~90°)
    return 90.0

def rotate_xy(points: List[Tuple[float, float]], yaw_deg: float) -> List[Tuple[float, float]]:
    """Rotate XY around origin by +yaw_deg (CCW)."""
    th = math.radians(yaw_deg)
    c, s = math.cos(th), math.sin(th)
    return [(c*x - s*y, s*x + c*y) for (x, y) in points]

def world_mesh_vertices(model) -> List[Tuple[float, float]]:
    """Collect XY vertices from exterior-ish elements to approximate footprint."""
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    xy: List[Tuple[float, float]] = []
    # Exterior-ish classes; add/remove if needed
    classes = ["IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcRoof", "IfcCurtainWall"]
    for cls in classes:
        for e in model.by_type(cls):
            try:
                shp = ifcopenshell.geom.create_shape(settings, e)
                vs = shp.geometry.verts  # flat list [x0,y0,z0, x1,y1,z1, ...]
                # sample all vertices (XY only)
                xy.extend(list(zip(vs[0::3], vs[1::3])))
            except Exception:
                continue
    return xy

# ---------- main ----------
def export_envelope_geojson(ifc_path: Path, out_geojson: Path):
    model = ifcopenshell.open(str(ifc_path))
    if not model:
        raise RuntimeError(f"Could not open {ifc_path}")

    # Site lat/lon (WGS84)
    site = (model.by_type("IfcSite") or [None])[0]
    lat = dms_to_decimal(getattr(site, "RefLatitude", (0, 0, 0))) if site else 0.0
    lon = dms_to_decimal(getattr(site, "RefLongitude", (0, 0, 0))) if site else 0.0

    # Yaw from project +Y to True North
    yaw_deg = project_north_yaw_degrees(model)

    # Collect XY in model space, rotate to align to True North
    xy = world_mesh_vertices(model)
    if not xy:
        raise RuntimeError("No geometry vertices collected (walls/roofs).")

    xy_rot = rotate_xy(xy, yaw_deg)

    # Build an approximate footprint: convex hull of all rotated points
    hull = MultiPoint(xy_rot).convex_hull
    if hull.is_empty or not isinstance(hull, (Polygon,)):
        raise RuntimeError("Failed to compute footprint hull.")

    # Create a local AEQD projection centered on site lat/lon
    # We’ll treat rotated XY as Easting/Northing in metres in that local CRS
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs")
    wgs84 = CRS.from_epsg(4326)
    to_wgs84 = Transformer.from_crs(aeqd, wgs84, always_xy=True)

    # Transform hull coords (model metres) -> lon/lat
    lonlat_coords = [to_wgs84.transform(x, y) for (x, y) in hull.exterior.coords]

    feature = {
        "type": "Feature",
        "properties": {
            "name": ifc_path.name,
            "source_ifc": str(ifc_path),
            "yaw_deg_projectY_to_trueN": yaw_deg,
            "note": "Approximate footprint georeferenced via AEQD at IfcSite latitude/longitude.",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [lonlat_coords],
        },
    }

    fc = {"type": "FeatureCollection", "features": [feature]}
    out_geojson.write_text(json.dumps(fc, indent=2))
    print(f"✅ Wrote {out_geojson}")

if __name__ == "__main__":
    # Adjust paths if needed
    ifc = Path("BK_v2_vb_updated.ifc")
    out = Path("bk_envelope.geojson")
    out.parent.mkdir(parents=True, exist_ok=True)
    export_envelope_geojson(ifc, out)
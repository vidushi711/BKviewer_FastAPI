# there are no 2D “FootPrint” curves to extract. 
# The most reliable fallback (and still simple) is to build a footprint from the slabs that belong to a specific storey (e.g., “BG”) using mesh geometry, keep only horizontal faces, union them, and export. 
# Below is a complete script that does exactly that and enforces True North (no silent 90° assumptions).

from pathlib import Path
import sys, math, json
from typing import Iterable, Tuple, List, Optional

import ifcopenshell
import ifcopenshell.geom
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.ops import unary_union
from pyproj import CRS, Transformer


# ---------- helpers ----------
def dms_to_decimal(dms) -> float:
    """IFC stores lat/lon as DMS tuples; convert to decimal degrees."""
    if not dms or len(dms) < 3:
        return 0.0
    return float(dms[0]) + float(dms[1]) / 60.0 + float(dms[2]) / 3600.0


def require_true_north(model) -> float:
    """
    Return yaw (deg) from IFC +Y to True North (0°=North, 90°=East).
    Raise if not defined (we do not make assumptions).
    """
    for ctx in model.by_type("IfcGeometricRepresentationContext"):
        tn = getattr(ctx, "TrueNorth", None)
        if tn and hasattr(tn, "DirectionRatios"):
            x, y = (tn.DirectionRatios + (0, 0))[:2]
            return math.degrees(math.atan2(x, y)) % 360.0
    raise ValueError(
        "No TrueNorth found in IfcGeometricRepresentationContext. "
        "Please define orientation in the authoring tool."
    )


def rotate_xy(points: Iterable[Tuple[float, float]], yaw_deg: float):
    """Rotate XY around origin by +yaw_deg (CCW)."""
    th = math.radians(yaw_deg)
    c, s = math.cos(th), math.sin(th)
    for x, y in points:
        yield (c * x - s * y, s * x + c * y)


def triangles_xy(shape, nz_thresh=0.95, min_tri_area=0.02):
    """
    Yield triangle XY tuples from an ifcopenshell shape (world coords),
    keeping only near-horizontal triangles (|nz| >= nz_thresh) and
    dropping tiny slivers (< min_tri_area m²).
    """
    vs = shape.geometry.verts
    fs = shape.geometry.faces
    i = 0
    while i < len(fs):
        n = fs[i]
        i += 1
        if n != 3:
            i += n
            continue
        i0, i1, i2 = fs[i:i+3]
        i += 3
        x0, y0, z0 = vs[3*i0], vs[3*i0+1], vs[3*i0+2]
        x1, y1, z1 = vs[3*i1], vs[3*i1+1], vs[3*i1+2]
        x2, y2, z2 = vs[3*i2], vs[3*i2+1], vs[3*i2+2]

        # normal (unnormalized)
        ux, uy, uz = (x1 - x0, y1 - y0, z1 - z0)
        vx, vy, vz = (x2 - x0, y2 - y0, z2 - z0)
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        norm = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
        nz_norm = nz / norm

        if abs(nz_norm) < nz_thresh:
            continue

        tri = Polygon([(x0, y0), (x1, y1), (x2, y2)])
        if tri.area < min_tri_area:
            continue
        yield ( (x0, y0), (x1, y1), (x2, y2) )


def get_storey_candidates(model):
    """Return list of (storey, elevation_value) for all IfcBuildingStorey with numeric Elevation."""
    out = []
    for st in model.by_type("IfcBuildingStorey"):
        elev = getattr(st, "Elevation", None)
        try:
            if elev is not None:
                out.append((st, float(elev)))
        except Exception:
            continue
    return out


def pick_storey(model, name_hint: Optional[str] = None):
    """
    - If name_hint is given, pick the storey whose Name or LongName matches (case-insensitive substring).
    - Else, pick the lowest storey with Elevation >= 0 (lowest above grade).
      If none >= 0, pick the absolute lowest.
    """
    storeys = get_storey_candidates(model)
    if not storeys:
        raise RuntimeError("No IfcBuildingStorey with a numeric Elevation found.")

    if name_hint:
        nh = name_hint.strip().lower()
        for st, elev in storeys:
            nm = (st.Name or "").lower()
            ln = (getattr(st, "LongName", "") or "").lower()
            if nh in nm or nh in ln:
                return st, elev

    above = [(st, ev) for st, ev in storeys if ev >= 0.0]
    if above:
        st, ev = sorted(above, key=lambda t: t[1])[0]
        return st, ev

    # fallback: absolute lowest
    st, ev = sorted(storeys, key=lambda t: t[1])[0]
    return st, ev


def slabs_contained_in_storey(model, storey):
    """Return list of IfcSlab that are contained in the given storey via spatial structure."""
    slab_ids = set()
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        if rel.RelatingStructure == storey:
            for el in (rel.RelatedElements or []):
                if el.is_a("IfcSlab"):
                    slab_ids.add(el.id())
    # turn ids back into entities to avoid duplicates
    return [model[id_] for id_ in slab_ids]


def collect_storey_slab_footprint(model, storey, z_band=0.8) -> MultiPolygon:
    """
    Mesh slabs contained in the chosen storey, keep horizontal triangles,
    union, clean, keep largest polygon, drop tiny holes.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    slabs = slabs_contained_in_storey(model, storey)
    if not slabs:
        raise RuntimeError(f"No IfcSlab contained in storey '{storey.Name or storey.LongName or storey.GlobalId}'.")

    # Optional: restrict to triangles near the storey's elevation (tighten if needed)
    try:
        target_z = float(getattr(storey, "Elevation", 0.0))
    except Exception:
        target_z = 0.0

    tris = []
    for s in slabs:
        try:
            shp = ifcopenshell.geom.create_shape(settings, s)
        except Exception:
            continue
        for tri in triangles_xy(shp, nz_thresh=0.96, min_tri_area=0.03):
            # quick z-band check: keep triangles whose average z is near the storey elevation
            # (helps avoid picking mezzanines/ramps if present)
            # Reconstruct z from the shape again (cheaper: skip z-band if too strict)
            # For simplicity, accept as-is; uncomment if needed:
            # x0,y0 = tri[0]; x1,y1 = tri[1]; x2,y2 = tri[2]
            # (we’d need z too; skipping banding here keeps it robust)
            tris.append(Polygon(tri))

    if not tris:
        raise RuntimeError("No horizontal slab triangles found for the chosen storey.")

    merged = unary_union(tris)
    # clean small spikes: close-open buffer
    merged = merged.buffer(0.20).buffer(-0.20)
    merged = merged.buffer(0)

    if merged.is_empty:
        raise RuntimeError("Footprint union is empty after cleanup.")

    polys = [merged] if isinstance(merged, Polygon) else list(merged.geoms)
    # keep reasonable areas only, then the largest
    polys = [p for p in polys if p.area >= 10.0]
    if not polys:
        raise RuntimeError("All polygons filtered out by area threshold.")
    largest = max(polys, key=lambda p: p.area)

    # remove tiny holes
    if largest.interiors:
        largest = Polygon(
            largest.exterior.coords,
            [r for r in largest.interiors if Polygon(r).area >= 8.0],
        )

    return MultiPolygon([largest])


def export_storey_footprint_geojson(ifc_path: Path, out_geojson: Path, storey_name_hint: Optional[str] = None):
    model = ifcopenshell.open(str(ifc_path))
    if not model:
        raise RuntimeError(f"Could not open {ifc_path}")

    # Site lat/lon for local proj
    site = (model.by_type("IfcSite") or [None])[0]
    lat = dms_to_decimal(getattr(site, "RefLatitude", (0, 0, 0))) if site else 0.0
    lon = dms_to_decimal(getattr(site, "RefLongitude", (0, 0, 0))) if site else 0.0

    # Enforce True North (no silent assumptions)
    yaw = require_true_north(model)

    # Pick storey
    storey, elev = pick_storey(model, name_hint=storey_name_hint)
    print(f"Using storey: '{storey.Name or storey.LongName or storey.GlobalId}' (Elevation={elev:.3f})")

    footprint = collect_storey_slab_footprint(model, storey)

    # local AEQD -> WGS84
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs")
    wgs84 = CRS.from_epsg(4326)
    to_wgs84 = Transformer.from_crs(aeqd, wgs84, always_xy=True)

    feats = []
    geoms = footprint.geoms if isinstance(footprint, MultiPolygon) else [footprint]
    for poly in geoms:
        ext_rot = list(rotate_xy(list(poly.exterior.coords), yaw))
        ext_ll = [to_wgs84.transform(x, y) for (x, y) in ext_rot]
        holes_ll = []
        for h in poly.interiors:
            h_rot = list(rotate_xy(list(h.coords), yaw))
            holes_ll.append([to_wgs84.transform(x, y) for (x, y) in h_rot])

        feats.append({
            "type": "Feature",
            "properties": {
                "storey": storey.Name or storey.LongName or storey.GlobalId,
                "storey_elevation": elev,
                "yaw_deg_projectY_to_trueN": yaw,
                "source_ifc": str(ifc_path),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [ext_ll] + holes_ll
            }
        })

    fc = {"type": "FeatureCollection", "features": feats}
    out_geojson.write_text(json.dumps(fc, indent=2))
    print(f"✅ Wrote {out_geojson} | polygons={len(feats)}")


# ---------- CLI ----------
if __name__ == "__main__":
    # Usage:
    #   python3 export_storey_slab_footprint.py BK_v2_vb_updated.ifc bk_footprint_BG.geojson BG
    #
    args = sys.argv[1:]
    ifc = Path(args[0]) if len(args) >= 1 else Path("BK_v2_vb_updated.ifc")
    out = Path(args[1]) if len(args) >= 2 else Path("bk_footprint.geojson")
    storey_hint = args[2] if len(args) >= 3 else None

    out.parent.mkdir(parents=True, exist_ok=True)
    export_storey_footprint_geojson(ifc, out, storey_hint)
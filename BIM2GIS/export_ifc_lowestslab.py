# footprint_from_floor.py
from pathlib import Path
import math
import json
from typing import Iterable, Tuple, List

import ifcopenshell
import ifcopenshell.geom
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from pyproj import CRS, Transformer


# ---------- helpers ----------
def dms_to_decimal(dms) -> float:
    """IFC stores lat/lon as DMS tuples; convert to decimal degrees."""
    if not dms or len(dms) < 3:
        return 0.0
    return float(dms[0]) + float(dms[1]) / 60.0 + float(dms[2]) / 3600.0


def project_north_yaw_degrees(model) -> float:
    """
    Return yaw (deg) from IFC +Y to True North (0°=North, 90°=East).
    Raises if TrueNorth is not defined (no silent assumptions).
    """
    for ctx in model.by_type("IfcGeometricRepresentationContext"):
        tn = getattr(ctx, "TrueNorth", None)
        if tn and hasattr(tn, "DirectionRatios"):
            x, y = (tn.DirectionRatios + (0, 0))[:2]
            # azimuth of the TrueNorth vector (0=N, 90=E)
            return math.degrees(math.atan2(x, y)) % 360.0
    raise ValueError(
        "IFC file does not contain a defined TrueNorth in IfcGeometricRepresentationContext. "
        "Please add/verify orientation before exporting a footprint."
    )


def rotate_xy(points: Iterable[Tuple[float, float]], yaw_deg: float):
    """Rotate XY around origin by +yaw_deg (counter-clockwise)."""
    th = math.radians(yaw_deg)
    c, s = math.cos(th), math.sin(th)
    for x, y in points:
        yield (c * x - s * y, s * x + c * y)


def triangles_xy(shape, horizontal_only=True, nz_thresh=0.9, min_tri_area=0.01):
    """
    Yield triangle XY tuples from an ifcopenshell shape (world coords).
    If horizontal_only=True, keep triangles whose |normalized nz| >= nz_thresh.
    Also drops triangles with projected area < min_tri_area (m²).
    """
    vs = shape.geometry.verts
    fs = shape.geometry.faces
    i = 0
    while i < len(fs):
        n = fs[i]; i += 1
        if n != 3:
            i += n
            continue
        i0, i1, i2 = fs[i:i+3]; i += 3
        x0, y0, z0 = vs[3*i0], vs[3*i0+1], vs[3*i0+2]
        x1, y1, z1 = vs[3*i1], vs[3*i1+1], vs[3*i1+2]
        x2, y2, z2 = vs[3*i2], vs[3*i2+1], vs[3*i2+2]

        # normal (unnormalized)
        ux, uy, uz = (x1-x0, y1-y0, z1-z0)
        vx, vy, vz = (x2-x0, y2-y0, z2-z0)
        nx = uy*vz - uz*vy
        ny = uz*vx - ux*vz
        nz = ux*vy - uy*vx
        norm = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
        nz_norm = nz / norm

        if horizontal_only and abs(nz_norm) < nz_thresh:
            continue  # skip near-vertical/oblique faces

        tri = Polygon([(x0, y0), (x1, y1), (x2, y2)])
        if tri.area < min_tri_area:
            continue  # drop tiny slivers
        yield ( (x0, y0), (x1, y1), (x2, y2) )



def slab_mean_z(shape) -> float:
    """Mean Z of a meshed shape (used to find lowest slab band)."""
    zs = shape.geometry.verts[2::3]
    return (sum(zs) / len(zs)) if zs else 0.0


def collect_floor_footprint_polys(model) -> MultiPolygon:
    """
    Pick the lowest slabs (≈ ground floor), union their *horizontal* triangles in XY,
    then keep the largest polygon and remove tiny pieces/holes.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    slab_shapes = []
    for slab in model.by_type("IfcSlab"):
        try:
            shp = ifcopenshell.geom.create_shape(settings, slab)
        except Exception:
            continue
        slab_shapes.append((slab_mean_z(shp), shp))

    if not slab_shapes:
        raise RuntimeError("No IfcSlab geometry found.")

    slab_shapes.sort(key=lambda t: t[0])
    z0 = slab_shapes[0][0]
    band = [shp for z, shp in slab_shapes if z <= z0 + 0.6]  # ground band

    # union horizontal triangles only
    tris = [Polygon(t) for shp in band for t in triangles_xy(
        shp, horizontal_only=True, nz_thresh=0.92, min_tri_area=0.02
    )]
    if not tris:
        raise RuntimeError("No horizontal slab triangles found at ground level.")

    merged = unary_union(tris)

    # clean slivers/spikes: small closing–opening buffer
    merged = merged.buffer(0.15).buffer(-0.15)

    # dissolve to MultiPolygon and keep the largest piece
    merged = merged.buffer(0)  # topology fix
    if merged.is_empty:
        raise RuntimeError("Footprint union is empty after cleanup.")

    if isinstance(merged, Polygon):
        polys = [merged]
    else:
        polys = list(merged.geoms)

    # drop tiny pieces (< 20 m²) and keep the largest
    polys = [p for p in polys if p.area >= 20.0]
    if not polys:
        raise RuntimeError("All polygons were smaller than the area threshold.")

    largest = max(polys, key=lambda p: p.area)

    # remove tiny holes (< 10 m²)
    if largest.interiors:
        cleaned = Polygon(
            largest.exterior.coords,
            [ring for ring in largest.interiors if Polygon(ring).area >= 10.0]
        )
    else:
        cleaned = largest

    return MultiPolygon([cleaned])
# ---------- exporter ----------
def _close_ring(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Ensure first==last for GeoJSON ring."""
    if not coords:
        return coords
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    return coords


def export_floor_footprint_geojson(ifc_path: Path, out_geojson: Path):
    model = ifcopenshell.open(str(ifc_path))
    if not model:
        raise RuntimeError(f"Could not open {ifc_path}")

    # Site lat/lon for georeferencing (WGS84)
    site = (model.by_type("IfcSite") or [None])[0]
    lat = dms_to_decimal(getattr(site, "RefLatitude", (0, 0, 0))) if site else 0.0
    lon = dms_to_decimal(getattr(site, "RefLongitude", (0, 0, 0))) if site else 0.0

    # Get footprint (model XY, metres)
    footprint = collect_floor_footprint_polys(model)

    # Require TrueNorth and compute yaw (+Y → True North)
    yaw = project_north_yaw_degrees(model)

    # Local AEQD CRS centered at the site; then convert to WGS84
    aeqd = CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs"
    )
    wgs84 = CRS.from_epsg(4326)
    to_wgs84 = Transformer.from_crs(aeqd, wgs84, always_xy=True)

    # Rotate coords then transform to lon/lat
    features = []
    geoms = footprint.geoms if isinstance(footprint, MultiPolygon) else [footprint]
    for poly in geoms:
        # exterior
        ext_rot = list(rotate_xy(list(poly.exterior.coords), yaw))
        ext_rot = _close_ring(ext_rot)
        ext_ll = [to_wgs84.transform(x, y) for (x, y) in ext_rot]

        # holes (if any)
        holes_ll = []
        for h in poly.interiors:
            h_rot = list(rotate_xy(list(h.coords), yaw))
            h_rot = _close_ring(h_rot)
            holes_ll.append([to_wgs84.transform(x, y) for (x, y) in h_rot])

        features.append(
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ext_ll] + holes_ll,
                },
            }
        )

    fc = {
        "type": "FeatureCollection",
        "features": features,
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
    }
    out_geojson.write_text(json.dumps(fc, indent=2))
    print(f"✅ Wrote {out_geojson}  |  polygons: {len(features)}")


# ---------- CLI ----------
if __name__ == "__main__":
    # Your requested filenames
    ifc = Path("BK_v2_vb_updated.ifc")
    out = Path("bk_envelope_v3.geojson")
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        export_floor_footprint_geojson(ifc, out)
    except Exception as e:
        print(f"❌ Error: {e}")
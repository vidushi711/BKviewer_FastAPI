# #!/usr/bin/env python3
# """
# Standalone script to extract room (IfcSpace) bounding boxes from an IFC file
# and save them as GeoJSON for Cesium bounding‐box selection.

# Usage (from project root):
#     python IFCpreprocess/ifcspaces_bb_v2.py

# Output:
#     GeoJSON written to  output/IFC_BB/spaces_bboxes.geojson
# """
# import json
# from pathlib import Path

# import ifcopenshell
# import ifcopenshell.geom
# from pyproj import Transformer

# IFC_PATH       = Path("../static/IFC/BK_v2_vb_updated.ifc")
# OUTPUT_GEOJSON = Path("../output/IFC_BB/spaces_bboxes.geojson")

# def dms_to_decimal(dms):
#     deg = dms[0]
#     minute = dms[1] if len(dms) > 1 else 0
#     sec = dms[2]    if len(dms) > 2 else 0
#     sign = 1 if deg >= 0 else -1
#     return sign * (abs(deg) + minute/60 + sec/3600)

# def compute_bounding_box(verts):
#     xs = verts[0::3]
#     ys = verts[1::3]
#     zs = verts[2::3]
#     return {
#         "xmin": min(xs), "xmax": max(xs),
#         "ymin": min(ys), "ymax": max(ys),
#         "zmin": min(zs), "zmax": max(zs),
#     }

# def main():
#     model = ifcopenshell.open(IFC_PATH)
#     site = model.by_type("IfcSite")[0]
#     lat  = dms_to_decimal(site.RefLatitude)
#     lon  = dms_to_decimal(site.RefLongitude)
#     elev = float(getattr(site, "RefElevation", 0.0))

#     # geodetic ↔ ECEF
#     to_ecef   = Transformer.from_crs("EPSG:4326", "EPSG:4978", always_xy=True)
#     to_geoide = Transformer.from_crs("EPSG:4978", "EPSG:4326", always_xy=True)

#     # site origin in ECEF
#     sx, sy, sz = to_ecef.transform(lon, lat, elev)

#     settings = ifcopenshell.geom.settings()
#     settings.set(settings.USE_WORLD_COORDS, True)

#     features = []
#     for space in model.by_type("IfcSpace"):
#         try:
#             shape = ifcopenshell.geom.create_shape(settings, space)
#         except:
#             continue
#         verts = shape.geometry.verts
#         bb    = compute_bounding_box(verts)
#         xmin, ymin, zmin = bb["xmin"], bb["ymin"], bb["zmin"]
#         xmax, ymax, zmax = bb["xmax"], bb["ymax"], bb["zmax"]

#         # base‐ring in local coords
#         ring = [
#             (xmin, ymin, zmin),
#             (xmax, ymin, zmin),
#             (xmax, ymax, zmin),
#             (xmin, ymax, zmin),
#             (xmin, ymin, zmin),
#         ]
#         # shift to ECEF
#         ecef_ring = [(x+sx, y+sy, z+sz) for x,y,z in ring]
#         # reproject to lon/lat/alt
#         geo_ring = [list(to_geoide.transform(ex,ey,ez)) for ex,ey,ez in ecef_ring]

#         features.append({
#             "type": "Feature",
#             "properties": {
#                 "id": space.GlobalId,
#                 "name": space.LongName or space.Name or space.GlobalId,
#                 "height": zmin + elev,
#                 "extrudedHeight": zmax + elev
#             },
#             "geometry": {
#                 "type": "Polygon",
#                 "coordinates": [geo_ring]
#             }
#         })

#     geojson = {"type":"FeatureCollection","features":features}
#     OUTPUT_GEOJSON.parent.mkdir(exist_ok=True, parents=True)
#     OUTPUT_GEOJSON.write_text(json.dumps(geojson, indent=2))
#     print(f"Wrote {len(features)} features to {OUTPUT_GEOJSON}")

# if __name__ == "__main__":
#     main()



#!/usr/bin/env python3
"""
Extract IfcSpace bounding‐boxes from IFC and write raw JSON
with optional translation + rotation baked into the bboxes.

Output:
    output/IFC_BB/spaces_bboxes.json
"""
import json
import math
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom


# user‐tweakable parameters (in model‐local metres):
SHIFT_LOCAL     = (-230.0, -80.0, -5.0)   # translate +10m in X, –5m in Y, +0 in Z
ROTATION_DEG_Z  = 0               # clockwise rotation about local Z (deg)

# paths:
IFC_PATH        = Path("../static/IFC/BK_v2_vb_updated.ifc")
OUTPUT_JSON     = Path("../output/IFC_BB/spaces_bboxes.json")


def compute_bounding_box(verts):
    xs, ys, zs = verts[0::3], verts[1::3], verts[2::3]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def make_transform(shift, rot_deg):
    """Return a function that (x,y,z) → rotated+shifted (x',y',z')."""
    theta = math.radians(rot_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    sx, sy, sz   = shift
    def xf(x, y, z):
        # rotate around Z
        xr =  cos_t * x - sin_t * y
        yr =  sin_t * x + cos_t * y
        zr =  z
        # then shift
        return xr + sx, yr + sy, zr + sz
    return xf


def main():
    if not IFC_PATH.exists():
        raise FileNotFoundError(f"IFC not found at {IFC_PATH}")

    # open and prepare IfcOpenShell
    model    = ifcopenshell.open(IFC_PATH)
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    # build our local→local transform
    transform = make_transform(SHIFT_LOCAL, ROTATION_DEG_Z)

    out = []
    for space in model.by_type("IfcSpace"):
        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
        except Exception:
            # skip if no geometry
            continue

        # 1) raw local bbox
        xmin, ymin, zmin, xmax, ymax, zmax = compute_bounding_box(shape.geometry.verts)

        # 2) enumerate the 8 corners
        corners = [
            (xmin, ymin, zmin),
            (xmax, ymin, zmin),
            (xmax, ymax, zmin),
            (xmin, ymax, zmin),
            (xmin, ymin, zmax),
            (xmax, ymin, zmax),
            (xmax, ymax, zmax),
            (xmin, ymax, zmax),
        ]

        # 3) apply our rotation+translation to each corner
        tcorners = [transform(x, y, z) for x, y, z in corners]

        # 4) recompute a tight bbox around the transformed corners
        xs, ys, zs = zip(*tcorners)
        tbbox = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]

        out.append({
            "id":   space.GlobalId,
            "name": space.LongName or space.Name or space.GlobalId,
            "bbox": tbbox
        })

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"Wrote {len(out)} spaces → {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
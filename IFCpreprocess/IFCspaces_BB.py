"""
Standalone script to extract room (IfcSpace) bounding boxes from an IFC file
and save them as JSON for Cesium bounding‐box selection.

Location:
    IFCpreprocess/IFCspaces_BB.py

Usage (from project root):
    python IFCpreprocess/IFCspaces_BB.py

Output:
    JSON written to  output/IFC_BB/spaces_bboxes.json
"""
import json
from pathlib import Path
import ifcopenshell
import ifcopenshell.geom

# ------------------------------------------------------------------
# CONFIGURATION: path to your IFC file (inside static/IFC)
IFC_PATH = Path("../static/IFC/BK_v2_vb_updated.ifc")
OUTPUT_JSON = Path("../output/IFC_BB/spaces_bboxes.json")
# ------------------------------------------------------------------

def compute_bounding_box(verts):
    """
    Given a flat list of vertex coordinates [x0,y0,z0, x1,y1,z1, ...],
    compute axis-aligned bounding box.
    """
    xs = verts[0::3]
    ys = verts[1::3]
    zs = verts[2::3]
    return {
        "xmin": min(xs),
        "xmax": max(xs),
        "ymin": min(ys),
        "ymax": max(ys),
        "zmin": min(zs),
        "zmax": max(zs),
    }


def main():
    if not IFC_PATH.exists():
        raise FileNotFoundError(f"IFC file not found at {IFC_PATH}")

    print(f"Opening IFC: {IFC_PATH}")
    model = ifcopenshell.open(IFC_PATH)

    # Prepare geometry settings for world coords
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    spaces = model.by_type("IfcSpace")
    if not spaces:
        print("No IfcSpace entities found in model.")
        return

    output = []
    for space in spaces:
        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
        except Exception as e:
            print(f"Skipping space {space.GlobalId}: cannot create geometry ({e})")
            continue

        verts = shape.geometry.verts
        bbox = compute_bounding_box(verts)

        # Collect space metadata
        name = space.LongName or space.Name or space.GlobalId
        output.append({
            "id": space.GlobalId,
            "name": name,
            "bbox": [bbox["xmin"], bbox["ymin"], bbox["zmin"],
                     bbox["xmax"], bbox["ymax"], bbox["zmax"]]
        })

    # Ensure output directory exists
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
       json.dump(output, f, indent=2)

    print(f"Wrote {len(output)} spaces to {OUTPUT_JSON}")


if __name__ == '__main__':
    main()

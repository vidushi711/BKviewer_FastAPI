# check_ifc.py
from pathlib import Path
import sys
import traceback
import ifcopenshell
from ifc_parsers import extract_site_details  # must be in same folder or on PYTHONPATH


def check_ifc_georef(ifc_path: str | Path):
    ifc_path = Path(ifc_path)
    print(f"\nDEBUG: Starting georef check for: {ifc_path.resolve()}")

    if not ifc_path.exists():
        print(f"❌ File not found: {ifc_path.resolve()}")
        return

    try:
        # --- Step 1: Open the IFC ---
        model = ifcopenshell.open(str(ifc_path))
        if not model:
            print(f"❌ Could not open file: {ifc_path}")
            return

        print(f"\n🔍 Checking georeferencing for: {ifc_path}\n")

        # --- Step 2: Extract site details (your helper) ---
        site = extract_site_details(ifc_path)
        print(f"📍 Latitude (decimal):  {site.latitude:.6f}")
        print(f"📍 Longitude (decimal): {site.longitude:.6f}")
        print(f"📏 Elevation:           {site.elevation:.2f} m")

        # --- Step 3: Schema check + MapConversion ---
        schema = model.schema.lower()  # e.g. "ifc2x3", "ifc4", "ifc4x3"
        print(f"🧩 IFC schema: {schema.upper()}")

        if "ifc4" in schema:
            # IFC4/IFC4x3 path
            try:
                conversions = model.by_type("IfcMapConversion")
                if conversions:
                    print(f"\n🗺 Found {len(conversions)} IfcMapConversion entries:")
                    for i, mc in enumerate(conversions, start=1):
                        print(f"  → MapConversion #{i}")
                        print(f"     Eastings:         {mc.Eastings}")
                        print(f"     Northings:        {mc.Northings}")
                        print(f"     OrthogonalHeight: {mc.OrthogonalHeight}")
                        print(f"     XAxisAbscissa:    {mc.XAxisAbscissa}")
                        print(f"     XAxisOrdinate:    {mc.XAxisOrdinate}")
                        print(f"     Scale:            {mc.Scale}")
                else:
                    print("⚠️ No IfcMapConversion found (IFC4 file, but unprojected).")
            except Exception as e:
                print(f"⚠️ Could not read IfcMapConversion: {e}")

        else:
            # IFC2x3 path
            print("ℹ️ IFC2x3 detected: standard IfcMapConversion is not available.")
            print("   Rely on IfcSite RefLatitude/RefLongitude and local placements.")

            # Optional: look for CRS hints
            try:
                from ifcopenshell.util.element import get_psets
                hints = []
                for obj in model:
                    psets = get_psets(obj)
                    for pset_name, props in psets.items():
                        for k, v in props.items():
                            text = f"{pset_name}.{k}"
                            if any(s in text.lower() for s in ["epsg", "crs", "mapconversion", "projection"]):
                                hints.append((pset_name, k, v))
                if hints:
                    print("\n🔎 Possible CRS/EPSG hints found in property sets:")
                    for p, k, v in hints[:20]:
                        print(f"   {p}.{k} = {v}")
                else:
                    print("🔎 No obvious CRS/EPSG hints found in property sets.")
            except Exception as e:
                print(f"⚠️ Pset scan skipped: {e}")

        # --- Step 4: Check placements for orientation ---
        placements = model.by_type("IfcLocalPlacement")
        if placements:
            print(f"\n🧭 Found {len(placements)} IfcLocalPlacement entries.")
            root_placements = [p for p in placements if not getattr(p, "PlacementRelTo", None)]
            print(f"   Root placements (no parent): {len(root_placements)}")
        else:
            print("⚠️ No placement entities found — model may lack orientation info.")

        print("\n✅ Georeference check completed.\n")

    except Exception:
        print("❌ Exception while checking georeferencing:")
        traceback.print_exc()


# --- ORIENTATION CHECK ---
import math
from collections import Counter
import ifcopenshell.util.placement

def _deg(x: float) -> float:
    return (x + 360.0) % 360.0

def _yaw_from_matrix(M):
    """
    Extract yaw (rotation about Z) from a 4x4 transform matrix (row-major).
    Assumes Z-up, no shear. Yaw is angle of +X axis relative to world +X.
    """
    # Matrix layout (Blender/OpenCascade-style row-major):
    # [m00 m01 m02 m03]
    # [m10 m11 m12 m13]
    # [m20 m21 m22 m23]
    # [m30 m31 m32 m33]
    m00, m01 = M[0][0], M[0][1]
    m10, m11 = M[1][0], M[1][1]
    # yaw can be derived from the XY part; use atan2 of X-axis projected on XY plane
    yaw_rad = math.atan2(m10, m00)  # rotation that takes world X to local X
    return math.degrees(yaw_rad)

def _azimuth_from_dir2d(dir2d):
    """
    IFC TrueNorth is an IfcDirection with 2 or 3 components: (x, y [, z]).
    Convert to azimuth: degrees clockwise from North (Y axis), with 0°=North, 90°=East.
    """
    x, y = dir2d[0], dir2d[1]
    # azimuth measured clockwise from +Y:
    # atan2(x, y) → 0 when pointing North (0,1); positive towards East.
    az = math.degrees(math.atan2(x, y))
    return _deg(az)

def _get_true_north_az(model) -> float | None:
    """
    Try to read TrueNorth from IfcGeometricRepresentationContext (IFC2x3/IFC4).
    Returns azimuth (° cw from North) or None if not present.
    """
    for ctx in model.by_type("IfcGeometricRepresentationContext"):
        tn = getattr(ctx, "TrueNorth", None)
        if tn and getattr(tn, "DirectionRatios", None):
            dr = tn.DirectionRatios
            if len(dr) >= 2:
                return _azimuth_from_dir2d(dr)
    return None

def _placement_yaw(entity) -> float | None:
    """
    Get yaw (°) of an entity’s ObjectPlacement (IfcLocalPlacement) using IfcOpenShell.
    """
    op = getattr(entity, "ObjectPlacement", None)
    if not op:
        return None
    M = ifcopenshell.util.placement.get_local_placement(op)
    # M is a 4x4 list of lists
    return _deg(_yaw_from_matrix(M))

def check_ifc_orientation(ifc_path: str | Path):
    model = ifcopenshell.open(str(ifc_path))
    if not model:
        print("❌ Could not open IFC")
        return

    print("\n🧭 ORIENTATION CHECK")
    schema = model.schema
    print(f"   IFC schema: {schema}")

    # 1) True North (if authoring tool set it)
    tn_az = _get_true_north_az(model)
    if tn_az is not None:
        print(f"   True North (from context): {tn_az:.2f}° (0°=North, 90°=East)")
    else:
        print("   True North: not defined in file (common in IFC2x3).")

    # 2) Yaw of Site and Building (rotation around Z)
    site = (model.by_type("IfcSite") or [None])[0]
    bldg = (model.by_type("IfcBuilding") or [None])[0]

    site_yaw = _placement_yaw(site) if site else None
    bldg_yaw = _placement_yaw(bldg) if bldg else None

    if site_yaw is not None:
        print(f"   IfcSite yaw (Z-rotation): {site_yaw:.2f}°")
    else:
        print("   IfcSite yaw: n/a")

    if bldg_yaw is not None:
        print(f"   IfcBuilding yaw (Z-rotation): {bldg_yaw:.2f}°")
    else:
        print("   IfcBuilding yaw: n/a")

    # 3) Deviation between model axes and True North (if available)
    if tn_az is not None:
        # Many tools treat +Y as project North. Compare +Y with True North.
        # IfcLocalPlacement gives the full rotation; we report deviation using building yaw.
        # Deviation if you assume +Y is “project north”:
        # model +Y azimuth = (bldg_yaw + 90) mod 360 (since yaw aligns world X to local X)
        if bldg_yaw is not None:
            proj_north_az = _deg(bldg_yaw + 90.0)
            dev = _deg(proj_north_az - tn_az)
            dev_alt = 360.0 - dev if dev > 180 else dev
            print(f"   Project North (assumed +Y) azimuth: {proj_north_az:.2f}°")
            print(f"   Deviation from True North: {dev_alt:.2f}°")
        elif site_yaw is not None:
            proj_north_az = _deg(site_yaw + 90.0)
            dev = _deg(proj_north_az - tn_az)
            dev_alt = 360.0 - dev if dev > 180 else dev
            print(f"   (Using IfcSite) Project North azimuth: {proj_north_az:.2f}°")
            print(f"   Deviation from True North: {dev_alt:.2f}°")

    # # 4) OPTIONAL: sample external walls to see dominant façade azimuths
    # try:
    #     walls = model.by_type("IfcWall")[:1000]  # sample cap
    #     az_counts = Counter()
    #     for w in walls:
    #         op = getattr(w, "ObjectPlacement", None)
    #         if not op:
    #             continue
    #         M = ifcopenshell.util.placement.get_local_placement(op)
    #         yaw = _deg(_yaw_from_matrix(M))
    #         # Quantize to nearest 5° to group
    #         bucket = 5 * round(yaw / 5.0)
    #         az_counts[bucket] += 1
    #     if az_counts:
    #         top = az_counts.most_common(6)
    #         print("\n   Dominant wall yaw buckets (° from world X):")
    #         for ang, cnt in top:
    #             print(f"     {ang:>4.0f}° : {cnt} walls")
    #         print("   (Rough “axis” azimuths are these ±90°)")
    #     else:
    #         print("\n   Could not sample wall azimuths (no placements).")
    # except Exception:
    #     print("\n   Skipped façade azimuth sampling (geom/placement issue).")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    default = Path("static/IFC/BK_v6_ifc4_georef_transformed.ifc")
    path_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    check_ifc_georef(path_arg)
    check_ifc_orientation(path_arg)
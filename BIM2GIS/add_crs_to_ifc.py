# add_crs_to_ifc.py
from pathlib import Path
import math
import ifcopenshell

# ---- USER INPUTS (RD New / EPSG:28992 numbers from QGIS) ----
IN  = Path("BK_v4_ifc4.ifc")                 # your IFC4 file
OUT = Path("BK_v5_ifc4_georef_epsg.ifc")     # output

EASTINGS  = 85209.0452983815
NORTHINGS = 446844.3563249507
HEIGHT    = 0.0

# If you want NO rotation: set AZIMUTH_DEG = 0 (Easting axis aligns with +X)
AZIMUTH_DEG = 0.0   # CCW rotation from East to your model's X-axis

# ---- derived: unit vector for X axis from azimuth ----
rad = math.radians(AZIMUTH_DEG)
X_ABSCISSA = math.cos(rad)
X_ORDINATE = math.sin(rad)
SCALE = 1.0

def get_model_context(model):
    ctxs = model.by_type("IfcGeometricRepresentationContext")
    if not ctxs:
        raise RuntimeError("No IfcGeometricRepresentationContext in file.")
    # prefer the one whose ContextIdentifier == 'Model'
    model_ctx = next((c for c in ctxs if (getattr(c, "ContextIdentifier", None) or "").lower()=="model"), None)
    return model_ctx or ctxs[0]

def get_metre_unit(model):
    # Try to reuse existing metre unit
    uas = model.by_type("IfcUnitAssignment")
    if uas:
        for u in uas[0].Units:
            if u.is_a("IfcSIUnit") and getattr(u, "UnitType", None) == "LENGTHUNIT" and getattr(u, "Name", None) == "METRE":
                return u
    # else create a standalone unit (allowed)
    return model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")

def normalize_xy(x, y):
    n = math.hypot(x, y)
    if n == 0:
        raise ValueError("X axis vector cannot be zero; set a valid azimuth.")
    return (x / n, y / n)

def main():
    m = ifcopenshell.open(str(IN))

    # 1) Schema guard
    if not m.schema.lower().startswith("ifc4"):
        raise RuntimeError(f"Schema {m.schema} not supported. Convert to IFC4 first (you already did with Migrate).")

    # 2) Context
    ctx = get_model_context(m)

    # 3) Units
    map_unit = get_metre_unit(m)

    # 4) Normalize axis
    xa, yo = normalize_xy(X_ABSCISSA, X_ORDINATE)

    # 5) MapConversion: update or create
    mcs = [mc for mc in m.by_type("IfcMapConversion") if getattr(mc, "SourceCRS", None) == ctx]
    if mcs:
        mc = mcs[0]
    else:
        mc = m.create_entity("IfcMapConversion", SourceCRS=ctx)

    mc.Eastings = float(EASTINGS)
    mc.Northings = float(NORTHINGS)
    mc.OrthogonalHeight = float(HEIGHT)
    mc.XAxisAbscissa = float(xa)
    mc.XAxisOrdinate = float(yo)
    mc.Scale = float(SCALE)
    mc.SourceCRS = ctx

    # 6) Projected CRS: create or reuse
    proj = getattr(mc, "TargetCRS", None)
    if not proj or not proj.is_a("IfcProjectedCRS"):
        # Minimal but informative naming
        proj = m.create_entity(
            "IfcProjectedCRS",
            Name="EPSG:28992",
            MapUnit=map_unit,
            GeodeticDatum="Amersfoort",
            MapProjection="RD New"
        )
        mc.TargetCRS = proj
    else:
        proj.Name = "EPSG:28992"
        proj.MapUnit = map_unit
        proj.GeodeticDatum = "Amersfoort"
        proj.MapProjection = "RD New"

    m.write(str(OUT))
    print(f"✅ Written: {OUT}")
    print(f"   Schema: {m.schema}")
    print(f"   Context: {(ctx.ContextIdentifier or '<<no id>>')}")
    print(f"   MapConversion: E={mc.Eastings}, N={mc.Northings}, H={mc.OrthogonalHeight}")
    print(f"   XAxis: ({mc.XAxisAbscissa:.6f}, {mc.XAxisOrdinate:.6f})  Scale={mc.Scale}")
    print(f"   TargetCRS: {mc.TargetCRS.Name}, Unit={getattr(mc.TargetCRS.MapUnit,'Name',None)}")

if __name__ == "__main__":
    main()
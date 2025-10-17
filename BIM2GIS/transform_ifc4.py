import ifcopenshell, math

src = "BK_v5_ifc4_georef_epsg.ifc"
dst = "BK_v6_ifc4_georef_transformed.ifc"

f = ifcopenshell.open(src)
ctx = f.by_type("IfcGeometricRepresentationContext")[0]

# Get existing IfcMapConversion
mc = None
for op in (ctx.HasCoordinateOperation or []):
    if op.is_a("IfcMapConversion"):
        mc = op; break
assert mc, "No IfcMapConversion found"

# --- COMMENT OUT TRANSLATION LINES (keep current values) ---
mc.Eastings  = (mc.Eastings  or 0.0) 10.0  
mc.Northings = (mc.Northings or 0.0) 5.0   

# --- ROTATION ONLY ---
# 130° clockwise means -130° CCW
theta = math.radians(-130.0)
mc.XAxisAbscissa = math.cos(theta)
mc.XAxisOrdinate = math.sin(theta)
# (mc.Scale, mc.OrthogonalHeight remain unchanged)

f.write(dst)
print("Wrote", dst)
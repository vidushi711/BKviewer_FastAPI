import ifcopenshell

ifc_path = "/Users/vb/Desktop/VBThesisCode/vb_resources/BK_BIM/ifc/BK_v2_vb.ifc"

# Loading duplicated IFC file
model = ifcopenshell.open(ifc_path)

# Getting IfcSite object
site = model.by_type("IfcSite")[0]

# --- Updating geographic data ---
# BK, Delft coordinates
# 52.00555684869794° N → (52, 0, 20, ~200_000)
# 4.3708261705353175° E → (4, 22, 15, ~297_000)
site.RefLatitude = [52, 0, 20, int(0.55684869794 * 1_000_000)]
site.RefLongitude = [4, 22, 15, int(0.8261705353175 * 1_000_000)]
site.RefElevation = 0.0  

#  Next 2 codelines Redundant  - IfcSite schema in IFC2X3 does not include a TimeZone attribute.
# # Update time zone (+1 = CET, +2 = CEST; depending on whether DST is in effect)
# site.TimeZone = "+2.0"  # will need to be canged to "+1.0" for CET (winter)

# Confirm update
print(" Updated geolocation:")
print("  RefLatitude:", site.RefLatitude)
print("  RefLongitude:", site.RefLongitude)
print("  RefElevation:", site.RefElevation)

# Get owner history (required for creating entities in IFC2X3)
owner_history = model.by_type("IfcOwnerHistory")[0]

# Add address info as a property set (IFC2X3-compatible)
pset_address = model.create_entity("IfcPropertySet",
    GlobalId=ifcopenshell.guid.new(),
    OwnerHistory=owner_history,
    Name="Pset_SiteAddress",
    HasProperties=[
        model.create_entity("IfcPropertySingleValue", Name="Institution", NominalValue=model.create_entity("IfcText", "TU Delft Faculty of Architecture & the Built Environment"), Unit=None),
        model.create_entity("IfcPropertySingleValue", Name="Town", NominalValue=model.create_entity("IfcLabel", "Delft"), Unit=None),
        model.create_entity("IfcPropertySingleValue", Name="Region", NominalValue=model.create_entity("IfcLabel", "South Holland"), Unit=None),
        model.create_entity("IfcPropertySingleValue", Name="PostalCode", NominalValue=model.create_entity("IfcLabel", "2628 BZ"), Unit=None),
        model.create_entity("IfcPropertySingleValue", Name="Country", NominalValue=model.create_entity("IfcLabel", "Netherlands"), Unit=None),
    ]
)

# Link the Pset to the IfcSite
model.create_entity("IfcRelDefinesByProperties",
    GlobalId=ifcopenshell.guid.new(),
    OwnerHistory=owner_history,
    RelatedObjects=[site],
    RelatingPropertyDefinition=pset_address
)

# Confirm address set
print("\n Created and linked address as Pset_SiteAddress.")

# Save the updated file
updated_path = ifc_path.replace(".ifc", "_updated.ifc")
model.write(updated_path)

print(f"Updated IFC saved to: {updated_path}")
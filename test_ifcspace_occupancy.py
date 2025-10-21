# import ifcopenshell
# import ifcopenshell.util.element

# m = ifcopenshell.open("static/IFC/BK_v6_ifc4_georef_transformed.ifc")

# for s in m.by_type("IfcSpace"):
#     psets = ifcopenshell.util.element.get_psets(s)
#     for pname, pdata in psets.items():
#         for key, val in pdata.items():
#             if any(word in key.lower() for word in ["occup", "person", "load", "density"]):
#                 print(f"{s.Name or s.LongName}: {pname}.{key} = {val}")


# FOLLOWING SCRIPT finds the space whose Name or LongName equals BG.West.010, and then dumps “everything useful” about that space
# works with both IFC2X3 and IFC4 files
# inspect_space_occupancy.py
from __future__ import annotations
from pathlib import Path
from typing import Iterable, Dict, Any, List
import sys

import ifcopenshell
from ifcopenshell.util.element import get_psets

# --------- CONFIG: edit if you want to hardcode inputs ----------
IFC_PATH  = Path("static/IFC/BK_v6_ifc4_georef_transformed.ifc")
SPACE_KEY = "01.West.120"   # matches Name or LongName (case-insensitive)
# ---------------------------------------------------------------

def by_types(model, type_names: Iterable[str]):
    """Return instances for all type names that exist in this schema."""
    out = []
    for t in type_names:
        try:
            out.extend(model.by_type(t))
        except RuntimeError:
            # Type doesn't exist in this schema; skip
            continue
    return out

def find_space(model, key: str):
    t = key.strip().lower()
    for s in model.by_type("IfcSpace"):
        nm  = (s.Name or "").strip().lower()
        lnm = (getattr(s, "LongName", "") or "").strip().lower()
        if t in (nm, lnm):
            return s
    return None

def pp(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

def print_psets(space):
    pp("Property sets (including quantities) for this space")
    psets: Dict[str, Dict[str, Any]] = get_psets(space) or {}
    if not psets:
        print("(No property sets found)")
        return
    for pset_name, props in sorted(psets.items()):
        print(f"[{pset_name}]")
        if not props:
            print("  (empty)")
            continue
        for k, v in sorted(props.items()):
            print(f"  - {k}: {v}")

def print_occupancy_like(space):
    pp("Occupancy-like properties (keyword search)")
    psets: Dict[str, Dict[str, Any]] = get_psets(space) or {}
    hits = []
    KW = ("occup", "people", "person", "density", "per person", "per area", "load")
    for pset, props in psets.items():
        for k, v in props.items():
            if any(w in k.lower() for w in KW):
                hits.append((pset, k, v))
    if hits:
        for pset, k, v in hits:
            print(f"  {pset}.{k} = {v}")
    else:
        print("(No obvious occupancy-like properties found)")

def print_occupants(model, space):
    pp("Actors/occupants linked by relationships")
    # IFC4 pattern (assignments)
    rel_assigns = by_types(model, ["IfcRelAssignsToActor"])
    count = 0
    for rel in rel_assigns:
        related = list(getattr(rel, "RelatedObjects", []) or [])
        if space in related:
            actor = getattr(rel, "RelatingActor", None)
            if actor:
                count += 1
                print(f"  IFC4 AssignsToActor → {actor.is_a()}  Name={getattr(actor, 'Name', None)}")
    if count == 0:
        print("  (No IFC4 actor assignments found)")

    # IFC2X3 pattern (occupies spaces)
    rel_occ = by_types(model, ["IfcRelOccupiesSpaces"])  # not in IFC4
    count2 = 0
    for rel in rel_occ:
        # IFC2x3 may use RelatedSpace (single) or RelatedSpaces (list)
        rs = getattr(rel, "RelatedSpace", None)
        rlist = getattr(rel, "RelatedSpaces", None)
        related = []
        if rs is not None:
            related = [rs]
        elif rlist is not None:
            related = list(rlist or [])
        if space in related:
            actor = getattr(rel, "RelatingActor", None) or getattr(rel, "RelatingOccupant", None)
            if actor:
                count2 += 1
                print(f"  IFC2x3 RelOccupiesSpaces → {actor.is_a()}  Name={getattr(actor,'Name',None)}")
    if count2 == 0:
        print("  (No IFC2x3 occupies-spaces links found)")

def print_space_boundaries(model, space):
    pp("Space boundaries (if available in schema)")
    # IFC4 names + IFC2X3 name
    rels = by_types(model, ["IfcRelSpaceBoundary2ndLevel",
                            "IfcRelSpaceBoundary1stLevel",
                            "IfcRelSpaceBoundary"])
    n = 0
    for rel in rels:
        # Each rel links a space to some element (wall, slab, etc.)
        sp = getattr(rel, "RelatingSpace", None)
        if sp and sp == space:
            n += 1
            elem = getattr(rel, "RelatedBuildingElement", None)
            if elem:
                print(f"  Boundary → {elem.is_a()}  GlobalId={getattr(elem,'GlobalId', None)}")
    if n == 0:
        print("  (No boundaries found or not authored in this file)")

def main():
    # Allow optional CLI override: python inspect_space_occupancy.py /path/to.ifc "Room Name"
    if len(sys.argv) >= 2:
        ifc_path = Path(sys.argv[1])
    else:
        ifc_path = IFC_PATH
    if len(sys.argv) >= 3:
        space_key = sys.argv[2]
    else:
        space_key = SPACE_KEY

    if not ifc_path.exists():
        print(f"ERROR: IFC not found: {ifc_path}")
        sys.exit(1)

    m = ifcopenshell.open(str(ifc_path))
    print(f"Opened: {ifc_path.name}")
    print(f"Schema: {m.schema}")

    space = find_space(m, space_key)
    if not space:
        print(f"Space not found by Name/LongName: {space_key}")
        # As a hint, show a few spaces found
        spaces = m.by_type("IfcSpace")
        print(f"(Found {len(spaces)} spaces. Examples:)")
        for s in spaces[:8]:
            print("  -", (s.Name or ""), "|", (getattr(s, "LongName", "") or ""))
        sys.exit(1)

    nm = space.Name or ""
    lnm = getattr(space, "LongName", "") or ""
    print(f"Matched space: Name='{nm}'  LongName='{lnm}'  GlobalId={space.GlobalId}")

    print_psets(space)
    print_occupancy_like(space)
    print_occupants(m, space)
    print_space_boundaries(m, space)
    trace_property(m, space, "Number of People")       # exact
    trace_property(m, space, "Energy Analysis")   

# to see where and how occupancy data is stored in IFC
def trace_property(model, space, name_contains: str):
    """
    Find a property by (partial) name on a given space and print the IFC path:
    IfcSpace <- IfcRelDefinesByProperties -> IfcPropertySet/IfcElementQuantity -> property
    """
    key = name_contains.lower()

    print("\n" + "="*80)
    print(f"Trace property containing: '{name_contains}'")
    print("="*80)

    found = False

    # 1) Direct properties on the space via IfcRelDefinesByProperties
    for rel in model.by_type("IfcRelDefinesByProperties"):
        rel_objs = list(getattr(rel, "RelatedObjects", []) or [])
        if space not in rel_objs:
            continue

        pdef = getattr(rel, "RelatingPropertyDefinition", None)
        if not pdef:
            continue

        if pdef.is_a("IfcPropertySet"):
            # Standard property set
            pset = pdef
            for prop in list(pset.HasProperties or []):
                pname = (prop.Name or "")
                if key in pname.lower():
                    found = True
                    # Value extraction (IfcMeasure types have .wrappedValue)
                    val = getattr(prop, "NominalValue", None)
                    val_type = val.is_a() if val else None
                    val_wrapped = getattr(val, "wrappedValue", None) if val else None
                    print(f"* Hit in IfcPropertySet:")
                    print(f"  - IfcSpace.GlobalId           = {space.GlobalId}")
                    print(f"  - IfcRelDefinesByProperties   = #{rel.id()} ({rel.is_a()})")
                    print(f"  - IfcPropertySet              = #{pset.id()} Name='{pset.Name}'")
                    print(f"  - IfcPropertySingleValue      = #{prop.id()} Name='{pname}'")
                    print(f"  - NominalValue                = {val_wrapped}  (type: {val_type})")
        elif pdef.is_a("IfcElementQuantity"):
            # Quantities path (not your case here, but useful generally)
            qto = pdef
            for q in list(qto.Quantities or []):
                qname = (q.Name or "")
                if key in qname.lower():
                    found = True
                    magnitude = getattr(q, "CountValue", None) or getattr(q, "LengthValue", None) or \
                                getattr(q, "AreaValue", None) or getattr(q, "VolumeValue", None)
                    print(f"* Hit in IfcElementQuantity:")
                    print(f"  - IfcSpace.GlobalId           = {space.GlobalId}")
                    print(f"  - IfcRelDefinesByProperties   = #{rel.id()} ({rel.is_a()})")
                    print(f"  - IfcElementQuantity          = #{qto.id()} Name='{qto.Name}'")
                    print(f"  - {q.is_a()}                  = #{q.id()} Name='{qname}'  Value={magnitude}")

    # 2) Properties inherited from a type (IfcRelDefinesByType → IfcSpaceType → psets)
    for rel in model.by_type("IfcRelDefinesByType"):
        if space not in list(getattr(rel, "RelatedObjects", []) or []):
            continue
        st = getattr(rel, "RelatingType", None)
        if not st:
            continue

        # IfcSpaceType can have HasPropertySets (IfcPropertySet) or ElementType quantities
        psets = list(getattr(st, "HasPropertySets", []) or [])
        for pset in psets:
            if not pset or not pset.is_a("IfcPropertySet"):
                continue
            for prop in list(pset.HasProperties or []):
                pname = (prop.Name or "")
                if key in pname.lower():
                    found = True
                    val = getattr(prop, "NominalValue", None)
                    val_type = val.is_a() if val else None
                    val_wrapped = getattr(val, "wrappedValue", None) if val else None
                    print(f"* Hit via IfcSpaceType (RelDefinesByType):")
                    print(f"  - IfcSpace.GlobalId           = {space.GlobalId}")
                    print(f"  - IfcRelDefinesByType         = #{rel.id()} ({rel.is_a()})")
                    print(f"  - IfcSpaceType                = #{st.id()} Name='{getattr(st,'Name',None)}'")
                    print(f"  - IfcPropertySet              = #{pset.id()} Name='{pset.Name}'")
                    print(f"  - IfcPropertySingleValue      = #{prop.id()} Name='{pname}'")
                    print(f"  - NominalValue                = {val_wrapped}  (type: {val_type})")

    if not found:
        print("(No matches found for that property name on this space.)")    

if __name__ == "__main__":
    main()
from ifc_parsers import parse_room

IFC = "static/IFC/BK_v6_ifc4_georef_transformed.ifc"
ROOM = "BG.West.010"

site = parse_room(IFC, ROOM)
room = next(iter(site.rooms.values()))
for w in room.windows or []:
    print(w.global_id, f"tilt={w.tilt:.1f}°, az_trueN={w.azimuth:.1f}°")
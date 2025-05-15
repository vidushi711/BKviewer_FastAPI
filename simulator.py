import os
import ifcopenshell
from pathlib import Path
from typing import Union, Optional
from typing import Any

# Import mediator functions from parser module
from ifc_parsers import parse_room, BoundingBox, Window, Room, Site

IFC_PATH = os.path.join("static", "IFC", "BK_v2_vb_updated.ifc")

def predict_internal_temp(room_name: str, ifc_path: Union[str, Path] = IFC_PATH) -> dict[str, Any]:
    """
    Mediator function: given a room_name, extracts site and room details from corrected BK IFC
    """

    # Parse SELECTED ROOM into a Site object that has locational data
    site: Site = parse_room(ifc_path, room_name)
    # parse_room invokes extract_site_details internally to add locational data

    # Attempt to find the room by its long_name key
    room: Optional[Room] = site.rooms.get(room_name)
    # If eaxct match not found - try case-insensitive match
    if room is None:
        for key, r in site.rooms.items():
            if key.lower() == room_name.strip().lower():
                room = r
                break
    if room is None:
        raise ValueError(f"No room named '{room_name}' found in IFC rooms")

    # Serialize windows
    windows_out = []
    if room.windows:
        for w in room.windows:
            windows_out.append({
                "global_id": w.global_id,
                "room_name": w.room_name,
                "SHGC": w.SHGC,
                "area": w.area,
                "solar_inflow": w.solar_inflow,
                "is_external": w.is_external,
            })

    # Build and return JSON-serializable dict
    return {
        "global_id": room.global_id,
        "short_name": room.short_name,
        "long_name": room.long_name,
        "volume": room.volume,
        "windows": windows_out,
    }

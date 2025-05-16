from pathlib import Path
from dataclasses import dataclass
# external
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
# VB added
from typing import Optional, Union

# OBJECT DEFINITIONS
@dataclass
class BoundingBox:
    '''Storing bounds of rooms and windows.'''
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

@dataclass
class Window:
    global_id: str
    room_name: str
    bounding_box: Optional[BoundingBox] = None
    SHGC: Optional[float] = None
    area: Optional[float] = None
    solar_inflow: Optional[float] = None
    is_external: bool = False

@dataclass
class Room:
    global_id: str
    short_name: str
    long_name: str
    volume: float = 0
    bounding_box: Optional[BoundingBox] = None
    windows: Optional[list[Window]] = None

class Site:
    """
    The Site class holds site attributes and manages a collection of Room objects.
    """
    def __init__(self, latitude: float, longitude: float, elevation: float, timezone: str = "Europe/Amsterdam"):
        self.rooms: dict[str, Room] = {}
        self.latitude = latitude
        self.longitude = longitude
        self.elevation = elevation
        self.timezone = timezone

    def add_room(self, room: Room, key: Optional[str] = None) -> None:
        if key is None:
            key = room.short_name
        self.rooms[key] = room

# mini FUNCTION TO COMPUTE BOUNDING BOX
def compute_bounding_box(shape_obj) -> Optional[BoundingBox]:
    verts = shape_obj.geometry.verts
    if not verts:
        return None
    xs = verts[0::3]
    ys = verts[1::3]
    zs = verts[2::3]
    return BoundingBox(
        x_min=min(xs), x_max=max(xs),
        y_min=min(ys), y_max=max(ys),
        z_min=min(zs), z_max=max(zs),
    )

# FUNCTION TO EXTRACT SITE DETAILS FROM IFC FILE
def extract_site_details(ifc_path: Union[str, Path]) -> Site:
    if isinstance(ifc_path, str):
        ifc_path = Path(ifc_path)
    model = ifcopenshell.open(ifc_path)
    sites = model.by_type("IfcSite")
    if not sites:
        return Site(latitude=0.0, longitude=0.0, elevation=0.0)
    ifc_site = sites[0]
    # Convert DMS to decimal
    def dms_to_decimal(dms):
        return dms[0] + dms[1]/60 + dms[2]/3600
    lat = dms_to_decimal(getattr(ifc_site, "RefLatitude", (0, 0, 0)))
    lon = dms_to_decimal(getattr(ifc_site, "RefLongitude", (0, 0, 0)))
    elev = float(getattr(ifc_site, "RefElevation", 0.0) or 0.0)
    return Site(latitude=lat, longitude=lon, elevation=elev)

# FUNCTION TO create ROOM OBJECT FROM  IFC FILE
def parse_room(ifc_path: Union[str, Path], room_name: str) -> Site:
    '''This function builds and returns a Site object containing exactly one room in its .rooms dict'''
    if isinstance(ifc_path, str):
        ifc_path = Path(ifc_path)
    model = ifcopenshell.open(ifc_path)
    site = extract_site_details(ifc_path)
    spaces = model.by_type("IfcSpace")
    windows = model.by_type("IfcWindow")
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    target = room_name.strip().lower()

    for space in spaces:
        longn = (space.LongName or "").strip().lower()
        shortn = (space.Name or "").strip().lower()
        if longn == target or shortn == target:
            gid = space.GlobalId
            short_name = space.Name or ""
            long_name = space.LongName or ""
            props = ifcopenshell.util.element.get_psets(space)
            volume = props.get("BaseQuantities", {}).get("GrossVolume", 0)
            try:
                shape = ifcopenshell.geom.create_shape(settings, space)
                bbox = compute_bounding_box(shape)
            except Exception:
                bbox = None
            
            # Gather external windows in the room
            room_windows: list[Window] = []
            for w in windows:
                psets = ifcopenshell.util.element.get_psets(w).get("Pset_WindowCommon", {})
                if not psets.get("IsExternal", False):
                    continue
                try:
                    shape_w = ifcopenshell.geom.create_shape(settings, w)
                    wbbox = compute_bounding_box(shape_w)
                except Exception:
                    wbbox = None
                # Check if window inside room bbox
                if bbox and wbbox:
                    buf = 2
                    if (
                        wbbox.x_min >= bbox.x_min - buf and
                        wbbox.y_min >= bbox.y_min - buf and
                        wbbox.z_min >= bbox.z_min - buf and
                        wbbox.x_max <= bbox.x_max + buf and
                        wbbox.y_max <= bbox.y_max + buf and
                        wbbox.z_max <= bbox.z_max + buf
                    ):
                        bq = ifcopenshell.util.element.get_psets(w).get("BaseQuantities", {})
                        area = bq.get("Area", 0)
                        shgc = ifcopenshell.util.element.get_psets(w).get("Analytical Properties(Type)", {}).get("Solar Heat Gain Coefficient", 0)
                        room_windows.append(
                            Window(
                                global_id=w.GlobalId,
                                room_name=short_name,
                                bounding_box=wbbox,
                                area=area,
                                SHGC=shgc,
                                is_external=True,
                            )
                        )
            # Create the room object and add it to the site
            parsed = Room(
                global_id=gid,
                short_name=short_name,
                long_name=long_name,
                volume=volume,
                bounding_box=bbox,
                windows=room_windows or None
            )
            site.add_room(parsed, key=parsed.long_name)
            return site

    # Not found
    raise ValueError(f"No space named '{room_name}' found in IFC")
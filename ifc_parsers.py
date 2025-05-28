from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Union, Tuple, List, Dict
# external
import math
import numpy as np
import ifcopenshell
import ifcopenshell.geom
from ifcopenshell.util.element import get_psets

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
    tilt: Optional[float] = None
    azimuth: Optional[float] = None
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


def compute_average_normal(verts, faces):
    """
    verts: flat list [x0,y0,z0, x1,y1,z1, ...]
    faces: list of 3-int tuples (i0, i1, i2) indexing into verts//3
    """
    total = np.zeros(3)
    for (i0, i1, i2) in faces:
        v0 = np.array(verts[3*i0:3*i0+3])
        v1 = np.array(verts[3*i1:3*i1+3])
        v2 = np.array(verts[3*i2:3*i2+3])
        # triangle normal (unnormalized)
        n = np.cross(v1 - v0, v2 - v0)
        total += n  # weighted by n (area proportional)
    norm = np.linalg.norm(total)
    return (total / norm) if norm > 0 else np.array([0, 0, 1])

def normal_to_tilt_azimuth(n):
    """
    n: unit normal [nx, ny, nz]
    returns tilt (° from horizontal), azimuth (° clockwise from north)
    """
    tilt = math.degrees(math.acos(n[2]))
    raw = math.degrees(math.atan2(n[0], n[1]))
    az = raw if raw >= 0 else raw + 360.0
    return tilt, az

def compute_window_tilt_azimuth(window_entity, window_bbox: BoundingBox) -> tuple[float, float]:
    """
    Builds a mesh for the window_entity, computes its average *exterior* normal,
    and returns (tilt, azimuth) in degrees.
    """
    # 1) Build the mesh
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    shape = ifcopenshell.geom.create_shape(settings, window_entity)
    verts = shape.geometry.verts
    raw = shape.geometry.faces

    # 2) Unpack faces, compute per-face normals & centroids
    normals = []
    centroids = []
    i = 0
    while i < len(raw):
        count = raw[i]
        if count == 3:
            i0, i1, i2 = raw[i+1], raw[i+2], raw[i+3]
            v0 = np.array(verts[3*i0:3*i0+3])
            v1 = np.array(verts[3*i1:3*i1+3])
            v2 = np.array(verts[3*i2:3*i2+3])
            # unnormalized normal
            n = np.cross(v1 - v0, v2 - v0)
            # triangle centroid
            centroid = (v0 + v1 + v2) / 3
            normals.append(n)
            centroids.append(centroid)
            i += 4
        else:
            i += 1 + count

    # 3) Compute window center from bounding box
    center = np.array([
        (window_bbox.x_min + window_bbox.x_max) / 2,
        (window_bbox.y_min + window_bbox.y_max) / 2,
        (window_bbox.z_min + window_bbox.z_max) / 2,
    ])

    # 4) Average only *exterior*-facing normals
    total = np.zeros(3)
    for n, centroid in zip(normals, centroids):
        # if dot(n, (centroid - center)) > 0, normal points outside
        if np.dot(n, centroid - center) > 0:
            total += n

    # 5) Normalize & compute tilt/azimuth
    norm = np.linalg.norm(total)
    outward = (total / norm) if norm > 0 else np.array([0, 0, 1])
    tilt = math.degrees(math.acos(outward[2]))
    raw_az = math.degrees(math.atan2(outward[0], outward[1]))
    az = raw_az if raw_az >= 0 else raw_az + 360.0
    return tilt, az

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

# Iterate through spaces to find the one matching room_name
    for space in spaces:
        longn = (space.LongName or "").strip().lower()
        shortn = (space.Name or "").strip().lower()
        if longn == target or shortn == target:
            gid = space.GlobalId
            short_name = space.Name or ""
            long_name = space.LongName or ""
            props = get_psets(space)
            volume = props.get("BaseQuantities", {}).get("GrossVolume", 0)
            try:
                shape = ifcopenshell.geom.create_shape(settings, space)
                bbox = compute_bounding_box(shape)
            except Exception:
                bbox = None
            
            # Gather external windows in the room - 
            # with these attributes loaded/calculated - 
            # global_id, room's short name, bounding_box, area, SHGC, tilt, azimuth, is_external
            room_windows: list[Window] = []
            for w in windows:
                psets = get_psets(w).get("Pset_WindowCommon", {})
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
                        bq = get_psets(w).get("BaseQuantities", {})
                        area = bq.get("Area", 0)
                        shgc = get_psets(w).get("Analytical Properties(Type)", {}).get("Solar Heat Gain Coefficient", 0)

                        tilt_val, az_val = compute_window_tilt_azimuth(w, wbbox)
                        room_windows.append(
                            Window(
                                global_id=w.GlobalId,
                                room_name=short_name,
                                bounding_box=wbbox,
                                area=area,
                                SHGC=shgc,
                                solar_inflow=None,
                                tilt=tilt_val,
                                azimuth=az_val,
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

if __name__ == "__main__":
    ifc_path = 'static/IFC/BK_v2_vb_updated.ifc'
    room_name = 'BG.West.010'
    site = parse_room(ifc_path, room_name)
    room = site.rooms.get(room_name)
    if room:
        print(f"Room: {room.short_name}, Volume: {room.volume}, Windows: {len(room.windows or [])}")
    else:
        print(f"No room found with name '{room_name}'")
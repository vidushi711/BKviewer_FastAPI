from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Union
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

# --- NEW: placement/orientation helpers ---

def axis2placement3d_to_matrix(ax) -> np.ndarray:
    """IfcAxis2Placement3D → 4x4 matrix [X Y Z O]."""
    p = ax.Location.Coordinates if getattr(ax, "Location", None) else (0.0, 0.0, 0.0)
    px, py, pz = map(float, p)

    # Z axis (Axis)
    if getattr(ax, "Axis", None) and getattr(ax.Axis, "DirectionRatios", None):
        zx, zy, zz = (ax.Axis.DirectionRatios + (0.0, 0.0))[:3]
    else:
        zx, zy, zz = 0.0, 0.0, 1.0

    # X axis (RefDirection)
    if getattr(ax, "RefDirection", None) and getattr(ax.RefDirection, "DirectionRatios", None):
        xx, xy, xz = (ax.RefDirection.DirectionRatios + (0.0, 0.0))[:3]
    else:
        xx, xy, xz = 1.0, 0.0, 0.0

    Z = np.array([zx, zy, zz], float); Z /= (np.linalg.norm(Z) or 1.0)
    X = np.array([xx, xy, xz], float); X = X - Z * np.dot(X, Z); X /= (np.linalg.norm(X) or 1.0)
    Y = np.cross(Z, X)

    M = np.eye(4)
    M[0:3, 0] = X
    M[0:3, 1] = Y
    M[0:3, 2] = Z
    M[0:3, 3] = [px, py, pz]
    return M

def placement_chain_matrix(lp) -> np.ndarray:
    """IfcLocalPlacement chain → world 4x4 matrix."""
    M = np.eye(4); cur = lp
    while cur is not None:
        ax = getattr(cur, "RelativePlacement", None)
        if ax and ax.is_a("IfcAxis2Placement3D"):
            M = axis2placement3d_to_matrix(ax) @ M
        cur = getattr(cur, "PlacementRelTo", None)
    return M

def true_north_deg(model) -> float:
    """0°=North, 90°=East. Raises if missing (you asked to enforce TN)."""
    for ctx in model.by_type("IfcGeometricRepresentationContext"):
        tn = getattr(ctx, "TrueNorth", None)
        if tn and hasattr(tn, "DirectionRatios"):
            x, y = (tn.DirectionRatios + (0, 0))[:2]
            return (math.degrees(math.atan2(float(x), float(y))) % 360.0)
    raise ValueError("TrueNorth missing in IfcGeometricRepresentationContext")

# def compute_window_tilt_azimuth(window_entity, window_bbox: BoundingBox, yaw_deg: float) -> tuple[float, float]:
#     """
#     Builds a mesh for the window_entity, computes its average *exterior* normal,
#     rotates it by 'yaw_deg' (project → True North), then returns (tilt, azimuth_deg_from_true_north).
#     """
#     # 1) Build the mesh
#     settings = ifcopenshell.geom.settings()
#     settings.set(settings.USE_WORLD_COORDS, True)
#     shape = ifcopenshell.geom.create_shape(settings, window_entity)
#     verts = shape.geometry.verts
#     raw = shape.geometry.faces

#     # 2) Unpack faces, compute per-face normals & centroids
#     normals = []
#     centroids = []
#     i = 0
#     while i < len(raw):
#         count = raw[i]
#         if count == 3:
#             i0, i1, i2 = raw[i+1], raw[i+2], raw[i+3]
#             v0 = np.array(verts[3*i0:3*i0+3])
#             v1 = np.array(verts[3*i1:3*i1+3])
#             v2 = np.array(verts[3*i2:3*i2+3])
#             n = np.cross(v1 - v0, v2 - v0)          # unnormalized normal
#             centroid = (v0 + v1 + v2) / 3           # triangle centroid
#             normals.append(n)
#             centroids.append(centroid)
#             i += 4
#         else:
#             i += 1 + count

#     # 3) Window center from bbox
#     center = np.array([
#         (window_bbox.x_min + window_bbox.x_max) / 2,
#         (window_bbox.y_min + window_bbox.y_max) / 2,
#         (window_bbox.z_min + window_bbox.z_max) / 2,
#     ])

#     # 4) Average only exterior-facing normals
#     total = np.zeros(3)
#     for n, centroid in zip(normals, centroids):
#         if np.dot(n, centroid - center) > 0:
#             total += n

#     # 5) Normalize
#     norm = np.linalg.norm(total)
#     outward = (total / norm) if norm > 0 else np.array([0.0, 0.0, 1.0])

#     # 6) Rotate outward vector by georef yaw so azimuth is vs True North
#     rx, ry = rotate_xy_vec(float(outward[0]), float(outward[1]), yaw_deg)
#     rz = float(outward[2])

#     # 7) Tilt and azimuth (0°=North, 90°=East)
#     tilt = math.degrees(math.acos(max(-1.0, min(1.0, rz))))
#     raw_az = math.degrees(math.atan2(rx, ry))
#     az = raw_az if raw_az >= 0 else raw_az + 360.0
#     return tilt, az
def window_tilt_az_from_placement(win, tn_deg: float) -> tuple[float, float]:
    """
    Return (tilt_deg, azimuth_deg_trueN) for a window using its LocalPlacement.
    - Tilt: 0°=up, 90°=vertical.
    - Azimuth: clockwise from True North (0°=N, 90°=E).
    """
    lp = getattr(win, "ObjectPlacement", None)
    if not lp or not lp.is_a("IfcLocalPlacement"):
        # fallback
        return 90.0, 0.0

    M = placement_chain_matrix(lp)
    Y = M[0:3, 1].astype(float)
    Y /= (np.linalg.norm(Y) or 1.0)

    # project-space tilt/azimuth
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, Y[2]))))
    az_proj = math.degrees(math.atan2(Y[0], Y[1])) % 360.0  # 0°=+Y

    # correct by True North ONLY
    az_true = (az_proj - tn_deg) % 360.0
    return tilt, az_true

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
    
    # model = ifcopenshell.open(ifc_path)
    # site = extract_site_details(ifc_path)
    # # NEW: read georeferencing once
    # georef = get_georef_info(model)
    # yaw_deg = georef["yaw_deg"]
    # ----------rewritten part ----------
    model = ifcopenshell.open(ifc_path)
    site = extract_site_details(ifc_path)
    # Enforce True North (raises if missing)
    tn_deg = true_north_deg(model)

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

                        # tilt_val, az_val = compute_window_tilt_azimuth(w, wbbox, ya)
                        tilt_val, az_val = window_tilt_az_from_placement(w, tn_deg)
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
    ifc_path = 'static/IFC/BK_v6_ifc4_georef_transformed.ifc'
    room_name = 'BG.West.010'
    site = parse_room(ifc_path, room_name)
    room = site.rooms.get(room_name)
    if room:
        print(f"Room: {room.short_name}, Volume: {room.volume}, Windows: {len(room.windows or [])}")
    else:
        print(f"No room found with name '{room_name}'")
import json
from typing import List, Dict, Any
import Rhino.Geometry as rg

def _coords_to_geometry(coords: List[List[float]]):
    """Convert coords to Rhino Polyline (or Line if 2 points)."""
    
    if len(coords) == 2:
        p1 = rg.Point3d(coords[0][0], coords[0][1], 0.0)
        p2 = rg.Point3d(coords[1][0], coords[1][1], 0.0)
        return rg.Line(p1, p2)
    
    points = [rg.Point3d(c[0], c[1], 0.0) for c in coords]
    return rg.Polyline(points)


def schema_to_rhino_geometry(schema: Dict[str, Any]) -> Dict[str, Any]:
    """ Convert layout schema to Rhino geometry objects for Grasshopper. """
    
    if isinstance(schema, str):
        schema = json.loads(schema)
    
    result = {
        "outline": _coords_to_geometry(schema.get("outline", [])),
        "rooms": [],
        "programs": [],
        "doors": [],
        "facades": [],
        "circulation": []
    }
    
    # Rooms
    for room in schema.get("rooms", []):
        result["rooms"].append(_coords_to_geometry(room.get("geometry", [])))
        result["programs"].append(room.get("program", "unknown"))
    
    # Doors (points only)
    for door in schema.get("doors", []):
        door_coords = door.get("geometry", [[0, 0]])
        pt_coords = door_coords[0] if isinstance(door_coords[0], list) else door_coords
        result["doors"].append(rg.Point3d(pt_coords[0], pt_coords[1], 0.0))
    
    # Facades
    for facade in schema.get("facades", []):
        result["facades"].append(_coords_to_geometry(facade.get("geometry", [])))
    
    # Circulation
    for circ in schema.get("circulation", []):
        result["circulation"].append(_coords_to_geometry(circ.get("geometry", [])))
    
    return result

"""
geom = schema_to_rhino_geometry(schema)
outline = geom["outline"]
rooms = geom["rooms"]
programs = geom["programs"]
doors = geom["doors"]
facades = geom["facades"]
circulation = geom["circulation"]
"""

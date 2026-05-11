"""
Utility script for adding windows to a layout.
Designed to be used inside a Grasshopper Python component.

Inputs:
  - windows_curves: List of Rhino curve objects
  - layout_json_str: JSON string of the layout (from sample_layouts)
  
Output:
  - Updated layout JSON string with windows added (room ID and name auto-detected)
"""

import json
import math
from typing import List, Dict, Any, Tuple, Optional


def calculate_line_length(line: List[List[float]]) -> float:
    """Calculate the length of a line segment."""
    if len(line) < 2:
        return 0.0
    x1, y1 = line[0]
    x2, y2 = line[1]
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def extract_line_from_curve(curve: Any) -> Optional[List[List[float]]]:
    """
    Extract line geometry from a Rhino curve object.
    
    Args:
        curve: Rhino curve object with StartPoint and EndPoint properties
    
    Returns:
        Line as [[x1, y1], [x2, y2]] or None if extraction fails
    """
    try:
        start_pt = curve.PointAtStart
        end_pt = curve.PointAtEnd
        
        # Extract X, Y coordinates from Rhino point objects
        return [
            [start_pt.X, start_pt.Y],
            [end_pt.X, end_pt.Y]
        ]
    except (AttributeError, TypeError):
        return None


def point_in_polygon(point: Tuple[float, float], polygon: List[List[float]]) -> bool:
    """Check if a point is inside a polygon using ray casting algorithm."""
    x, y = point
    n = len(polygon)
    inside = False
    
    p1x, p1y = polygon[0]
    for i in range(1, n):
        p2x, p2y = polygon[i]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    
    return inside


def find_room_for_window(
    window_line: List[List[float]],
    layout: Dict[str, Any]
) -> Optional[Tuple[str, str]]:
    """
    Find which room a window belongs to by checking if the window endpoints
    are on the boundary or inside the room geometry.
    
    Returns:
        Tuple of (room_id, room_name) or None if room not found
    """
    rooms = layout.get("rooms", [])
    
    for room in rooms:
        room_geometry = room.get("geometry", [])
        if not room_geometry:
            continue
        
        # Check if window endpoints are inside or on boundary of room
        for endpoint in window_line[:2]:
            if point_in_polygon(tuple(endpoint), room_geometry):
                return (room["id"], room["name"])
    
    return None


def add_windows_to_layout(
    windows_curves: List[Any],
    layout_json_str: str
) -> str:
    """
    Add windows to a layout from Rhino curves, automatically detecting which room each belongs to.
    
    Args:
        windows_curves: List of Rhino curve objects
        layout_json_str: JSON string of the layout dictionary to modify
    
    Returns:
        Updated layout as JSON string with windows added to the windows array
    """
    # Parse the JSON string
    layout = json.loads(layout_json_str)
    
    if "windows" not in layout:
        layout["windows"] = []
    
    # Get the next window ID number
    existing_windows = layout.get("windows", [])
    next_window_num = len(existing_windows) + 1
    
    print("DEBUG: Starting add_windows_to_layout")
    print("DEBUG: Number of input curves: {}".format(len(windows_curves)))
    print("DEBUG: Number of rooms in layout: {}".format(len(layout.get("rooms", []))))
    
    windows_added = 0
    
    # Add each window
    for i, curve in enumerate(windows_curves):
        print("DEBUG: Processing curve {}".format(i))
        
        # Extract line geometry from Rhino curve
        line = extract_line_from_curve(curve)
        print("DEBUG: Extracted line: {}".format(line))
        
        if not line:
            print("DEBUG: Failed to extract line from curve")
            continue
        
        # Find which room this window belongs to
        room_info = find_room_for_window(line, layout)
        print("DEBUG: Room info: {}".format(room_info))
        
        if not room_info:
            print("DEBUG: No room found for this window")
            continue
        
        room_id, room_name = room_info
        window_id = f"window-{next_window_num + i}"
        width = calculate_line_length(line)
        window_name = f"{room_name} Window"
        
        print("DEBUG: Adding window {} to room {}".format(window_id, room_id))
        
        window = {
            "id": window_id,
            "name": window_name,
            "geometry": line,
            "attributes": {
                "roomId": room_id,
                "width": width
            }
        }
        layout["windows"].append(window)
        windows_added += 1
    
    print("DEBUG: Total windows added: {}".format(windows_added))
    
    # Return updated layout as JSON string
    return json.dumps(layout, indent=2)

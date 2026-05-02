"""
Layout Filter Tool.

Smart layout selector for local Python tool interface.
The function checks which parameter is not empty and uses that one.
Priority: layout_id > apartment_area > description_search

Returns dicts for direct Python function calls.
"""

import json

# ---------------------------------------------------------------------------
# Load JSON from string for backward compatibility with old state format
# ---------------------------------------------------------------------------
def load_json_from_string(json_string):
    try:
        data = json.loads(json_string)
    except Exception as e:
        raise ValueError(f"Invalid JSON string: {e}")
    return data

# ---------------------------------------------------------------------------
# Select layout by checking which input parameter is not empty/None.
# Priority: layout_id > apartment_area > description_search
# Returns dict with matching layout or error dict
# ---------------------------------------------------------------------------
def select_layout(all_layouts, layout_id=None, apartment_area=None, description_search=None):
    # Handle if all_layouts is a string (for backward compatibility)
    if isinstance(all_layouts, str):
        layouts_list = load_json_from_string(all_layouts)
    else:
        layouts_list = all_layouts
    
    try:
        # Check which parameter is not empty and use it
        if layout_id:  # Check if not None and not empty string
            result = _search_by_layout_id(layouts_list, layout_id)
        elif apartment_area:  # Check if not None and not 0
            result = _search_by_area(layouts_list, apartment_area)
        elif description_search:  # Check if not None and not empty string
            result = _search_by_description(layouts_list, description_search)
        else:
            # All inputs empty
            result = None
        
        # Return dict directly
        if result is None:
            return {"error": "No layout found matching criteria"}
        return result
    
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Search by layoutId (exact match)
# ---------------------------------------------------------------------------
def _search_by_layout_id(layouts_list, layout_id):
    for layout in layouts_list:
        if isinstance(layout, str):
            try:
                layout = json.loads(layout)
            except:
                continue
        
        if layout.get("layoutId") == layout_id:
            return layout
    
    return None


# ---------------------------------------------------------------------------
# Search by apartment area (approximate match within 0.5)
# ---------------------------------------------------------------------------
def _search_by_area(layouts_list, apartment_area):
    for layout in layouts_list:
        if isinstance(layout, str):
            try:
                layout = json.loads(layout)
            except:
                continue
        
        apt_area = layout.get("apartment", {}).get("attributes", {}).get("area")
        if apt_area and abs(apt_area - apartment_area) < 0.5:
            return layout
    
    return None


# ---------------------------------------------------------------------------
# Search by description substring (case-insensitive)
# ---------------------------------------------------------------------------
def _search_by_description(layouts_list, description_search):
    for layout in layouts_list:
        if isinstance(layout, str):
            try:
                layout = json.loads(layout)
            except:
                continue
        
        apt_name = layout.get("description", "")
        if description_search.lower() in apt_name.lower():
            return layout
    
    return None


# ---------------------------------------------------------------------------
# Print all layouts to debug what values exist.
# Useful for seeing what layoutIds, names, and areas are available.
# ---------------------------------------------------------------------------
def debug_layouts(layouts_list):
    try:
        print("=== Available Layouts ===")
        for i, layout in enumerate(layouts_list):
            if isinstance(layout, str):
                try:
                    layout = json.loads(layout)
                except:
                    print(f"[{i}] Error parsing")
                    continue
            
            layout_id = layout.get("layoutId", "?")
            apt_name = layout.get("apartment", {}).get("name", "?")
            apt_area = layout.get("apartment", {}).get("attributes", {}).get("area", "?")
            
            print(f"[{i}] layoutId='{layout_id}' | name='{apt_name}' | area={apt_area}")
    
    except Exception as e:
        print(f"Error: {e}")
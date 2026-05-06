"""Convert layout schema to NetworkX graph representation."""

import networkx as nx


def create_graph_from_layout(layout: dict) -> nx.Graph:
    """Create a NetworkX graph from a layout JSON object.
    
    Nodes are rooms (with name, program attributes).
    Edges are doors connecting them.
    """
    graph = nx.Graph()
    
    # Add all rooms as nodes
    for room in layout['rooms']:
        graph.add_node(room['id'], name=room['name'], program=room['program'])
    
    # Add edges based on door connections
    for door in layout['doors']:
        connected_rooms = door['attributes']['connectsRooms']
        
        # A door can connect 2 or more rooms
        # Create edges between all pairs of connected rooms
        for i in range(len(connected_rooms)):
            for j in range(i + 1, len(connected_rooms)):
                graph.add_edge(connected_rooms[i], connected_rooms[j], door_id=door['id'])
    
    return graph


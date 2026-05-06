# This script reads the sample_layouts.json file, creates a graph representation of the rooms and their connections, and visualizes it using NetworkX and Matplotlib.

#Matplotlib need to be installed to run the code below

import json
import networkx as nx
import matplotlib.pyplot as plt

# Load the JSON file
with open('team_06/layout_inputs/sample_layouts.json', 'r') as f:
    layouts = json.load(f)

# Function to create a graph from a layout
def create_graph_from_layout(layout):
    """
    Create a NetworkX graph from a layout JSON object
    Nodes are rooms, edges are doors connecting them
    """
    G = nx.Graph()
    
    # Add all rooms as nodes
    for room in layout['rooms']:
        G.add_node(room['id'], name=room['name'], program=room['program'], area=room['attributes']['area'])
    
    # Add edges based on door connections
    for door in layout['doors']:
        connected_rooms = door['attributes']['connectsRooms']
        
        # A door can connect 2 or more rooms
        # Create edges between all pairs of connected rooms
        for i in range(len(connected_rooms)):
            for j in range(i + 1, len(connected_rooms)):
                G.add_edge(connected_rooms[i], connected_rooms[j], door_id=door['id'])
    
    return G

# Example: Create graphs for the first layout
layout = layouts[1]
G = create_graph_from_layout(layout)

# Print graph info
print(f"Layout: {layout['apartment']['name']}")
print(f"Nodes: {list(G.nodes())}")
print(f"Edges: {list(G.edges())}")
print(f"Number of nodes: {G.number_of_nodes()}")
print(f"Number of edges: {G.number_of_edges()}")

# Visualize
plt.figure(figsize=(10, 8))
pos = nx.spring_layout(G, seed=42)

# Color nodes by room type
node_colors = []
color_map = {
    'bed': 'lightblue',
    'bath': 'lightcoral',
    'kitchen': 'lightgreen',
    'living': 'lightyellow',
    'foyer': 'lightgray',
    'extra': 'plum'
}

for node in G.nodes():
    program = G.nodes[node]['program']
    node_colors.append(color_map.get(program, 'lightgray')) # Default color if program type is not in the color map

nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=1500)
nx.draw_networkx_labels(G, pos, labels={node: G.nodes[node]['name'] for node in G.nodes()}, font_size=8)
nx.draw_networkx_edges(G, pos, width=2)
plt.title(f"Room Graph: {layout['apartment']['name']}")
plt.axis('off')
plt.tight_layout()
plt.show()
"""Graph-based layout search using NetworkX.

Unified topology search: build pattern graphs and match via graph similarity.
"""

import json
from pathlib import Path
import networkx as nx

# Import graph builders
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.schema_to_graph import create_graph_from_layout, build_topology_graph

# ============================================================================
# GraphSearcher class: loads layout graphs and provides search methods.
# ============================================================================
class GraphSearcher:
    # --------- Loading and initialization
    def __init__(self, graphs_path: str):

        self.graphs_path = graphs_path
        self.layout_graphs = self._load_graphs()
    
    # --------- Private methods
    def _load_graphs(self) -> dict:

        with open(self.graphs_path, 'r') as f:
            graphs_data = json.load(f)
        
        # Convert node-link format back to NetworkX graphs
        layout_graphs = {}
        for layout_id, node_link_data in graphs_data.items():
            layout_graphs[layout_id] = nx.node_link_graph(node_link_data)
        
        return layout_graphs

    def search_by_graph_similarity(self, pattern_graph: nx.Graph, method: str = "jaccard") -> list:
        results = []
        
        # Extract pattern structure: required program counts and edges
        pattern_programs = {}
        for node in pattern_graph.nodes():
            program = pattern_graph.nodes[node].get('program', '')
            pattern_programs[program] = pattern_programs.get(program, 0) + 1
        
        pattern_edges = set()
        for u, v in pattern_graph.edges():
            # Get programs for each node in pattern
            prog_u = pattern_graph.nodes[u].get('program', '')
            prog_v = pattern_graph.nodes[v].get('program', '')
            edge = tuple(sorted([prog_u, prog_v]))
            pattern_edges.add(edge)
        
        for layout_id, G in self.layout_graphs.items():
            # Get available programs in layout
            available_programs = {}
            for node in G.nodes():
                program = G.nodes[node].get('program', '')
                available_programs[program] = available_programs.get(program, 0) + 1
            
            # Check if layout has required program counts
            if not all(available_programs.get(prog, 0) >= count 
                      for prog, count in pattern_programs.items()):
                continue
            
            # Get layout edges between required programs
            layout_edges = set()
            for u, v in G.edges():
                prog_u = G.nodes[u].get('program', '')
                prog_v = G.nodes[v].get('program', '')
                # Only count edges between programs we care about
                if prog_u in pattern_programs and prog_v in pattern_programs:
                    edge = tuple(sorted([prog_u, prog_v]))
                    layout_edges.add(edge)
            
            # Calculate primary similarity based on pattern edges
            if method == "jaccard":
                # Jaccard: intersection / union
                union_size = len(pattern_edges | layout_edges)
                if union_size > 0:
                    similarity = len(pattern_edges & layout_edges) / union_size
                else:
                    similarity = 0.0
            
            elif method == "overlap":
                # Overlap: intersection / min
                min_size = min(len(pattern_edges), len(layout_edges)) or 1
                similarity = len(pattern_edges & layout_edges) / min_size
            
            else:
                similarity = 0.0
            
            # Tiebreaker: connectivity quality (higher = more interconnected subgraph)
            # Count how many pattern program types have edges within pattern set
            required_prog_nodes = [node for node in G.nodes() 
                                  if G.nodes[node].get('program', '') in pattern_programs]
            if len(required_prog_nodes) > 1:
                subgraph = G.subgraph(required_prog_nodes)
                # Density of the required rooms subgraph (0-1, higher = more connected)
                tiebreaker = nx.density(subgraph)
            else:
                tiebreaker = 0.0
            
            results.append((layout_id, similarity, tiebreaker))
        
        # Sort by similarity first, then by connectivity tiebreaker
        results.sort(key=lambda x: (x[1], x[2]), reverse=True)
        
        # Return as (layout_id, similarity) pairs for compatibility
        return [(layout_id, similarity) for layout_id, similarity, _ in results]
    
    # --------- Utility methods
    # Get layout info for a specific layout ID
    def get_layout_info(self, layout_id: str) -> nx.Graph:
        
        return self.layout_graphs.get(layout_id)
    
    # --------- Statistics
    # Get network statistics for a layout
    def get_graph_stats(self, layout_id: str) -> dict:
        G = self.layout_graphs.get(layout_id)
        if G is None:
            return None
        
        # Count rooms by program
        program_counts = {}
        for node in G.nodes():
            program = G.nodes[node].get('program', '')
            program_counts[program] = program_counts.get(program, 0) + 1
        
        return {
            "layout_id": layout_id,
            "num_rooms": G.number_of_nodes(),
            "num_connections": G.number_of_edges(),
            "room_programs": program_counts,
            "is_connected": nx.is_connected(G),
            "density": nx.density(G),
            "clustering_coefficient": sum(nx.clustering(G).values()) / G.number_of_nodes() if G.number_of_nodes() > 0 else 0,
            "degree_sequence": {G.nodes[node].get('name', node): G.degree(node) for node in G.nodes()}
        }

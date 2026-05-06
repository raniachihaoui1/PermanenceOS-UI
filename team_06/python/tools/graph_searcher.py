"""Graph-based layout search using NetworkX.

Simple topology search: graph similarity and room program matching.
"""

import json
from pathlib import Path
import networkx as nx

# Import graph builder
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.schema_to_graph import create_graph_from_layout


class GraphSearcher:
    """Search layouts using graph topology comparison."""
    
    def __init__(self, layouts_path: str):
        """
        Initialize with layouts data.
        
        Args:
            layouts_path: Path to sample_layouts.json
        """
        self.layouts_path = layouts_path
        self.layouts = self._load_layouts()
        self.layout_graphs = {}
        self._build_networkx_graphs()
    
    def _load_layouts(self) -> list:
        """Load all layouts from JSON."""
        with open(self.layouts_path, 'r') as f:
            return json.load(f)
    
    def _build_networkx_graphs(self) -> None:
        """Build NetworkX graphs from layout schemas."""
        for layout_idx, layout_data in enumerate(self.layouts, 1):
            layout_id = f"layout-{layout_idx}"
            # Build graph from schema
            G = create_graph_from_layout(layout_data)
            
            self.layout_graphs[layout_id] = {
                'graph': G,
                'data': layout_data
            }

    
    def search_by_graph_similarity(self, pattern_graph: nx.Graph, method: str = "jaccard") -> list:
        """
        Search for layouts similar to a given pattern graph.
        
        Args:
            pattern_graph: Reference NetworkX graph
            method: Similarity metric ('jaccard' or 'overlap')
        
        Returns:
            List of (layout_id, similarity_score) tuples
        """
        results = []
        
        # Convert pattern graph to edge set
        pattern_edges = set()
        for u, v in pattern_graph.edges():
            edge = tuple(sorted([u, v]))
            pattern_edges.add(edge)
        
        for layout_id, layout_info in self.layout_graphs.items():
            G = layout_info['graph']
            
            # Convert to edge set
            layout_edges = set()
            for u, v in G.edges():
                edge = tuple(sorted([u, v]))
                layout_edges.add(edge)
            
            # Calculate similarity
            if method == "jaccard":
                # Jaccard similarity: intersection / union
                union_size = len(pattern_edges | layout_edges)
                if union_size > 0:
                    similarity = len(pattern_edges & layout_edges) / union_size
                else:
                    similarity = 0.0
            
            elif method == "overlap":
                # Overlap coefficient: intersection / min size
                min_size = min(len(pattern_edges), len(layout_edges)) or 1
                similarity = len(pattern_edges & layout_edges) / min_size
            
            else:
                similarity = 0.0
            
            results.append((layout_id, similarity))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    
    def search_by_room_program(self, required_programs: list, min_match: int = None) -> list:
        """
        Search for layouts with specific room types.
        
        Args:
            required_programs: List of room programs needed
                              e.g., ['bed', 'kitchen', 'living']
            min_match: Minimum number to match (default: all)
        
        Returns:
            List of (layout_id, num_matched) tuples
        """
        if min_match is None:
            min_match = len(required_programs)
        
        results = []
        
        for layout_id, layout_info in self.layout_graphs.items():
            rooms = layout_info['data']['rooms']
            available_programs = {room['program'] for room in rooms}
            
            # Count matches
            matches = sum(1 for prog in required_programs if prog in available_programs)
            
            if matches >= min_match:
                results.append((layout_id, matches))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    
    def get_layout_info(self, layout_id: str) -> dict:
        """Get layout schema data for a specific layout ID."""
        if layout_id in self.layout_graphs:
            return self.layout_graphs[layout_id]['data']
        return None
    
    def get_graph_stats(self, layout_id: str) -> dict:
        """Get network statistics for a layout."""
        if layout_id not in self.layout_graphs:
            return None
        
        G = self.layout_graphs[layout_id]['graph']
        
        return {
            "layout_id": layout_id,
            "num_rooms": G.number_of_nodes(),
            "num_doors": G.number_of_edges(),
            "is_connected": nx.is_connected(G),
            "density": nx.density(G),
            "clustering_coefficient": sum(nx.clustering(G).values()) / G.number_of_nodes() if G.number_of_nodes() > 0 else 0,
            "degree_sequence": {G.nodes[node].get('name', node): G.degree(node) for node in G.nodes()}
        }


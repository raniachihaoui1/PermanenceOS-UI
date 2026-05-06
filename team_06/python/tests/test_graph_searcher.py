#!/usr/bin/env python3
"""Quick test of GraphSearcher integration."""

from tools.graph_searcher import GraphSearcher
from pathlib import Path

# Test path resolution
graphs_path = Path(__file__).resolve().parent.parent / "layout_inputs" / "sample_graphs.json"
print(f"Using path: {graphs_path}")
print(f"Exists: {graphs_path.exists()}")

if graphs_path.exists():
    gs = GraphSearcher(str(graphs_path))
    print("\n✓ GraphSearcher loaded successfully")
    print(f"Loaded graphs: {list(gs.layout_graphs.keys())}")
    
    # Test a search
    stats = gs.get_graph_stats('layout-1')
    print(f"\nLayout-1 stats: {stats}")
    
    # Test search by degree
    results = gs.search_by_room_program(['bed', 'kitchen', 'living'])
    print(f"\nRooms with bed+kitchen+living: {results}")
else:
    print(f"ERROR: File not found at {graphs_path}")

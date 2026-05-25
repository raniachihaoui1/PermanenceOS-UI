"""
intelligent_grid.py — Layout-aware structural grid generator.

Extracts the algorithm from tag_and_audit.py and exposes it as a single
callable function.  No file I/O.  No matplotlib.  Falls back to an empty
list if shapely / networkx are not installed.
"""
from __future__ import annotations

import math
import string
import itertools
from itertools import product as iproduct
from typing import Any


# ── Public API ────────────────────────────────────────────────────────────────

def generate_layout_aware_grid(
    layout: dict[str, Any],
    max_options: int = 6,
) -> list[list[dict[str, Any]]]:
    """Return up to *max_options* candidate structure arrays for *layout*.

    Each returned item is a list of column/beam element dicts that can be
    assigned directly to ``layout["structure"]``.  Returns an empty list when
    the layout has no rooms, or when shapely / networkx are unavailable.
    """
    try:
        from shapely.geometry import LineString, Point, MultiLineString
        from shapely.geometry import Polygon as ShapelyPolygon
        from shapely.ops import linemerge, unary_union
        import networkx as nx
    except ImportError:
        return []

    rooms   = layout.get("rooms", [])
    outline = layout.get("outline", [])
    if not rooms or len(outline) < 3:
        return []

    # ── Constants (same as tag_and_audit.py) ──────────────────────────────────
    TOLERANCE         = 0.01
    MIN_GAP           = 2.5
    MIN_GAP_GRID      = 1.49
    MAX_GAP           = 5.0
    TOO_CLOSE         = 1.5
    MID_PROXIMITY     = 1.0
    MIN_CHAIN_LEN     = 4.0
    MAX_BEAM_FOR_COL  = 2.2
    MIN_DIST_PROTECTED = 1.5
    protected_room_names = ["bedroom", "living"]

    def key(pt):
        return (round(pt[0], 3), round(pt[1], 3))

    # ── Outline + candidate columns ────────────────────────────────────────────
    outline_ls   = LineString(outline)
    outline_poly = ShapelyPolygon(outline)

    all_points: set = set()
    for room in rooms:
        for pt in room.get("geometry", [])[:-1]:
            all_points.add(key(pt))

    unique_x = sorted(set(pt[0] for pt in all_points))
    unique_y = sorted(set(pt[1] for pt in all_points))

    candidate_columns = []
    for x in unique_x:
        for y in unique_y:
            pt = Point(x, y)
            if outline_poly.contains(pt) or outline_poly.boundary.distance(pt) < TOLERANCE:
                candidate_columns.append((x, y))

    if not candidate_columns:
        return []

    # ── Column classification ──────────────────────────────────────────────────
    room_corners = set(
        key(pt) for room in rooms for pt in room.get("geometry", [])[:-1]
    )
    wall_segments = []
    for room in rooms:
        pts = room.get("geometry", [])[:-1]
        for i in range(len(pts)):
            wall_segments.append(LineString([pts[i], pts[(i + 1) % len(pts)]]))

    outline_pts = outline[:-1]

    def is_corner(p_prev, p_curr, p_next):
        d1 = (p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
        d2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
        return abs(d1[0] * d2[1] - d1[1] * d2[0]) > TOLERANCE

    perimeter_corner_cols    = []
    collinear_perimeter_cols = []
    wall_corner_cols         = []
    wall_floating_cols       = []

    for pt in candidate_columns:
        p           = Point(pt)
        on_boundary = outline_poly.boundary.distance(p) < TOLERANCE
        is_rc       = pt in room_corners
        on_wall     = any(seg.distance(p) < TOLERANCE for seg in wall_segments)

        if on_boundary:
            matches = [
                i for i, op in enumerate(outline_pts)
                if abs(op[0] - pt[0]) < TOLERANCE and abs(op[1] - pt[1]) < TOLERANCE
            ]
            classified = False
            for i in matches:
                p_prev = outline_pts[(i - 1) % len(outline_pts)]
                p_curr = outline_pts[i]
                p_next = outline_pts[(i + 1) % len(outline_pts)]
                if key(p_prev) == key(p_curr) or key(p_next) == key(p_curr):
                    continue
                if is_corner(p_prev, p_curr, p_next):
                    perimeter_corner_cols.append(pt)
                    classified = True
                    break
            if not classified and is_rc:
                collinear_perimeter_cols.append(pt)
        else:
            if is_rc:
                wall_corner_cols.append(pt)
            elif on_wall:
                wall_floating_cols.append(pt)

    all_pts = list(
        set(perimeter_corner_cols) | set(collinear_perimeter_cols)
        | set(wall_corner_cols)    | set(wall_floating_cols)
    )
    if not all_pts:
        return []

    # ── Primal graph ───────────────────────────────────────────────────────────
    def safe_add_edge(G, a, b):
        mid = LineString([a, b]).interpolate(0.5, normalized=True)
        if outline_poly.contains(mid) or outline_poly.boundary.distance(mid) < TOLERANCE:
            G.add_edge(a, b)

    G_primal = nx.Graph()
    for pt in all_pts:
        G_primal.add_node(pt)

    for pt in all_pts:
        same_x = sorted([n for n in all_pts if abs(n[0] - pt[0]) < TOLERANCE and n != pt],
                         key=lambda n: n[1])
        idx = next((i for i, n in enumerate(same_x) if n[1] > pt[1]), None)
        if idx is not None:
            safe_add_edge(G_primal, pt, same_x[idx])
        if idx is not None and idx > 0:
            safe_add_edge(G_primal, pt, same_x[idx - 1])
        elif idx is None and same_x:
            safe_add_edge(G_primal, pt, same_x[-1])

        same_y = sorted([n for n in all_pts if abs(n[1] - pt[1]) < TOLERANCE and n != pt],
                         key=lambda n: n[0])
        idx = next((i for i, n in enumerate(same_y) if n[0] > pt[0]), None)
        if idx is not None:
            safe_add_edge(G_primal, pt, same_y[idx])
        if idx is not None and idx > 0:
            safe_add_edge(G_primal, pt, same_y[idx - 1])
        elif idx is None and same_y:
            safe_add_edge(G_primal, pt, same_y[-1])

    # ── Edge classification ────────────────────────────────────────────────────
    room_wall_segments_ls = []
    for room in rooms:
        pts = room.get("geometry", [])[:-1]
        for i in range(len(pts)):
            room_wall_segments_ls.append(LineString([pts[i], pts[(i + 1) % len(pts)]]))

    def is_on_perimeter(a, b):
        mid = LineString([a, b]).interpolate(0.5, normalized=True)
        return outline_poly.boundary.distance(mid) < TOLERANCE

    def is_on_room_wall(a, b):
        mid = LineString([a, b]).interpolate(0.5, normalized=True)
        return any(w.distance(mid) < TOLERANCE for w in room_wall_segments_ls)

    perimeter_edges  = []
    room_wall_edges  = []
    grid_edges_list  = []

    for u, v in G_primal.edges():
        if is_on_perimeter(u, v):
            perimeter_edges.append((u, v))
        elif is_on_room_wall(u, v):
            room_wall_edges.append((u, v))
        else:
            grid_edges_list.append((u, v))

    perimeter_nodes     = set(perimeter_corner_cols) | set(collinear_perimeter_cols)
    perimeter_only_edges = [
        (u, v) for u, v in G_primal.edges()
        if u in perimeter_nodes and v in perimeter_nodes
    ]
    base_perimeter_edges = list(perimeter_only_edges)
    base_wall_edges      = list(room_wall_edges)

    edge_types: dict = {}
    for u, v in G_primal.edges():
        ek = tuple(sorted([u, v]))
        if is_on_perimeter(u, v):
            edge_types[ek] = "perimeter"
        elif is_on_room_wall(u, v):
            edge_types[ek] = "wall"
        else:
            edge_types[ek] = "grid"

    perimeter_edge_dict = {ek: ek for ek, t in edge_types.items() if t == "perimeter"}
    grid_edge_dict      = {ek: ek for ek, t in edge_types.items() if t == "grid"}

    # ── Helpers ────────────────────────────────────────────────────────────────
    def edge_direction(u, v):
        return "h" if abs(u[1] - v[1]) < TOLERANCE else "v"

    def edge_midpoint(u, v):
        return ((u[0] + v[0]) / 2, (u[1] + v[1]) / 2)

    def get_axis_val(u, v, direction):
        return round(u[1], 3) if direction == "h" else round(u[0], 3)

    def ray_cast_distance(edge, direction, ref_edges, sign):
        u, v   = edge
        mid    = edge_midpoint(u, v)
        midx, midy = mid
        axis_val = get_axis_val(u, v, direction)
        hits = []
        for fu, fv in ref_edges:
            fd   = edge_direction(fu, fv)
            if fd != direction:
                continue
            fval = get_axis_val(fu, fv, direction)
            if sign > 0 and fval <= axis_val:
                continue
            if sign < 0 and fval >= axis_val:
                continue
            if direction == "h":
                if min(fu[0], fv[0]) <= midx <= max(fu[0], fv[0]):
                    hits.append(abs(fval - axis_val))
            else:
                if min(fu[1], fv[1]) <= midy <= max(fu[1], fv[1]):
                    hits.append(abs(fval - axis_val))
        return min(hits) if hits else float("inf")

    def is_collinear_to_perimeter(edge, peri_edges):
        u, v = edge
        d, val = edge_direction(u, v), get_axis_val(u, v, edge_direction(u, v))
        for pu, pv in peri_edges:
            if edge_direction(pu, pv) == d and abs(get_axis_val(pu, pv, d) - val) < TOLERANCE:
                return True
        return False

    def chain_length(edge, all_wall):
        u, v = edge
        d    = edge_direction(u, v)
        val  = get_axis_val(u, v, d)
        same = [
            LineString([eu, ev]) for eu, ev in all_wall
            if edge_direction(eu, ev) == d and abs(get_axis_val(eu, ev, d) - val) < TOLERANCE
        ]
        if not same:
            return LineString([u, v]).length
        if len(same) == 1:
            return same[0].length
        merged = linemerge(unary_union(MultiLineString(same)))
        if merged.geom_type == "LineString":
            return merged.length
        mid = Point(edge_midpoint(u, v))
        for geom in merged.geoms:
            if geom.distance(mid) < TOLERANCE:
                return geom.length
        return LineString([u, v]).length

    def build_graph(edges):
        G = nx.Graph()
        for u, v in edges:
            G.add_edge(u, v)
        return G

    def find_open_ends(edges):
        G = build_graph(edges)
        return [n for n in G.nodes() if G.degree(n) == 1]

    def node_touches_edge(node, edge):
        u, v = edge
        return (round(u[0], 3), round(u[1], 3)) == node or (round(v[0], 3), round(v[1], 3)) == node

    # ── Wall culling ───────────────────────────────────────────────────────────
    wall_edges_list = list(room_wall_edges)
    fixed_wall, candidate_wall = [], []
    for edge in wall_edges_list:
        if is_collinear_to_perimeter(edge, base_perimeter_edges):
            fixed_wall.append(edge)
        elif chain_length(edge, wall_edges_list) >= MIN_CHAIN_LEN:
            fixed_wall.append(edge)
        else:
            candidate_wall.append(edge)

    ref_edges_wall = base_perimeter_edges + wall_edges_list
    ray_results_w: dict = {}
    for i, edge in enumerate(candidate_wall):
        d = edge_direction(*edge)
        dn = ray_cast_distance(edge, d, ref_edges_wall, -1)
        dp = ray_cast_distance(edge, d, ref_edges_wall, +1)
        ray_results_w[i] = (dn, dp, dn > MIN_GAP and dp > MIN_GAP)

    initial_culled = {i for i, r in ray_results_w.items() if not r[2]}
    recheck_ref = base_perimeter_edges + fixed_wall + [
        e for i, e in enumerate(candidate_wall) if i not in initial_culled
    ]
    final_wall_keep: dict = {}
    for i, edge in enumerate(candidate_wall):
        if i in initial_culled:
            final_wall_keep[i] = False
            continue
        d  = edge_direction(*edge)
        dn = ray_cast_distance(edge, d, recheck_ref, -1)
        dp = ray_cast_distance(edge, d, recheck_ref, +1)
        final_wall_keep[i] = dn > MIN_GAP and dp > MIN_GAP

    kept_candidates = [e for i, e in enumerate(candidate_wall) if final_wall_keep.get(i, False)]
    culled_wall     = [e for i, e in enumerate(candidate_wall) if not final_wall_keep.get(i, False)]
    base_wall       = fixed_wall + kept_candidates

    all_peri_wall = base_perimeter_edges + base_wall
    open_ends     = find_open_ends(all_peri_wall)

    open_end_fixes: dict = {}
    for node in open_ends:
        fixers = [e for e in culled_wall if node_touches_edge(node, e)]
        if fixers:
            open_end_fixes[node] = fixers

    all_opt_groups_wall: list = []
    all_forced_wall:     list = []
    for node, fixers in open_end_fixes.items():
        if len(fixers) == 1:
            all_forced_wall.append(fixers[0])
        else:
            all_opt_groups_wall.append(fixers)

    def build_wall_layout(choices={}):
        extra = list(all_forced_wall)
        for gi, group in enumerate(all_opt_groups_wall):
            extra.append(choices.get(gi, group[0]))
        return base_wall + extra

    if all_opt_groups_wall:
        combos       = list(itertools.islice(iproduct(*all_opt_groups_wall), 5))
        wall_options = [build_wall_layout({i: c[i] for i in range(len(all_opt_groups_wall))})
                        for c in combos]
    else:
        wall_options = [build_wall_layout()]

    final_perimeter_edges = {tuple(sorted(e)): e for e in base_perimeter_edges}
    final_grid_edges      = dict(grid_edge_dict)

    # ── Open corner fix ────────────────────────────────────────────────────────
    perimeter_node_set_oc: set = set()
    for u, v in base_perimeter_edges:
        perimeter_node_set_oc.add((round(u[0], 3), round(u[1], 3)))
        perimeter_node_set_oc.add((round(v[0], 3), round(v[1], 3)))

    def find_open_corners(edges, pns):
        G = build_graph(edges)
        corners = []
        for node in G.nodes():
            if node in pns:
                continue
            if G.degree(node) != 2:
                continue
            nbrs = list(G.neighbors(node))
            if edge_direction(node, nbrs[0]) != edge_direction(node, nbrs[1]):
                corners.append(node)
        return corners

    final_wall_options: list = []
    for wall_opt in wall_options:
        all_edges_opt = base_perimeter_edges + wall_opt
        corners       = find_open_corners(all_edges_opt, perimeter_node_set_oc)
        in_use        = set(tuple(sorted(e)) for e in all_edges_opt)

        corner_opt_groups: list = []
        corner_forced:     list = []
        for node in corners:
            touching = []
            for edge in base_wall_edges:
                u, v = edge
                un = (round(u[0], 3), round(u[1], 3))
                vn = (round(v[0], 3), round(v[1], 3))
                if un == node or vn == node:
                    touching.append((un, vn))
            not_in_use = [e for e in touching if tuple(sorted(e)) not in in_use]
            if not not_in_use:
                continue
            if len(not_in_use) == 1:
                corner_forced.append(not_in_use[0])
            else:
                corner_opt_groups.append(not_in_use)

        def build_fixed(base_w, forced, choices={}):
            extra = list(forced)
            for gi, group in enumerate(corner_opt_groups):
                extra.append(choices.get(gi, group[0]))
            return base_w + extra

        if corner_opt_groups:
            combos   = list(itertools.islice(iproduct(*corner_opt_groups), 5))
            expanded = [
                build_fixed(wall_opt, corner_forced, {i: c[i] for i in range(len(corner_opt_groups))})
                for c in combos
            ]
        else:
            expanded = [build_fixed(wall_opt, corner_forced)]
        final_wall_options.extend(expanded)

    seen_keys: list = []
    unique_opts:  list = []
    for opt in final_wall_options:
        k = frozenset(tuple(sorted(e)) for e in opt)
        if k not in seen_keys:
            seen_keys.append(k)
            unique_opts.append(opt)
    wall_options = unique_opts

    # ── Grid culling ───────────────────────────────────────────────────────────
    def mid_group_val(u, v, direction):
        mid = edge_midpoint(u, v)
        return mid[0] if direction == "h" else mid[1]

    def group_by_mid_proximity(edge_ids, edges_by_id, direction, tolerance):
        sorted_ids = sorted(edge_ids, key=lambda eid: mid_group_val(*edges_by_id[eid], direction))
        clusters: list = []
        for eid in sorted_ids:
            u, v = edges_by_id[eid]
            mv   = mid_group_val(u, v, direction)
            placed = False
            for cluster in clusters:
                for cid in cluster:
                    if abs(mv - mid_group_val(*edges_by_id[cid], direction)) <= tolerance:
                        cluster.append(eid)
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                clusters.append([eid])
        return clusters

    def has_collinear_fixed(edge, direction, fixed_e):
        u, v = edge
        val  = get_axis_val(u, v, direction)
        for fu, fv in fixed_e:
            if edge_direction(fu, fv) == direction and abs(get_axis_val(fu, fv, direction) - val) < TOLERANCE:
                return True
        return False

    def cull_dangling(grid, all_edges_g):
        culled:  set  = set()
        changed = True
        while changed:
            changed = False
            active  = [e for e in grid if tuple(sorted(e)) not in culled]
            G       = nx.Graph()
            for u, v in all_edges_g:
                G.add_edge(u, v)
            for u, v in active:
                if tuple(sorted([u, v])) in culled:
                    continue
                if G.degree(u) == 1 or G.degree(v) == 1:
                    culled.add(tuple(sorted([u, v])))
                    changed = True
        return [e for e in grid if tuple(sorted(e)) not in culled]

    def cull_grid_direction(edge_ids, edge_id_map, direction, fixed_e):
        if not edge_ids:
            return set(), []
        cull_ids:  set  = set()
        opt_groups: list = []
        clusters = group_by_mid_proximity(edge_ids, edge_id_map, direction, MID_PROXIMITY)
        for cluster in clusters:
            ray_res: dict = {}
            for eid in cluster:
                e  = edge_id_map[eid]
                dn = ray_cast_distance(e, direction, fixed_e, -1)
                dp = ray_cast_distance(e, direction, fixed_e, +1)
                ray_res[eid] = (dn, dp, dn > MIN_GAP_GRID and dp > MIN_GAP_GRID)
            ray_candidates = [eid for eid in cluster if ray_res[eid][2]]
            for eid in cluster:
                if not ray_res[eid][2]:
                    cull_ids.add(eid)
            col_candidates = [eid for eid in ray_candidates
                              if has_collinear_fixed(edge_id_map[eid], direction, fixed_e)]
            for eid in ray_candidates:
                if eid not in col_candidates:
                    cull_ids.add(eid)
            if not col_candidates:
                continue
            col_sorted = sorted(col_candidates, key=lambda eid: get_axis_val(*edge_id_map[eid], direction))
            cand_clusters: list = []
            for eid in col_sorted:
                val    = get_axis_val(*edge_id_map[eid], direction)
                placed = False
                for cc in cand_clusters:
                    for ceid in cc:
                        if abs(val - get_axis_val(*edge_id_map[ceid], direction)) < TOO_CLOSE:
                            cc.append(eid)
                            placed = True
                            break
                    if placed:
                        break
                if not placed:
                    cand_clusters.append([eid])
            for cc in cand_clusters:
                if len(cc) == 1:
                    continue
                vals = [get_axis_val(*edge_id_map[eid], direction) for eid in cc]
                span = max(vals) - min(vals)
                if span < MAX_GAP:
                    opt_groups.append(cc)
                else:
                    for eid in cc:
                        if eid not in [col_sorted[0], col_sorted[1]]:
                            cull_ids.add(eid)
                    opt_groups.append([col_sorted[0], col_sorted[1]])
        return cull_ids, opt_groups

    def run_grid_culling(wall_opt):
        fixed_w  = list(final_perimeter_edges.values()) + wall_opt
        all_w    = fixed_w + list(final_grid_edges.values())
        active   = cull_dangling(list(final_grid_edges.values()), all_w)
        id_map   = {i: e for i, e in enumerate(active)}
        h_ids    = [i for i, e in id_map.items() if edge_direction(*e) == "h"]
        v_ids    = [i for i, e in id_map.items() if edge_direction(*e) == "v"]
        h_cull, h_opts = cull_grid_direction(h_ids, id_map, "h", fixed_w)
        v_cull, v_opts = cull_grid_direction(v_ids, id_map, "v", fixed_w)
        all_cull = h_cull | v_cull
        all_opts = h_opts + v_opts

        def build_grid(choices={}):
            kept: list = []
            for eid, e in id_map.items():
                if eid in all_cull:
                    continue
                in_group = False
                for gi, group in enumerate(all_opts):
                    if eid in group:
                        in_group = True
                        if eid == choices.get(gi, group[0]):
                            kept.append(e)
                        break
                if not in_group:
                    kept.append(e)
            return kept

        if all_opts:
            combos = list(itertools.islice(iproduct(*[g for g in all_opts]), 5))
            return [build_grid({i: c[i] for i in range(len(all_opts))}) for c in combos]
        return [build_grid({})]

    # ── Combine wall × grid options ────────────────────────────────────────────
    all_layout_options: list = []
    for wall_idx, wall_opt in enumerate(wall_options):
        for grid_idx, grid_opt in enumerate(run_grid_culling(wall_opt)):
            all_layout_options.append((wall_idx, grid_idx, wall_opt, grid_opt))
            if len(all_layout_options) >= max_options * 3:
                break
        if len(all_layout_options) >= max_options * 3:
            break

    # ── Column culling + beam/column finalisation ──────────────────────────────
    perimeter_node_set: set = set()
    for u, v in final_perimeter_edges.values():
        perimeter_node_set.add((round(u[0], 3), round(u[1], 3)))
        perimeter_node_set.add((round(v[0], 3), round(v[1], 3)))

    protected_nodes: set = set()
    for room in rooms:
        if any(pn in room.get("name", "").lower() for pn in protected_room_names):
            for pt in room.get("geometry", [])[:-1]:
                protected_nodes.add((round(pt[0], 3), round(pt[1], 3)))

    anchor_nodes = perimeter_node_set | protected_nodes

    def is_collinear_deg2(node, G):
        if G.degree(node) != 2:
            return False
        nbrs = list(G.neighbors(node))
        n1, n2 = nbrs[0], nbrs[1]
        return (abs(n1[0] - node[0]) < TOLERANCE and abs(n2[0] - node[0]) < TOLERANCE) or \
               (abs(n1[1] - node[1]) < TOLERANCE and abs(n2[1] - node[1]) < TOLERANCE)

    def merge_through_node(node, G):
        nbrs = list(G.neighbors(node))
        return (nbrs[0], nbrs[1])

    # ── Naming ─────────────────────────────────────────────────────────────────
    all_col_nodes_set: set = set()

    # Pre-compute naming across all layouts so IDs are stable
    raw_final: list = []
    for wall_idx, grid_idx, wall_opt, grid_opt in all_layout_options:
        final_kept = list(final_perimeter_edges.values()) + wall_opt + grid_opt
        G_final = nx.Graph()
        for u, v in final_kept:
            G_final.add_edge(
                (round(u[0], 3), round(u[1], 3)),
                (round(v[0], 3), round(v[1], 3)),
            )
        cull_nodes: set = set()
        for node in G_final.nodes():
            if node in set(perimeter_corner_cols):
                continue
            if is_collinear_deg2(node, G_final):
                cull_nodes.add(node)

        cleaned: set = set()
        for u, v in G_final.edges():
            if u in cull_nodes or v in cull_nodes:
                continue
            cleaned.add(tuple(sorted([u, v])))

        for node in cull_nodes:
            u, v = merge_through_node(node, G_final)
            while u in cull_nodes:
                nbrs = list(G_final.neighbors(u))
                u = nbrs[0] if nbrs[1] == node else nbrs[1]
            while v in cull_nodes:
                nbrs = list(G_final.neighbors(v))
                v = nbrs[0] if nbrs[1] == node else nbrs[1]
            if u != v:
                cleaned.add(tuple(sorted([u, v])))

        G_clean = nx.Graph()
        for u, v in cleaned:
            G_clean.add_edge(u, v)

        col_cull: set = set()
        for node in G_clean.nodes():
            if node in perimeter_node_set:
                continue
            if node in protected_nodes:
                continue
            if G_clean.degree(node) >= 4:
                continue
            nbrs = list(G_clean.neighbors(node))
            if max(math.dist(node, nb) for nb in nbrs) >= MAX_BEAM_FOR_COL:
                continue
            if min(math.dist(node, a) for a in anchor_nodes) >= MIN_DIST_PROTECTED:
                continue
            col_cull.add(node)

        final_column_nodes = set(G_clean.nodes()) - col_cull
        all_col_nodes_set |= final_column_nodes
        raw_final.append({
            "beam_edges":   list(cleaned),
            "columns":      final_column_nodes,
            "culled_cols":  col_cull,
        })

    if not all_col_nodes_set:
        return []

    all_x_vals = sorted(set(round(pt[0], 3) for pt in all_col_nodes_set))
    all_y_vals = sorted(set(round(pt[1], 3) for pt in all_col_nodes_set))

    def get_letter(idx):
        letters = string.ascii_uppercase
        if idx < 26:
            return letters[idx]
        return letters[idx // 26 - 1] + letters[idx % 26]

    x_label = {x: get_letter(i) for i, x in enumerate(all_x_vals)}
    y_label = {y: str(i + 1) for i, y in enumerate(all_y_vals)}

    def get_col_name(pt):
        x = round(pt[0], 3)
        y = round(pt[1], 3)
        return f"{x_label.get(x, '?')}{y_label.get(y, '?')}"

    # ── Pick first unique base layout ──────────────────────────────────────────
    seen_sigs: set = set()
    base_ld = None
    for ld in raw_final:
        sig = frozenset(tuple(sorted([round(p[0],3), round(p[1],3)])) for p in ld["columns"])
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            base_ld = ld
            break
    if base_ld is None:
        return []

    base_cols  = base_ld["columns"]
    base_beams = base_ld["beam_edges"]

    # ── Helper: build a structure array from columns + beam edge list ──────────
    def _to_structure(
        columns: Any,
        beam_edges: Any,
        name_fn: Any = None,
    ) -> list[dict[str, Any]]:
        if name_fn is None:
            name_fn = get_col_name
        s: list[dict[str, Any]] = []
        for pt in sorted(set(tuple(p) for p in columns)):
            col_type = "perimeter" if pt in perimeter_node_set else "internal"
            cn = name_fn(pt)
            s.append({
                "id": cn, "name": f"Col_{cn}",
                "geometry": [[pt[0], pt[1]]],
                "attributes": {
                    "type": col_type, "dimensions": "200x200", "height": "3.5",
                    "isWallAligned": "true", "structuralRole": "primary",
                    "material": "RCC", "conflict": "None",
                },
            })
        seen_b: set = set()
        for edge in beam_edges:
            u, v = edge[0], edge[1]
            bk = tuple(sorted([tuple(u), tuple(v)]))
            if bk in seen_b:
                continue
            seen_b.add(bk)
            bu, bv = bk
            bn = f"{name_fn(bu)}-{name_fn(bv)}"
            bt = "perimeter" if (bu in perimeter_node_set and bv in perimeter_node_set) else "internal"
            bl = round(math.dist(bu, bv), 3)
            s.append({
                "id": bn, "name": f"Beam_{bn}",
                "geometry": [[bu[0], bu[1]], [bv[0], bv[1]]],
                "attributes": {
                    "type": bt, "length": bl,
                    "depth": "300", "width": "200",
                    "isWallAligned": "true", "structuralRole": "primary",
                    "material": "RCC", "conflict": "None", "section": None,
                },
            })
        return s

    # ── Balanced: base topology as-is ─────────────────────────────────────────
    balanced = _to_structure(base_cols, base_beams)

    # ── Conservative: add midspan columns on beams longer than SPLIT_THR ──────
    SPLIT_THR = 3.2  # m — split beams longer than this

    def _make_conservative() -> list[dict[str, Any]]:
        extra_cols: dict = {}  # mid_pt -> name
        col_set = set(tuple(p) for p in base_cols)
        new_beams: list = []

        for edge in base_beams:
            u, v = tuple(edge[0]), tuple(edge[1])
            length = math.dist(u, v)
            if length <= SPLIT_THR:
                new_beams.append((u, v))
                continue
            mid = (round((u[0] + v[0]) / 2, 3), round((u[1] + v[1]) / 2, 3))
            if mid not in col_set and mid not in extra_cols:
                bu_n = get_col_name(u)
                bv_n = get_col_name(v)
                extra_cols[mid] = f"{bu_n}m{bv_n}"
            new_beams.append((u, mid))
            new_beams.append((mid, v))

        if not extra_cols:
            return []  # nothing to add — Conservative = Balanced

        def name_ext(pt):
            t = tuple(pt)
            if t in extra_cols:
                return extra_cols[t]
            return get_col_name(pt)

        all_cols = list(col_set) + list(extra_cols.keys())
        return _to_structure(all_cols, new_beams, name_fn=name_ext)

    # ── Open: merge near-duplicate columns (within MERGE_DIST) + cull short beams
    MERGE_DIST = 0.65  # m — pairs closer than this are consolidated into one

    def _make_open() -> list[dict[str, Any]] | None:
        import networkx as nx_o
        G = nx_o.Graph()
        col_list = [tuple(p) for p in base_cols]
        for pt in col_list:
            G.add_node(pt)
        for edge in base_beams:
            G.add_edge(tuple(edge[0]), tuple(edge[1]))

        # Build merge map: removed_col -> kept_col
        merge_map: dict = {}
        processed: set = set()
        for i, a in enumerate(col_list):
            if a in processed:
                continue
            for b in col_list[i + 1:]:
                if b in processed:
                    continue
                if math.dist(a, b) > MERGE_DIST:
                    continue
                # Keep whichever has higher degree; prefer perimeter on tie
                da, db = G.degree(a), G.degree(b)
                if da > db or (da == db and a in perimeter_node_set):
                    keep, drop = a, b
                else:
                    keep, drop = b, a
                merge_map[drop] = keep
                processed.add(drop)
                break  # each column merges into at most one other

        if not merge_map:
            return None

        def resolve(pt):
            while pt in merge_map:
                pt = merge_map[pt]
            return pt

        new_cols_set: set = set()
        for pt in col_list:
            new_cols_set.add(resolve(pt))

        new_beams_set: set = set()
        for edge in base_beams:
            u = resolve(tuple(edge[0]))
            v = resolve(tuple(edge[1]))
            if u == v:
                continue  # zero-length beam after merge — drop it
            new_beams_set.add(tuple(sorted([u, v])))

        if len(new_cols_set) == len(col_list):
            return None  # no change

        return _to_structure(list(new_cols_set), [list(e) for e in new_beams_set])

    conservative = _make_conservative()
    open_grid    = _make_open()

    # ── Assemble final result list ─────────────────────────────────────────────
    result: list[list[dict[str, Any]]] = []

    if conservative:
        result.append(conservative)
    result.append(balanced)
    if open_grid and len(open_grid) != len(balanced):
        result.append(open_grid)

    if not result:
        return [balanced]

    return result[:max_options]

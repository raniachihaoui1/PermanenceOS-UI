# Structural Design Agent — Summary

## What it is

A conversational structural design agent for early architectural decision-making. The architect types a plain-language instruction — "add a structural grid", "what if we remove column C_2", "evaluate the layout" — and the agent reasons about consequences, runs structural calculations, modifies the layout if needed, and returns a written response with a full evaluation table.

It is built on LangGraph, connects to a Grasshopper MCP server for geometry tools, and uses an LLM only for reasoning and communication — all structural mathematics is computed directly in Python, not by the model.

---

## Pipeline

The agent runs as a directed graph with four nodes:

```
CLI prompt --> bootstrap() --> run_agent()
                                    |
               +-------- reason --------+
               |    LLM decides:        |
               |  answer OR call tool   |
               +------------------------+
                        | tool called?
         YES --> modify --> evaluate --> comparison --> reason (max 2 cycles)
         NO  -->            evaluate --> reason --> END
```

**Reason** — the LLM reads the current layout summary and tool catalog. It decides whether to answer directly or call a tool (e.g. `tag_and_audit` to generate a structural grid). It never invents geometry — it works only with element IDs and attributes that exist in the JSON.

**Modify** — if a tool was called, this node sends the call to the Grasshopper MCP server, receives the updated layout JSON, and saves it to disk. If GH returns empty (e.g. canvas not running), a Python fallback generates the column grid directly from the layout outline. The original layout is snapshotted here so a diff can be computed later.

**Evaluate** — the structural calculation node. No LLM. Runs first-principles checks on every beam and column in the layout. Includes human-in-the-loop material selection, section upgrade offers, per-element upgrade options, midspan column insertion, and an alternatives menu on failure.

**Comparison** — runs only after a modify cycle. Computes a diff of what changed (added, removed, modified elements) and asks the LLM to summarise it in plain language. Increments a cycle counter — the graph allows a maximum of two modify cycles before ending.

The routing logic: if the reason node decides to call a tool and fewer than two cycles have run, the graph goes reason → modify → evaluate → comparison → reason. If no tool is called, it goes reason → evaluate → reason → end. Evaluate always runs exactly once per prompt.

---

## Human-in-the-Loop Interactions

The evaluate node presents three interactive prompts to the architect:

### 1. Material selection (always, first pass only)

```
Material (current: RCC):
  1. RCC    — beam 200x300mm | col 200x200mm  <-- active
  2. STEEL  — beam 82x160mm  | col 100x100mm
  3. TIMBER — beam 100x240mm | col 100x100mm
  [Enter] — keep current
Choice [1/2/3 or RCC/STEEL/TIMBER]:
```

### 2. Global section upgrade (on FAIL, loops through all tiers)

```
Structural FAIL with STEEL. Upgrade to STEEL M (beam 100x200mm | col 120x120mm)?
Upgrade? [y/N]:
```

### 3. Alternatives menu (on any remaining FAIL)

The alternatives are computed from the actual failure data — no LLM, no hallucinated IDs. Options appear in this order:

1. **Per-element section upgrade** — upgrade only the specific failing beam or column to the next IPE/RCC/Timber tier (e.g. "Upgrade CD_1 from IPE160 to IPE200")
2. **Midspan column** — split a failing beam at its midpoint and insert a new column (e.g. "Add midspan column under beam CD_1 (span 6.0m → 3.0m each side)")
3. **Per-element material switch** — switch a single element to a different material (e.g. "Switch CD_1 to RCC")
4. **Global tier upgrade** — upgrade all elements to the next material tier
5. **Free text** — type any custom instruction, passed to the reason node

All three programmatic options (per-element upgrade, midspan column, material switch) are handled inline in Python — no LLM call, no tool call. The layout JSON is updated and re-evaluated immediately in the same session.

For what-if removal failures the alternatives are geometry-specific:

```
Structural issues detected. Choose an action:
  1. Add intermediate column at midpoint of AB_1 (span 4.0m → 2.0m each side)
  2. Replace AB_1 with a deeper section to carry 8.0m span (S=310.2 > 165.0 MPa)
  3. Add a transfer beam to redirect load path around A_1
  [Enter or text] — describe a custom change
Choice:
```

---

## First Principles Structural Calculations

"First principles" means the agent does not look up pre-computed tables or use empirical rules of thumb. It derives every result from fundamental physics and mechanics equations applied directly to the geometry of each element.

### Loads

Every beam and column accumulates load from the floor area it supports. The agent calculates tributary widths for beams (half the distance to the nearest parallel beam in each direction) and tributary areas for columns (a Voronoi-like partition of the column grid). From these areas it assembles:

- **Self-weight** — material density x cross-section area x span
- **Superimposed dead load** — 3.5 kN/m² (125mm slab + finishes + partitions, IS 875)
- **Live load** — 2.0 kN/m² (residential, IS 875 Part 2)

### Beam checks

Each beam is treated as a simply supported member with a uniform distributed load. Four checks are run:

**Bending stress** — the maximum bending moment at mid-span is M = wL²/8. The bending stress is S = M / Wy, where Wy is the section modulus. For RCC and Timber, Wy = b·d²/6 from the solid rectangular section. For Steel, Wy is read directly from the IPE section property table (e.g. IPE 160: Wy = 108,700 mm³). The result is compared against the material's allowable bending stress.

**Shear stress** — the maximum shear at the support is V = wL/2. Average shear stress T = V/A. Compared against allowable shear.

**Live-load deflection** — d_LL = 5·w_LL·L⁴ / (384·E·I). Limit is L/360.

**Total-load deflection** — d_TL = 5·w_tot·L⁴ / (384·E·I). Limit is L/250.

The elastic modulus E and moment of inertia I are material- and section-specific. For steel, I comes from the IPE lookup table (not b·d³/12), which gives the true stiffness of the I-section web and flanges rather than an overestimate from a solid block.

### Column checks

**Compressive stress** — axial load P = floor load from tributary area + column self-weight. Direct stress S = P/A, compared against allowable compressive stress.

**Euler buckling** — the critical buckling load is P_cr = pi²·E·I_min / Le², where Le = 0.65H is the effective length for a fixed-pinned condition (standard for reinforced concrete and steel frames). The safety factor SF = P_cr / P must exceed 3.0. For steel HSS columns, I_min and the radius of gyration r are taken from the section property table.

### What-if simulation

When the prompt mentions removing a column, the agent re-evaluates all beams whose endpoint columns are being removed. It traces the beam chain from the floating endpoint through the removed positions until it reaches the nearest remaining column — this gives an effective span that may be much longer than the original. It then re-runs the bending, shear, and deflection checks at the extended span and reports which beams fail and by how much.

---

## Material System

Three materials are available, each calibrated to Indian Standards:

| Material | E (MPa)  | Allow. bending | Allow. compression | Allow. shear | Standard        |
|----------|----------|----------------|--------------------|--------------|-----------------|
| RCC      | 25,000   | 8.5 MPa        | 6.0 MPa            | 2.8 MPa      | IS 456, M25     |
| Steel    | 200,000  | 165 MPa        | 150 MPa            | 100 MPa      | IS 800, Fe250   |
| Timber   | 12,500   | 12.0 MPa       | 8.0 MPa            | 1.5 MPa      | IS 883, Group B |

Each material has three section tiers (base, M, L). If a check fails, the agent loops through the upgrade tiers automatically. For steel, all three tiers use actual IPE beam and HSS column section properties rather than solid rectangle approximations.

### Steel section properties

| Profile  | A (mm²) | I (mm⁴)      | Wy (mm³) |
|----------|---------|--------------|----------|
| IPE 160  | 2,009   | 8.69 x 10⁶  | 108,700  |
| IPE 200  | 2,848   | 19.43 x 10⁶ | 194,300  |
| IPE 240  | 3,912   | 38.92 x 10⁶ | 324,300  |

| Profile       | A (mm²) | I_min (mm⁴)  | r_min (mm) |
|---------------|---------|--------------|------------|
| HSS 100x100x6 | 2,256   | 3.61 x 10⁶  | 40.0       |
| HSS 120x120x6 | 2,736   | 6.39 x 10⁶  | 48.3       |
| HSS 150x150x6 | 3,456   | 12.69 x 10⁶ | 60.6       |

### Section tiers

```
Base tier:
  RCC    — beam 200x300mm   | col 200x200mm
  STEEL  — beam IPE 160     | col HSS 100x100x6
  TIMBER — beam 100x240mm   | col 100x100mm

_M tier (upgrade on FAIL):
  RCC_M    — beam 250x450mm   | col 250x250mm
  STEEL_M  — beam IPE 200     | col HSS 120x120x6
  TIMBER_M — beam 120x300mm   | col 120x120mm

_L tier (upgrade if _M still FAILs):
  RCC_L    — beam 300x600mm   | col 300x300mm
  STEEL_L  — beam IPE 240     | col HSS 150x150x6
  TIMBER_L — beam 150x360mm   | col 150x150mm
```

---

## LLM Reasoning Rules

The reason node uses a structured system prompt that separates three distinct cases:

### What-if removal (two-step)
Step 1: User asks "what if we remove X" → LLM sets `action="final"`, `final_response=""`. Evaluate runs the simulation automatically.
Step 2: Evaluate appends a "STRUCTURAL FAIL after removing…" message → LLM reads the actual span, beam IDs, and stress values from that message and writes a three-option response (intermediate column / deeper section / transfer beam).

### Regular structural failure
When the conversation contains "User instruction after structural failure" + "Structural evaluation (first principles)": LLM reads the failing beam/column IDs directly from the evaluation text and writes failure-type-specific options.
**Critical rule: LLM must never invent element IDs. Use only IDs present in the evaluation.**

### General questions / modifications
General questions (what rooms exist, what conflicts exist, what is permanent) → answered directly from layout JSON.
Modifications (add grid, confirmed change) → tool call with typology="column_grid" and grid_spacing=4.0 by default.
What-if questions → never call a tool.

---

## Code Summary

### Files not modified (read-only)

| File | Role |
|------|------|
| `_runtime/bootstrap.py` | Connects MCP server, loads LLM, sets file paths |
| `_runtime/llm.py` | LLM wrapper, enforces JSON response format |
| `_runtime/mcp_client.py` | HTTP client to Grasshopper MCP server |
| `_runtime/config.py` | Reads .env settings |
| `main.py` | CLI entry point — unchanged |
| `nodes/tools.py` | Legacy tool executor (not wired into graph) |

### Files modified or created

| File | Lines (approx) | Status | Key role |
|------|----------------|--------|----------|
| `graph.py` | ~200 | Modified | AgentState, routing logic, Unicode-safe output, material persistence |
| `nodes/reason.py` | ~125 | Modified | SYSTEM_PROMPT with what-if + regular-fail + tag_and_audit defaults |
| `nodes/evaluate.py` | ~900 | New file | All structural intelligence (see breakdown below) |
| `nodes/comparison.py` | ~88 | New file | Layout diff + LLM plain-language summary |
| `nodes/modify.py` | ~130 | New file | MCP tool call, Python grid fallback, layout save, original snapshot |

### Changes by session

#### evaluate.py
- Added `BEAM_SECTION_UPGRADE` — per-element Steel IPE upgrade chain (IPE160 → IPE200 → IPE240)
- Added `COL_SECTION_UPGRADE` — per-element HSS upgrade chain
- Added `BEAM_DIM_UPGRADE` — per-element RCC/Timber beam dimension upgrade chain
- Added `COL_DIM_UPGRADE` — per-element RCC/Timber column dimension upgrade chain
- Added `_upgrade_element_section(layout_str, element_id, new_section)` — upgrades a single element's section in JSON without touching others
- Added `_add_midspan_column(layout_str, beam_id, material)` — splits a beam at its midpoint, inserts a new column, creates two half-beams
- Added `_switch_element_material(layout_str, element_id, new_material)` — changes one element's material + resets section dims
- Updated `_build_failure_alternatives` — per-element options appear first (upgrade specific beam/col, midspan column, material switch), then global upgrade
- Updated failure while loop — handles Upgrade / Add midspan / Switch patterns inline in Python, re-evaluates immediately, loops

#### modify.py
- Added `_generate_column_grid(layout_json_str, grid_spacing)` — Python fallback that generates a full column grid (columns + horizontal + vertical beams) from the layout outline when GH returns empty
- Added empty output guard: if `tag_and_audit` returns empty, runs `_generate_column_grid` instead of leaving the layout unchanged
- Truncated tool result print to 200 chars to keep logs readable

#### reason.py
- Updated TAG_AND_AUDIT TOOL rules: always pass `typology="column_grid"` and `grid_spacing=4.0` unless user specifies otherwise

#### graph.py
- Unicode replacements in `_format_evaluation`: S (was σ), d (was δ), T (was τ) — avoids ASCII encoding errors in terminal
- Material persistence in `run_agent`: reads from `final_state["layout_json_string"]` (carries per-element upgrades) rather than from disk
- Preserves per-element upgraded sections: skips global material write for elements whose section differs from the global tier default
- Clears stale `"section"` attribute for non-steel materials (prevents `"section": "HSS150x150x6"` appearing on Timber elements)

### evaluate.py breakdown

| Section | Purpose |
|---------|---------|
| `MATERIALS` | RCC / Steel / Timber allowable stresses and E values |
| `STEEL_BEAM_PROPS` / `STEEL_COL_PROPS` | Real IPE and HSS section property lookup tables |
| `DEFAULT_SECTIONS` / `SECTION_UPGRADE_MAP` | 9 material tiers, global upgrade chain |
| `BEAM_SECTION_UPGRADE` / `COL_SECTION_UPGRADE` | Per-element Steel IPE / HSS upgrade chains |
| `BEAM_DIM_UPGRADE` / `COL_DIM_UPGRADE` | Per-element RCC / Timber dimension upgrade chains |
| `_beam_trib_widths` | Half-spacing tributary width geometry |
| `_column_trib_areas` | Voronoi-like tributary area per column |
| `_check_beams` | Bending, shear, LL deflection, TL deflection per beam |
| `_check_columns` | Compressive stress + Euler buckling per column |
| `_extract_removal_ids` | Regex extraction of removal intent from user message |
| `simulate_what_if_removal` | Beam chain trace + re-check at extended span |
| `evaluate_structure` | Public API — assembles full result dict |
| `_apply_material_override` | Patches all structure elements with chosen material + section |
| `_upgrade_element_section` | Single-element section upgrade (Steel IPE, RCC dims, Timber dims) |
| `_add_midspan_column` | Splits beam at midpoint, inserts column, creates two half-beams |
| `_switch_element_material` | Changes one element's material + section to a different material |
| `_build_failure_alternatives` | Computes numbered alternatives menu from actual failure data |
| `build_evaluate_node` | Full evaluate node: material picker → upgrade loop → eval → alternatives menu |

---

## Example prompts

```
python main.py "add a structural grid to layout-1-large"
python main.py "evaluate the structural layout"
python main.py "what if we remove column C_2"
python main.py "what if we remove column B_3"
python main.py "what structural conflicts exist in the layout"
```

At evaluate material picker: type `1` (RCC), `2` (STEEL), `3` (TIMBER), or press Enter to keep current.
At alternatives menu: type a number or free text; `Upgrade CD_1 from IPE160 to IPE200`, `Add midspan column under beam CD_1`, `Switch CD_1 to STEEL` are all handled inline.

Valid column IDs after tag_and_audit on layout-1-large: A_1 through D_4 (rows A-D, positions 1-4).

---

## GH / MCP notes

- GH file: `team_01/gh/team_01_working.gh` — must be open and running in Rhino for `tag_and_audit` to return geometry
- If GH returns empty, `modify.py` falls back to Python grid generation automatically — the rest of the pipeline (evaluate → comparison) still runs normally
- The `tag_and_audit` tool requires `typology` and `grid_spacing`; the reason node now always supplies these defaults
- Other MCP tools (`delete_room_01`, `add_window_01`, `classify_element_permanence`) still require GH

---

## Design principles

1. **LLM for language, Python for numbers.** The LLM never calculates — it reads results produced by deterministic code and writes plain-language responses.

2. **No hallucinated IDs.** The reason prompt explicitly forbids inventing element IDs. The alternatives menu in evaluate.py uses only IDs from the actual failure data.

3. **Human in the loop at every decision point.** Material selection, section upgrades, and failure responses are all interactive menus — the architect chooses, the agent executes.

4. **Per-element control.** The architect can upgrade, switch material, or add a midspan column to a specific failing element without affecting the rest of the structure.

5. **Material persists across modify cycles.** The chosen material tier is stored in AgentState and written back to the layout JSON after the entire graph completes, preserving per-element upgrades.

6. **GH fallback.** If Grasshopper is not running or returns empty output, the Python grid generator produces a valid column grid so the full evaluate → comparison pipeline still runs.

7. **_runtime/ is read-only.** All intelligence is in the five writable files. The bootstrap, LLM wrapper, MCP client, and CLI entry point are unchanged.

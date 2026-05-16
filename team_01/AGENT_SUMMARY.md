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

**Modify** — if a tool was called, this node sends the call to the Grasshopper MCP server, receives the updated layout JSON, and saves it to disk. The original layout is snapshotted here so a diff can be computed later.

**Evaluate** — the structural calculation node. No LLM. Runs first-principles checks on every beam and column in the layout. Includes human-in-the-loop material selection, section upgrade offers, and an alternatives menu on failure. Described in full below.

**Comparison** — runs only after a modify cycle. Computes a diff of what changed (added, removed, modified elements) and asks the LLM to summarise it in plain language. Increments a cycle counter — the graph allows a maximum of two modify cycles before ending.

The routing logic: if the reason node decides to call a tool and fewer than two cycles have run, the graph goes reason → modify → evaluate → comparison → reason. If no tool is called, it goes reason → evaluate → reason → end. Evaluate always runs exactly once per prompt.

---

## Human-in-the-Loop Interactions

The evaluate node presents three interactive prompts to the architect:

### 1. Material selection (always, first pass only)

```
Material (current: RCC):
  1. RCC    — beam 200×300mm | col 200×200mm  <-- active
  2. STEEL  — beam 82×160mm  | col 100×100mm
  3. TIMBER — beam 100×240mm | col 100×100mm
  [Enter] — keep current
Choice [1/2/3 or RCC/STEEL/TIMBER]:
```

### 2. Section upgrade (on FAIL, loops through all tiers)

```
Structural FAIL with STEEL. Upgrade to STEEL M (beam 100×200mm | col 120×120mm)?
Upgrade? [y/N]:
```

If still failing after STEEL_M:

```
Structural FAIL with STEEL_M. Upgrade to STEEL L (beam 120×240mm | col 150×150mm)?
Upgrade? [y/N]:
```

### 3. Alternatives menu (on any remaining FAIL)

The alternatives are computed from the actual failure data — no LLM, no hallucinated IDs. Each option names the exact beam or column that failed and the actual values:

```
Structural issues detected. Choose an action:
  1. Upgrade section to STEEL_M (beam 100×200mm | col 120×120mm)
  2. Add midspan column under beam CD_1 (span 6.0m → 3.0m, δ=24.5mm > 24.0mm)
  3. Increase depth of beam CD_1 (σ=172.3 > 165.0 MPa, span 6.0m)
  [Enter or text] — describe a custom change
Choice:
```

For what-if removal failures the alternatives are geometry-specific:

```
Structural issues detected. Choose an action:
  1. Add intermediate column at midpoint of AB_1 (span 4.0m → 2.0m each side)
  2. Replace AB_1 with a deeper section to carry 8.0m span (σ=310.2 > 165.0 MPa)
  3. Add a transfer beam to redirect load path around A_1
  [Enter or text] — describe a custom change
Choice:
```

The architect picks a number (resolved to the full description) or types free text. The choice is appended to the message history and passed to the reason node.

---

## First Principles Structural Calculations

"First principles" means the agent does not look up pre-computed tables or use empirical rules of thumb. It derives every result from fundamental physics and mechanics equations applied directly to the geometry of each element.

### Loads

Every beam and column accumulates load from the floor area it supports. The agent calculates tributary widths for beams (half the distance to the nearest parallel beam in each direction) and tributary areas for columns (a Voronoi-like partition of the column grid). From these areas it assembles:

- **Self-weight** — material density × cross-section area × span
- **Superimposed dead load** — 3.5 kN/m² (125mm slab + finishes + partitions, IS 875)
- **Live load** — 2.0 kN/m² (residential, IS 875 Part 2)

### Beam checks

Each beam is treated as a simply supported member with a uniform distributed load. Four checks are run:

**Bending stress** — the maximum bending moment at mid-span is M = wL²/8. The bending stress is σ = M / Wy, where Wy is the section modulus. For RCC and Timber, Wy = b·d²/6 from the solid rectangular section. For Steel, Wy is read directly from the IPE section property table (e.g. IPE 160: Wy = 108,700 mm³). The result is compared against the material's allowable bending stress.

**Shear stress** — the maximum shear at the support is V = wL/2. Average shear stress τ = V/A. Compared against allowable shear.

**Live-load deflection** — δ_LL = 5·w_LL·L⁴ / (384·E·I). Limit is L/360.

**Total-load deflection** — δ_TL = 5·w_tot·L⁴ / (384·E·I). Limit is L/250.

The elastic modulus E and moment of inertia I are material- and section-specific. For steel, I comes from the IPE lookup table (not b·d³/12), which gives the true stiffness of the I-section web and flanges rather than an overestimate from a solid block.

### Column checks

**Compressive stress** — axial load P = floor load from tributary area + column self-weight. Direct stress σ = P/A, compared against allowable compressive stress.

**Euler buckling** — the critical buckling load is P_cr = π²·E·I_min / Le², where Le = 0.65H is the effective length for a fixed-pinned condition (standard for reinforced concrete and steel frames). The safety factor SF = P_cr / P must exceed 3.0. For steel HSS columns, I_min and the radius of gyration r are taken from the section property table — the hollow square section is significantly less stiff than a solid block of the same outer dimensions, so using real values here matters.

### What-if simulation

When the prompt mentions removing a column, the agent re-evaluates all beams whose endpoint columns are being removed. It traces the beam chain from the floating endpoint through the removed positions until it reaches the nearest remaining column — this gives an effective span that may be much longer than the original. It then re-runs the bending, shear, and deflection checks at the extended span and reports which beams fail and by how much. The results are fed back to the reason node, which proposes specific remediation options (intermediate column, transfer beam, increased section depth) using the actual element IDs from the layout.

### Why this matters

Using the LLM to answer structural questions would produce plausible-sounding but numerically unreliable results. By separating the calculation (deterministic Python) from the communication (LLM), the agent gives the architect numbers they can stand behind — actual stress values, actual deflections, actual safety factors — while still presenting them in plain language at the speed of conversation.

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

| Profile  | A (mm²) | I (mm⁴)       | Wy (mm³) |
|----------|---------|---------------|----------|
| IPE 160  | 2,009   | 8.69 × 10⁶   | 108,700  |
| IPE 200  | 2,848   | 19.43 × 10⁶  | 194,300  |
| IPE 240  | 3,912   | 38.92 × 10⁶  | 324,300  |

| Profile       | A (mm²) | I_min (mm⁴)   | r_min (mm) |
|---------------|---------|---------------|------------|
| HSS 100×100×6 | 2,256   | 3.61 × 10⁶   | 40.0       |
| HSS 120×120×6 | 2,736   | 6.39 × 10⁶   | 48.3       |
| HSS 150×150×6 | 3,456   | 12.69 × 10⁶  | 60.6       |

### Section tiers

```
Base tier:
  RCC    — beam 200×300mm   | col 200×200mm
  STEEL  — beam IPE 160     | col HSS 100×100×6
  TIMBER — beam 100×240mm   | col 100×100mm

_M tier (upgrade on FAIL):
  RCC_M    — beam 250×450mm   | col 250×250mm
  STEEL_M  — beam IPE 200     | col HSS 120×120×6
  TIMBER_M — beam 120×300mm   | col 120×120mm

_L tier (upgrade if _M still FAILs):
  RCC_L    — beam 300×600mm   | col 300×300mm
  STEEL_L  — beam IPE 240     | col HSS 150×150×6
  TIMBER_L — beam 150×360mm   | col 150×150mm
```

---

## LLM Reasoning Rules

The reason node uses a structured system prompt that separates three distinct cases:

### What-if removal (two-step)
Step 1: User asks "what if we remove X" → LLM sets `action="final"`, `final_response=""`. Evaluate runs the simulation automatically.
Step 2: Evaluate appends a "STRUCTURAL FAIL after removing…" message → LLM reads the actual span, beam IDs, and stress values from that message and writes a three-option response (intermediate column / deeper section / transfer beam).

### Regular structural failure
When the conversation contains "User instruction after structural failure" + "Structural evaluation (first principles)": LLM reads the failing beam/column IDs directly from the evaluation text and writes failure-type-specific options (deflection → midspan support or section upgrade; bending → section upgrade; shear → section width; column buckling → bracing).
**Critical rule: LLM must never invent element IDs. Use only IDs present in the evaluation.**

### General questions / modifications
General questions (what rooms exist, what is permanent) → answered directly from layout JSON.
Modifications (add grid, confirmed change) → tool call.
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

| File | Lines (current) | Status | Key additions |
|------|-----------------|--------|---------------|
| `graph.py` | ~181 | Modified | AgentState, routing logic, material persistence to JSON after graph |
| `nodes/reason.py` | ~109 | Modified | SYSTEM_PROMPT with what-if + regular-fail + no-hallucination rules |
| `nodes/evaluate.py` | ~800 | New file | All structural intelligence (see breakdown below) |
| `nodes/comparison.py` | ~68 | New file | Layout diff + LLM plain-language summary |
| `nodes/modify.py` | ~51 | New file | MCP tool call, layout save, original snapshot |

### evaluate.py breakdown

| Section | Lines | Purpose |
|---------|-------|---------|
| `MATERIALS` | 30 | RCC / Steel / Timber allowable stresses and E values |
| `STEEL_BEAM_PROPS` / `STEEL_COL_PROPS` | 12 | Real IPE and HSS section property lookup tables |
| `DEFAULT_SECTIONS` / `SECTION_UPGRADE_MAP` | 20 | 9 material tiers, upgrade chain |
| `_beam_trib_widths` | 30 | Half-spacing tributary width geometry |
| `_column_trib_areas` | 20 | Voronoi-like tributary area per column |
| `_check_beams` | 80 | Bending, shear, LL deflection, TL deflection per beam |
| `_check_columns` | 60 | Compressive stress + Euler buckling per column |
| `_extract_removal_ids` | 20 | Regex extraction of removal intent from user message |
| `simulate_what_if_removal` | 130 | Beam chain trace + re-check at extended span |
| `evaluate_structure` | 30 | Public API — assembles full result dict |
| `_apply_material_override` | 20 | Patches all structure elements with chosen material + section |
| `_build_failure_alternatives` | 55 | Computes numbered alternatives menu from actual failure data |
| `build_evaluate_node` | ~200 | Full evaluate node: material picker → upgrade loop → eval → alternatives menu |

**~800 net new lines** across the five files. The structural intelligence — material selection, IPE/HSS lookup, load calculation, beam and column checks, what-if simulation, upgrade loop, alternatives menu — is entirely contained in these files.

---

## Example prompts

```
python main.py "add a structural grid to layout-1-large"
python main.py "evaluate the structural layout"
python main.py "what if we remove column C_2"
python main.py "what if we remove column B_3"
python main.py "what structural conflicts exist in the layout"
```

Valid column IDs: A_1 through D_4 (rows A-D, positions 1-4).

---

## Design principles

1. **LLM for language, Python for numbers.** The LLM never calculates — it reads results produced by deterministic code and writes plain-language responses.

2. **No hallucinated IDs.** The reason prompt explicitly forbids inventing element IDs. The alternatives menu in evaluate.py uses only IDs from the actual failure data — the LLM never sees a free-form "suggest alternatives" question.

3. **Human in the loop at every decision point.** Material selection, section upgrades, and failure responses are all interactive numbered menus — the architect chooses, the agent executes.

4. **Material persists across modify cycles.** The chosen material tier is stored in AgentState and written back to the layout JSON after the entire graph completes, so it survives multiple tool calls.

5. **_runtime/ is read-only.** All intelligence is in the five writable files. The bootstrap, LLM wrapper, MCP client, and CLI entry point are unchanged.

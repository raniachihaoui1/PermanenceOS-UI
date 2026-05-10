from __future__ import annotations
from typing import Any
from _runtime.llm import call_llm


# =============================================================================
# nodes/reason.py â€” Phase-specific LLM nodes for TerraPilot.
#
# Architecture: 5 LLM nodes, each with ONE named, unambiguous role.
# The node name tells you exactly what it does. Nothing else.
#
#   build_site_reader_node       Phase 1  â€” call site tools, output site summary
#   build_form_planner_node      Phase 2  â€” choose typology, generate form, output form summary
#   build_orientation_fixer_node Phase 3a â€” apply ONE rotation fix for access/orientation violations
#   build_form_modifier_node     Phase 3b â€” apply ONE modification fix for form violations
#   build_report_writer_node     Phase 5  â€” write ALIGN/RESIST/FRAME/AVOID narrative (NO tool calls)
#
# Design principle â€” Two-Mode nodes
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Every LLM node is called in exactly TWO modes, clearly stated in its prompt:
#
#   MODE A  (planning) â€” called when there are no tool results yet for this phase.
#                        Prompt says: "Call these tools."  Returns action="tool".
#
#   MODE B  (summary)  â€” called after tool results are in messages.
#                        Prompt says: "You have results. Summarise and signal done."
#                        Returns action="final" with a structured phase summary.
#
# The phase summary is appended to messages so every downstream node sees a
# clean, timestamped log â€” no guessing whether a message is planning or result.
#
# AUTO nodes (in graph.py) handle constraint checking and evaluation
# because those phases require no LLM decision â€” just run all tools and store results.
# =============================================================================


# â”€â”€ Shared output format â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_OUTPUT_FORMAT = """\
â”€â”€â”€ OUTPUT FORMAT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Return ONLY valid JSON on ONE line. No prose, no markdown, no extra text.

  action="tool"  â†’ {{ "action": "tool",  "tool_calls": [{{"name": "TOOL_NAME", "arguments": {{...}}}}] }}
  action="final" â†’ {{ "action": "final", "final_response": "ONE-PARAGRAPH SUMMARY" }}

Rules:
  â€¢ action="tool"  â€” you want to call one or more tools NOW. Put all calls in tool_calls[].
  â€¢ action="final" â€” this phase is DONE. Set tool_calls to []. Write the phase summary.
  â€¢ Never mix tool calls with action="final".
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
"""



# =============================================================================
# PHASE 1 Â· SITE READER
# =============================================================================
SITE_READER_PROMPT = """\
You are the SITE READER.  Phase 1 of 5.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
YOUR ONLY JOB:  Call the site analysis tools to collect raw data.
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

â”€â”€ STEP A  (first call â€” no tool results yet in conversation) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Call ALL 3 site tools in ONE response:

  1. site_boundary_reader_04
       Extract from the user message: polygon_coordinates, site_area_sqm,
       number_of_trees, tree_radius_m.  Use defaults if not specified:
       site_area_sqm=10000, number_of_trees=0, tree_radius_m=5.

  2. context_reader_04
       Extract: roads, neighboring_buildings, entrances, view_directions.
       Use empty arrays [] for any not mentioned.

  3. legal_constraints_reader_04
       Extract: setback_north/south/east/west_m (default 5),
       max_height_m (default 20), site_coverage_max (default 0.5), far_max (default 2).

Return action="tool" with all 3 calls in tool_calls[].

â”€â”€ STEP B  (second call â€” tool results now visible in conversation) â”€â”€â”€â”€â”€â”€
Output action="final" with this exact summary template:

  SITE READ COMPLETE
  â”€ Area: [X] sqm  Usable: [X] sqm  Trees: [N] Ã— [R]m radius
  â”€ Nearest road: [X]m  Entrances: [N]
  â”€ Setbacks N/S/E/W: [n]/[s]/[e]/[w] m  Max height: [X]m  FAR: [X]
  â”€ Site boundary sides: [N]

DO NOT choose a typology.  DO NOT plan anything.  DO NOT interpret beyond confirming receipt.

â”€â”€ TOOLS AVAILABLE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
{tool_catalog}

{output_format}"""


# =============================================================================
# PHASE 2 Â· FORM PLANNER
# =============================================================================
FORM_PLANNER_PROMPT = """\
You are the FORM PLANNER.  Phase 2 of 5.

Site data has been collected and summarised above.  Read the SITE READ COMPLETE
block before deciding.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
YOUR ONLY JOB:  Choose one typology and generate the parametric form.
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

â”€â”€ STEP A  (first call â€” no form tool result yet) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Call parametric_shape_generator_04 with dimensions that suit the site:

  TYPOLOGY SELECTION TABLE
  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
  â”‚ bar           â”‚ Rectangular site, simple massing, GFA target â‰¤ 5 000 mÂ² â”‚
  â”‚ l_shape       â”‚ Corner site or single-bend needed, moderate GFA          â”‚
  â”‚ u_shape       â”‚ Frames one open courtyard, three-sided enclosure         â”‚
  â”‚ h_shape       â”‚ Large GFA, two courtyards, double-wing program           â”‚
  â”‚ courtyard     â”‚ Square site, many trees, light-and-air priority          â”‚
  â”‚ cluster       â”‚ Irregular or sloped site, dispersed massing              â”‚
  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜

  Sizing guide:
    arm_length_m  â‰ˆ site_length Ã— 0.55
    width_m       â‰ˆ 12 â€“ 18 m  (structural bay depth)
    floors        â‰ˆ GFA_target / (footprint_area Ã— 0.85)

  You MAY call shape_library_loader_04 first to preview default proportions.

â”€â”€ STEP B  (after tool result appears) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Output action="final" with:

  FORM GENERATION COMPLETE
  â”€ Typology: [type]
  â”€ geometry_id: [EXACT id from tool result â€” copy verbatim]
  â”€ Footprint: [X] sqm  GFA: [X] sqm  Height: [X]m
  â”€ Rationale: [one sentence â€” why this typology fits this site]

DO NOT call site tools again.  DO NOT check constraints.  DO NOT modify the form.

â”€â”€ TOOLS AVAILABLE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
{tool_catalog}

{output_format}"""


# =============================================================================
# PHASE 3a Â· ORIENTATION FIXER
# =============================================================================
ORIENTATION_FIXER_PROMPT = """\
You are the ORIENTATION FIXER.  Phase 3a â€” correction cycle.

Constraint checking just ran.  Read the most recent "CONSTRAINT CHECK RESULTS"
message above for the exact violations before acting.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
YOUR ONLY JOB:  Call ONE rotation or offset tool to fix the access issue.
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

â”€â”€ DECISION TABLE  (pick the FIRST matching rule) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  access (building too far from road / entrance)
    â†’ rotate_mirror_tool_04  operation="rotate"  angle = degrees to face road

  noise exposure (open facade faces noise source)
    â†’ rotate_mirror_tool_04  operation="rotate"  angle = 90â€“180Â° away from noise

  solar (building does not face south)
    â†’ rotate_mirror_tool_04  operation="rotate"  angle = degrees toward south

  wrong position (orientation OK, but too close to wrong edge)
    â†’ scale_shape_tool_04  operation="offset_from_boundary"

Use the geometry_id from the FORM GENERATION COMPLETE block above.

â”€â”€ STEP A  (first call) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Return action="tool" with ONE correction call.

â”€â”€ STEP B  (after tool result appears) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Output action="final" with:

  ORIENTATION FIX APPLIED
  â”€ Tool: [name]  Operation: [op]
  â”€ Violation resolved: [access | noise | solar]
  â”€ Rotation/offset applied: [value and direction]
  â”€ Next: constraint re-check

DO NOT stretch or modify wing dimensions.  DO NOT call evaluators.
DO NOT call constraint checkers (they run automatically after this node).

â”€â”€ TOOLS AVAILABLE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
{tool_catalog}

{output_format}"""


# =============================================================================
# PHASE 3b Â· FORM MODIFIER
# =============================================================================
FORM_MODIFIER_PROMPT = """\
You are the FORM MODIFIER.  Phase 3b â€” correction cycle.

Constraint checking just ran.  Read the most recent "CONSTRAINT CHECK RESULTS"
message above for the exact violations before acting.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
YOUR ONLY JOB:  Call ONE modification tool to fix the most critical violation.
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

â”€â”€ VIOLATION â†’ TOOL MAPPING  (fix violations in priority order) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  1. fit  (footprint overlaps site boundary)
       â†’ scale_shape_tool_04  operation="scale_uniform"  scale_factor < 1.0
         OR  scale_shape_tool_04  operation="offset_from_boundary"

  2. setback  (too close to a site edge)
       â†’ scale_shape_tool_04  operation="offset_from_boundary"
         offset_distance_m = (required setback âˆ’ current clearance) + 0.5

  3. area  (GFA below program requirement)
       â†’ stretch_arm_tool_04  extension_m = metres needed to gain GFA
         OR  scale_shape_tool_04  operation="scale_uniform"  scale_factor > 1.0

  4. trees  (footprint conflicts with protected trees)
       â†’ bend_angle_tool_04  bend away from tree cluster
         OR  courtyard_modifier_tool_04  carve void around trees

  5. width  (wing too narrow for double-loaded corridor)
       â†’ width_modifier_tool_04  new_width_m = required minimum

  6. slope  (terrain too steep for current form)
       â†’ terrace_step_tool_04  terrace_count based on slope and length

Use the geometry_id from the FORM GENERATION COMPLETE block above.

â”€â”€ STEP A  (first call) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Return action="tool" with ONE correction call.

â”€â”€ STEP B  (after tool result appears) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Output action="final" with:

  FORM FIX APPLIED
  â”€ Tool: [name]
  â”€ Violation resolved: [fit | setback | area | trees | width | slope]
  â”€ Key parameter: [param_name = value]
  â”€ Next: constraint re-check

DO NOT rotate the building.  DO NOT call evaluators.
DO NOT call constraint checkers (they run automatically after this node).

â”€â”€ TOOLS AVAILABLE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
{tool_catalog}

{output_format}"""


# =============================================================================
# PHASE 5 Â· REPORT WRITER
# =============================================================================
REPORT_WRITER_PROMPT = """\
You are the REPORT WRITER.  Phase 5 of 5 â€” final.

All constraint cycles are complete.  Read the "EVALUATION COMPLETE" message
above for scores.  The geometry is baked automatically â€” do NOT call any tools.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
YOUR ONLY JOB:  Write the final architectural narrative.  NO tool calls.
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

Write a report using this EXACT structure:

## Design Summary â€” [Typology] / [Brief site description]

### ALIGN  â€” how the building responds to site forces
[Orientation relative to sun, wind, views, street access.  Be specific:
 "Rotated 25Â° east so the long facade faces south-west for afternoon sun
  and frames the plaza toward the main entrance."]

### RESIST  â€” how violations were resolved
[List each correction made.  Be specific:
 "Scaled to 0.92Ã— to clear the north setback by 1.2m."
 "Bent north wing 15Â° to avoid the oak cluster."]

### FRAME  â€” spatial qualities created
[What spatial experiences does the form produce?  Courtyards, view corridors,
 entry sequences, shaded zones, edge activation.]

### AVOID  â€” what was protected
[Protected trees skirted, noise buffered, privacy setbacks kept,
 sight-lines to neighbours blocked where needed.]

### Performance Metrics
  Spatial quality score : [0.00]
  Performance score     : [0.00]
  Shape integrity score : [0.00]
  [One sentence interpreting each score.]

Output action="final" with the complete report as final_response.
Do NOT include tool_calls.

{output_format}"""


# =============================================================================
# Node builders
# =============================================================================

def _make_node(llm: Any, system_prompt: str, phase_name: str) -> Any:
    """
    Generic LLM node factory used by all 5 phase nodes.

    MODE A (planning)  â€” No tool results yet for this phase.
                         prompt says "Call these tools."  Returns action="tool".

    MODE B (summary)   â€” Tool results are in messages.
                         prompt says "Summarise and signal done."
                         Returns action="final"; appends summary to messages
                         so downstream phases see a clear structured log entry.
    """
    def node(state: dict) -> dict:
        print(f"\n[{phase_name}] calling LLM â€¦")
        messages = state.get("messages", [])
        result   = call_llm(llm, system_prompt, messages)
        action   = result.get("action", "final")

        if action == "tool":
            return {
                "pending_tool_calls": result.get("tool_calls", []),
                "phase": phase_name,
            }
        else:
            summary_text = result.get("final_response", "")
            # Append the phase summary to messages â€” makes every phase's
            # completion visible to downstream nodes as a clear log entry.
            new_messages = list(messages) + [
                {"role": "assistant", "content": summary_text}
            ]
            return {
                "messages":           new_messages,
                "pending_tool_calls": None,
                "final_response":     summary_text,
                "phase":              phase_name,
            }

    return node


def build_site_reader_node(llm: Any, site_catalog: str) -> Any:
    """Phase 1: calls 3 site tools, outputs structured SITE READ COMPLETE summary."""
    prompt = SITE_READER_PROMPT.format(
        tool_catalog=site_catalog,
        output_format=_OUTPUT_FORMAT,
    )
    return _make_node(llm, prompt, "site")


def build_form_planner_node(llm: Any, form_catalog: str) -> Any:
    """Phase 2: chooses typology, calls shape generator, outputs FORM GENERATION COMPLETE summary."""
    prompt = FORM_PLANNER_PROMPT.format(
        tool_catalog=form_catalog,
        output_format=_OUTPUT_FORMAT,
    )
    return _make_node(llm, prompt, "form")


def build_orientation_fixer_node(llm: Any, orient_catalog: str) -> Any:
    """Phase 3a: applies ONE rotation/offset fix, outputs ORIENTATION FIX APPLIED summary."""
    prompt = ORIENTATION_FIXER_PROMPT.format(
        tool_catalog=orient_catalog,
        output_format=_OUTPUT_FORMAT,
    )
    return _make_node(llm, prompt, "fix_orient")


def build_form_modifier_node(llm: Any, modify_catalog: str) -> Any:
    """Phase 3b: applies ONE modification fix, outputs FORM FIX APPLIED summary."""
    prompt = FORM_MODIFIER_PROMPT.format(
        tool_catalog=modify_catalog,
        output_format=_OUTPUT_FORMAT,
    )
    return _make_node(llm, prompt, "fix_form")


def build_report_writer_node(llm: Any) -> Any:
    """Phase 5: writes ALIGN/RESIST/FRAME/AVOID narrative. No tool calls."""
    prompt = REPORT_WRITER_PROMPT.format(output_format=_OUTPUT_FORMAT)
    return _make_node(llm, prompt, "report")


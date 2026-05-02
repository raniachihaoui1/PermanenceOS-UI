# Adding Local Python Tools

## Quick Reference

### 3 Key Files to Create/Modify

**1. `local_tools/layout_filter.py`** — Your Python tool
```python
def select_layout(all_layouts, layout_id=None, ...):
    return {"result": ...}  # Return dict, not JSON string
```

**2. `nodes/local_tools.py`** — Tool executor node
```python
def get_local_tools():
    return [{"name": "layout_filter", "inputSchema": {...}}]

def build_local_tool_node():
    def local_tool_node(state):
        # Call select_layout with state["all_layouts"]
        ...
    return local_tool_node
```

**3. `graph.py`** — Update graph & routing
```python
# Add to AgentState:
all_layouts: list[dict[str, Any]]

# In _build_initial_state():
all_layouts = json.loads(layouts_path.read_text())
local_tools = get_local_tools()
combined_tools = local_tools + ctx.tools

# Update _route():
if call["name"] == "layout_filter":
    return "local_tool"

# In build_graph():
local_tool = build_local_tool_node()
graph.add_node("local_tool", local_tool)
graph.add_conditional_edges("reason", _route, 
    {"run_tool": "tool", "local_tool": "local_tool", "finish": END})
graph.add_edge("local_tool", "reason")
```

---

## Critical Lessons

✅ **DO:**
- Keep user's request in user message — LLM needs it
- Use `inputSchema` (camelCase) — Match MCP format
- Create routing to separate local vs MCP tools
- Load data (all_layouts) into state

❌ **DON'T:**
- Remove critical info from user message when modifying it
- Return JSON strings from local tools — Return dicts
- Modify bootstrap.py — Use graph.py state instead
- Reuse MCP tool names (use "layout_filter" not "select_layout")

---

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Tool timeout | Routed to MCP instead of local_tool | Check `_route()` and node registration |
| LLM ignores tools | Missing user message context | Don't remove `f"User request:\n{prompt}"` |
| Tool gets None data | Data not loaded or in state | Load all_layouts; add to return dict |
| Tool catalog broken | Schema format mismatch | Use `inputSchema` consistently |

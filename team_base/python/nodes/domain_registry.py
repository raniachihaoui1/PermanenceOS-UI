from __future__ import annotations

# Central registry for domain-specific sub-agents.
#
# To add a new domain later, add one entry here (for example "mass").
# The rest of the workflow reads from this registry instead of hard-coding
# separate lists in multiple files.
DOMAIN_REGISTRY: dict[str, dict[str, object]] = {
    "volume": {
        "tool_name_contains": ["volume"],
        "label": "Volume",
    },
    "area": {
        "tool_name_contains": ["area"],
        "label": "Area",
    },
}

AVAILABLE_DOMAINS: tuple[str, ...] = tuple(DOMAIN_REGISTRY.keys())

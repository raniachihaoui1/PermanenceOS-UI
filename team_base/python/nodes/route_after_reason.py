from __future__ import annotations

from typing import Any, Callable


def create_route_after_reason(dbg: Callable[[str], None]) -> Callable[[dict[str, Any]], str]:
    def route_after_reason(state: dict[str, Any]) -> str:
        if state["final_response"] is not None:
            dbg("[graph][route] reason -> finish")
            return "finish"
        dbg("[graph][route] reason -> run_tool")
        return "run_tool"

    return route_after_reason

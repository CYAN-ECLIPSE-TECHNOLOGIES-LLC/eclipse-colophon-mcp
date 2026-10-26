#!/usr/bin/env python3
# Eclipse Colophon MCP — Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
"""MCP-style dispatch. 23 P0 tools; owner verbs absent from non-owner table (no oracle).
commerce_verify_offer = P2 simulator surface, separate from the 23. No price-write verb exists;
any price-write-shaped name -> REPRICE_FORBIDDEN."""
import json, re, sys
import colophon_engine as E

REPRICE_NAMES = re.compile(r"(reprice|price_write|set_price|update_price|enroll|unenroll)", re.I)

def list_tools(owner=False):
    names = list(E.TOOLS) if owner else [n for n in E.TOOLS if n not in E.OWNER_TOOLS]
    return [{"name": n, "descriptor": E.DESCRIPTOR} for n in names]

def dispatch(name, params=None, owner=False):
    params = params or {}
    try:
        if REPRICE_NAMES.search(name): raise E.ToolError("REPRICE_FORBIDDEN", name)
        if name in ("watch_scan_title",): raise E.ToolError("PORTAL_TOS_GATE", "Watch D4-gated, not P0")
        if name.startswith("connector_"): raise E.ToolError("PORTAL_TOS_GATE", "Connector P1/D3-gated")
        if name == "commerce_verify_offer": return {"ok": True, "result": E.commerce_verify_offer(params)}
        if name not in E.TOOLS: raise E.ToolError("UNKNOWN_TOOL", name)
        if name in E.OWNER_TOOLS and not owner and params.get("owner_token") != E.OWNER_TOKEN:
            raise E.ToolError("UNKNOWN_TOOL", "no oracle")  # indistinguishable from unknown
        return {"ok": True, "result": E.TOOLS[name](params)}
    except E.ToolError as e:
        return {"ok": False, "error": e.code, "detail": str(e)}

if __name__ == "__main__":
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("method") == "tools/list": out = {"tools": list_tools(req.get("owner", False))}
        else: out = dispatch(req.get("tool",""), req.get("params",{}), req.get("owner", False))
        print(json.dumps(out))

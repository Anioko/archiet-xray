#!/usr/bin/env python3
"""Archiet X-Ray MCP server — give your AI agent the architecture map.

A minimal, stdlib-only MCP (Model Context Protocol) server over stdio that
exposes the X-Ray extractor to AI coding agents (Claude Code, Cursor,
Windsurf, …). The agent can ask *before* it edits:

  - xray_scan          (re)scan the repo, get stats + visibility score
  - arch_summary       compact architecture summary (modules, routes, entities)
  - blast_radius       who depends on this file/module? what breaks if I edit it?
  - boundary_findings  deterministic risk findings (secrets, raw SQL, token storage)

Register (Claude Code):
  claude mcp add archiet-xray -- python /path/to/mcp_server.py /path/to/repo

No LLM calls, no network — everything is deterministic local extraction.
https://archiet.com
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import xray as _xray

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "xray_scan",
        "description": (
            "Scan the repository and build the architecture model (routes, "
            "entities, tasks, module dependency graph, findings). Run once at "
            "session start and after structural changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "arch_summary",
        "description": (
            "Compact architecture summary: modules, route prefixes, domain "
            "entities, hotspots, visibility score. Use this as ground truth "
            "for where things live before searching the codebase."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "blast_radius",
        "description": (
            "Given a file or top-level module path, report what depends on it "
            "(fan-in), what it depends on (fan-out), and the routes/entities "
            "it contains. Call BEFORE editing anything load-bearing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "file path or module, relative to repo root",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "boundary_findings",
        "description": (
            "Deterministic risk findings: hardcoded secrets, raw SQL bypassing "
            "the ORM, auth tokens in localStorage, routes without auth guards."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


class Server:
    def __init__(self, repo: Path):
        self.repo = repo
        self.model: dict | None = None

    # ── tool implementations ────────────────────────────────────────────
    def _ensure_model(self) -> dict:
        if self.model is None:
            self.model = _xray.xray(self.repo)
        return self.model

    def t_xray_scan(self, _args: dict) -> dict:
        self.model = _xray.xray(self.repo)
        return {"score": self.model["score"], "stats": self.model["stats"]}

    def t_arch_summary(self, _args: dict) -> dict:
        m = self._ensure_model()
        return {
            "repo": m["repo"],
            "score": m["score"],
            "modules": m["modules"],
            "entities": [e["name"] for e in m["entities"]],
            "route_count": m["stats"]["routes"],
            "route_sample": [
                {"path": r["path"], "methods": r["methods"], "file": r["file"]}
                for r in m["routes"][:30]
            ],
            "hotspots": m["hotspots"][:10],
        }

    def t_blast_radius(self, args: dict) -> dict:
        m = self._ensure_model()
        path = args["path"].replace("\\", "/").strip("/")
        head = path.split("/")[0]
        dependents = [e for e in m["module_edges"] if e["to"] == head]
        dependencies = [e for e in m["module_edges"] if e["from"] == head]
        contains = {
            "routes": [
                r for r in m["routes"] if r["file"].replace("\\", "/").startswith(path)
            ],
            "entities": [
                e["name"]
                for e in m["entities"]
                if e["file"].replace("\\", "/").startswith(path)
            ],
        }
        hot = next(
            (
                h
                for h in m["hotspots"]
                if h["module"] == path or h["module"].startswith(path)
            ),
            None,
        )
        return {
            "target": path,
            "dependent_modules": dependents,
            "dependency_modules": dependencies,
            "direct_imports_of_target": hot["fan_in"] if hot else 0,
            "contains": contains,
            "advice": (
                "High fan-in: read dependents before editing."
                if (hot and hot["fan_in"] > 10) or len(dependents) > 3
                else "Low coupling detected for this target."
            ),
        }

    def t_boundary_findings(self, _args: dict) -> dict:
        m = self._ensure_model()
        no_auth = [
            {"path": r["path"], "file": r["file"], "line": r["line"]}
            for r in m["routes"]
            if r["auth"] is False
        ]
        return {"findings": m["findings"], "routes_without_auth_guard": no_auth[:40]}

    # ── jsonrpc plumbing ────────────────────────────────────────────────
    def handle(self, msg: dict) -> dict | None:
        mid = msg.get("id")
        method = msg.get("method", "")
        if method == "initialize":
            return self._result(
                mid,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "archiet-xray",
                        "version": _xray.XRAY_VERSION,
                    },
                },
            )
        if method in {"notifications/initialized", "initialized"}:
            return None
        if method == "tools/list":
            return self._result(mid, {"tools": TOOLS})
        if method == "tools/call":
            name = msg["params"]["name"]
            args = msg["params"].get("arguments") or {}
            impl = getattr(self, f"t_{name}", None)
            if impl is None:
                return self._error(mid, -32602, f"unknown tool: {name}")
            try:
                payload = impl(args)
            except Exception as exc:  # surface, never crash the server
                return self._result(
                    mid,
                    {
                        "content": [{"type": "text", "text": f"error: {exc}"}],
                        "isError": True,
                    },
                )
            return self._result(
                mid,
                {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]},
            )
        if method == "ping":
            return self._result(mid, {})
        if mid is not None:
            return self._error(mid, -32601, f"method not found: {method}")
        return None

    @staticmethod
    def _result(mid, result) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _error(mid, code, message) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "error": {"code": code, "message": message},
        }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    repo = Path(args[0]) if args else Path(".")
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 2
    server = Server(repo.resolve())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = server.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

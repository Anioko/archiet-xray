#!/usr/bin/env python3
"""Archiet Architecture Audit MCP server — procurement-grade audits for AI agents.

A minimal, stdlib-only MCP (Model Context Protocol) server over stdio that
lets an AI agent (Claude Code, Cursor, Windsurf, …) submit architecture
documents to Archiet's hosted audit factory and get back a shareable,
consulting-grade traceability report:

  - submit_architecture_audit  upload docs (or pasted text) → audit report URL
  - get_audit_status           poll a previously created audit by token
  - get_audit_limits           file count/size limits before uploading

UNLIKE archiet-xray (which is fully local), this server TALKS TO THE NETWORK:
the documents you submit are uploaded to archiet.com (or ARCHIET_BASE_URL),
processed by a deterministic audit pipeline (no LLM reads your docs), and the
resulting report lives at an unguessable URL you can share with your team or
procurement. The uploaded files themselves are never exposed publicly.

Register (Claude Code):
  claude mcp add archiet-audit -- python /path/to/server.py

https://archiet.com/audit-my-architecture
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_BASE_URL = "https://archiet.com"
API_PATH = "/api/audits/architecture"
HTTP_TIMEOUT_SEC = 120  # the audit renders synchronously (~15s typical)

TOOLS = [
    {
        "name": "submit_architecture_audit",
        "description": (
            "Submit architecture documents to Archiet's audit factory and get "
            "back a consulting-grade traceability audit: a % can-generate / "
            "partial / cannot / custom breakdown across 22+ architecture "
            "concerns, severity-ranked gaps, and a 30/60/90-day adoption "
            "roadmap, at a shareable unguessable URL. Provide either local "
            "file paths (pdf/docx/md/txt/html) or pasted architecture text. "
            "NOTE: this uploads the documents to archiet.com for processing — "
            "the pipeline is deterministic (no LLM reads your docs) and the "
            "files are never exposed publicly, but do not submit material "
            "you may not transmit. Rate limit: one audit per minute per IP."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": (
                        "work email — the report link is associated with it"
                    ),
                },
                "company_name": {
                    "type": "string",
                    "description": "optional — appears as the audit subject",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "local paths to architecture docs " "(pdf, docx, md, txt, html)"
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "pasted architecture description (markdown), used when "
                        "no files are given"
                    ),
                },
            },
            "required": ["email"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_audit_status",
        "description": (
            "Fetch a previously submitted audit request by its token — status, "
            "inferred customer profile, and the report URLs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "audit request token"}
            },
            "required": ["token"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_audit_limits",
        "description": (
            "Upload limits for the audit endpoint (max files, per-file and "
            "total size) — check before submitting large document sets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


def base_url() -> str:
    return os.environ.get("ARCHIET_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def encode_multipart(
    fields: dict[str, str], files: list[tuple[str, str, bytes]]
) -> tuple[bytes, str]:
    """Encode form fields + files as multipart/form-data (stdlib only).

    ``files`` entries are (form_field_name, filename, content).
    Returns (body, content_type).
    """
    boundary = f"archiet-audit-{uuid.uuid4().hex}"
    out: list[bytes] = []
    for name, value in fields.items():
        out += [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ]
    for field, filename, content in files:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        out += [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{field}"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            f"Content-Type: {ctype}\r\n\r\n".encode(),
            content,
            b"\r\n",
        ]
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def http_json(req: urllib.request.Request) -> tuple[int, dict]:
    """Execute a request; return (status, parsed-json-or-error-dict)."""
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {"error": f"http_{exc.code}", "detail": str(exc)}
    except urllib.error.URLError as exc:
        return 0, {"error": "network_unreachable", "detail": str(exc.reason)}


class Server:
    # ── tool implementations ────────────────────────────────────────────
    def t_submit_architecture_audit(self, args: dict) -> dict:
        email = (args.get("email") or "").strip()
        if not email or "@" not in email:
            return {"error": "a valid work email is required"}

        uploads: list[tuple[str, str, bytes]] = []
        for raw in args.get("files") or []:
            p = Path(raw).expanduser()
            if not p.is_file():
                return {"error": f"file not found: {raw}"}
            uploads.append(("files", p.name, p.read_bytes()))
        text = (args.get("text") or "").strip()
        if not uploads and text:
            uploads.append(("files", "architecture.md", text.encode("utf-8")))
        if not uploads:
            return {
                "error": (
                    "provide `files` (paths to pdf/docx/md/txt/html) or `text` "
                    "(pasted architecture description)"
                )
            }

        fields = {"email": email}
        company = (args.get("company_name") or "").strip()
        if company:
            fields["company_name"] = company

        body, content_type = encode_multipart(fields, uploads)
        req = urllib.request.Request(
            base_url() + API_PATH,
            data=body,
            headers={
                "Content-Type": content_type,
                "User-Agent": f"archiet-audit-mcp/{SERVER_VERSION}",
            },
            method="POST",
        )
        status, payload = http_json(req)
        if status == 201:
            share = payload.get("share_url") or ""
            audit = payload.get("audit_url") or ""
            row = payload.get("request") or {}
            return {
                "status": "completed",
                "share_url": base_url() + share if share.startswith("/") else share,
                "audit_url": base_url() + audit if audit.startswith("/") else audit,
                "token": row.get("token"),
                "inferred_profile": {
                    k: row.get(k)
                    for k in ("industry", "stack", "compliance")
                    if row.get(k) is not None
                },
                "note": (
                    "Share the audit_url with your team — it is unguessable, "
                    "not listed publicly, and renders the full consulting-grade "
                    "report."
                ),
            }
        return {"status": "failed", "http_status": status, **payload}

    def t_get_audit_status(self, args: dict) -> dict:
        token = (args.get("token") or "").strip()
        if not token:
            return {"error": "token is required"}
        req = urllib.request.Request(
            f"{base_url()}{API_PATH}/{token}",
            headers={"User-Agent": f"archiet-audit-mcp/{SERVER_VERSION}"},
        )
        status, payload = http_json(req)
        return {"http_status": status, **payload}

    def t_get_audit_limits(self, _args: dict) -> dict:
        req = urllib.request.Request(
            f"{base_url()}{API_PATH}/limits",
            headers={"User-Agent": f"archiet-audit-mcp/{SERVER_VERSION}"},
        )
        status, payload = http_json(req)
        return {"http_status": status, **payload}

    # ── jsonrpc plumbing (same shape as archiet-xray) ───────────────────
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
                        "name": "archiet-audit",
                        "version": SERVER_VERSION,
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


def main() -> int:
    server = Server()
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

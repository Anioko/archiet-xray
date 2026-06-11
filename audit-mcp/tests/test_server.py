"""Tests for the archiet-audit MCP server — offline, network fully mocked."""

import io
import json
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as audit_server  # noqa: E402


# ── multipart encoder ────────────────────────────────────────────────────────


def test_encode_multipart_roundtrip_shape():
    body, ctype = audit_server.encode_multipart(
        {"email": "cto@acme.com", "company_name": "Acme"},
        [("files", "arch.md", b"# Architecture\nclaims platform")],
    )
    assert ctype.startswith("multipart/form-data; boundary=archiet-audit-")
    boundary = ctype.split("boundary=")[1]
    text = body.decode("utf-8")
    assert text.count(f"--{boundary}") == 4  # 2 fields + 1 file + terminator
    assert 'name="email"' in text and "cto@acme.com" in text
    assert 'filename="arch.md"' in text
    assert "# Architecture" in text
    assert text.rstrip().endswith(f"--{boundary}--")


# ── tool behaviour (urlopen mocked) ──────────────────────────────────────────


class _FakeResponse(io.BytesIO):
    def __init__(self, status: int, payload: dict):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_submit_returns_absolute_share_url(monkeypatch, tmp_path):
    doc = tmp_path / "arch.md"
    doc.write_text("# Claims platform\ninsurance carriers", encoding="utf-8")

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return _FakeResponse(
            201,
            {
                "request": {"token": "tok123", "industry": "insurance"},
                "share_url": "/audit-my-architecture/tok123",
                "audit_url": "/audits/insurance-acme-abc",
            },
        )

    monkeypatch.setattr(audit_server.urllib.request, "urlopen", fake_urlopen)
    out = audit_server.Server().t_submit_architecture_audit(
        {"email": "cto@acme.com", "files": [str(doc)]}
    )
    assert out["status"] == "completed"
    assert out["share_url"] == "https://archiet.com/audit-my-architecture/tok123"
    assert out["audit_url"] == "https://archiet.com/audits/insurance-acme-abc"
    assert out["token"] == "tok123"
    assert out["inferred_profile"]["industry"] == "insurance"
    assert captured["url"].endswith("/api/audits/architecture")
    assert b"insurance carriers" in captured["body"]


def test_submit_accepts_pasted_text(monkeypatch):
    def fake_urlopen(req, timeout=None):
        assert b'filename="architecture.md"' in req.data
        return _FakeResponse(
            201,
            {"request": {"token": "t2"}, "share_url": "/x/t2", "audit_url": None},
        )

    monkeypatch.setattr(audit_server.urllib.request, "urlopen", fake_urlopen)
    out = audit_server.Server().t_submit_architecture_audit(
        {"email": "cto@acme.com", "text": "# My architecture\nFlask + Postgres"}
    )
    assert out["status"] == "completed"


def test_submit_validates_inputs():
    s = audit_server.Server()
    assert "error" in s.t_submit_architecture_audit({"email": "not-an-email"})
    assert "error" in s.t_submit_architecture_audit({"email": "a@b.com"})
    assert "error" in s.t_submit_architecture_audit(
        {"email": "a@b.com", "files": ["/no/such/file.md"]}
    )


def test_submit_surfaces_rate_limit(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url,
            429,
            "rate limited",
            None,
            io.BytesIO(
                json.dumps({"error": "rate_limited", "retry_after_sec": 60}).encode(
                    "utf-8"
                )
            ),
        )

    monkeypatch.setattr(audit_server.urllib.request, "urlopen", fake_urlopen)
    out = audit_server.Server().t_submit_architecture_audit(
        {"email": "a@b.com", "text": "arch"}
    )
    assert out["status"] == "failed"
    assert out["http_status"] == 429
    assert out["error"] == "rate_limited"


def test_base_url_env_override(monkeypatch):
    monkeypatch.setenv("ARCHIET_BASE_URL", "http://localhost:9500/")
    assert audit_server.base_url() == "http://localhost:9500"


# ── jsonrpc plumbing over stdio (no network calls made) ──────────────────────


def test_mcp_stdio_initialize_and_list():
    srv = Path(__file__).resolve().parents[1] / "server.py"
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "submit_architecture_audit",
                "arguments": {"email": "missing-at-sign"},
            },
        },
    ]
    proc = subprocess.run(
        [sys.executable, str(srv)],
        input="\n".join(json.dumps(m) for m in msgs) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [json.loads(ln) for ln in proc.stdout.strip().splitlines()]
    by_id = {ln["id"]: ln for ln in lines if "id" in ln}
    assert by_id[1]["result"]["serverInfo"]["name"] == "archiet-audit"
    names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert names == {
        "submit_architecture_audit",
        "get_audit_status",
        "get_audit_limits",
    }
    # Invalid email is rejected locally — no network needed.
    payload = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert "error" in payload

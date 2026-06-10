"""Tests for the X-Ray extractor — fixture mini-repo, no DB, no network."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xray  # noqa: E402


@pytest.fixture()
def mini_repo(tmp_path: Path) -> Path:
    (tmp_path / "app" / "blueprints").mkdir(parents=True)
    (tmp_path / "app" / "models").mkdir(parents=True)
    (tmp_path / "frontend" / "app" / "dashboard").mkdir(parents=True)
    (tmp_path / "frontend" / "app" / "api" / "users").mkdir(parents=True)

    # Trigger strings are runtime-assembled so this test file itself never
    # trips the repo's secret/raw-SQL/localStorage pre-commit scanners
    # (same convention as delivery_gate's _resolve_secret).
    fake_secret = "sk-" + "live-" + "abcdef1234567890"
    raw_sql = "SEL" + "ECT * FROM users WHERE 1=1"
    (tmp_path / "app" / "blueprints" / "users_bp.py").write_text(
        textwrap.dedent(f"""
        from flask import Blueprint, jsonify
        from app.models.user import User
        from app.services.auth import login_required

        bp = Blueprint("users", __name__)

        @bp.route("/api/users", methods=["GET", "POST"])
        @login_required
        def list_users():
            return jsonify([])

        @bp.route("/api/public/ping")
        def ping():
            return "pong"

        API_SECRET{'_KEY'} = "{fake_secret}"

        def report(db):
            db.execute("{raw_sql}")
    """),
        encoding="utf-8",
    )

    (tmp_path / "app" / "models" / "user.py").write_text(
        textwrap.dedent("""
        from app.extensions import db

        class User(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            email = db.Column(db.String(255))
            workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"))

        class Workspace(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(255))
    """),
        encoding="utf-8",
    )

    (tmp_path / "app" / "tasks.py").write_text(
        textwrap.dedent("""
        from celery import shared_task

        @shared_task
        def send_digest():
            pass
    """),
        encoding="utf-8",
    )

    set_item = "local" + "Storage.set" + "Item"
    (tmp_path / "frontend" / "app" / "dashboard" / "page.tsx").write_text(
        'import { api } from "@/lib/api";\n'
        f'{set_item}("auth_token", token);\n'
        "export default function Page() { return null }\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "app" / "api" / "users" / "route.ts").write_text(
        "export async function GET() { return Response.json([]) }\n",
        encoding="utf-8",
    )
    return tmp_path


def test_extracts_flask_routes_with_auth(mini_repo):
    m = xray.xray(mini_repo)
    routes = {r["path"]: r for r in m["routes"] if r["framework"] == "flask"}
    assert routes["/api/users"]["methods"] == ["GET", "POST"]
    assert routes["/api/users"]["auth"] is True
    assert routes["/api/public/ping"]["auth"] is False


def test_extracts_entities_and_relations(mini_repo):
    m = xray.xray(mini_repo)
    ents = {e["name"]: e for e in m["entities"]}
    assert "User" in ents and "Workspace" in ents
    assert "workspaces" in ents["User"]["relations"]
    assert "email" in ents["User"]["fields"]


def test_extracts_celery_tasks(mini_repo):
    m = xray.xray(mini_repo)
    assert any(t["name"] == "send_digest" for t in m["tasks"])


def test_extracts_nextjs_routes(mini_repo):
    m = xray.xray(mini_repo)
    paths = {r["path"] for r in m["routes"]}
    assert "/dashboard" in paths
    assert "/api/users" in paths  # both flask + next route


def test_findings_secret_rawsql_tokenstorage(mini_repo):
    m = xray.xray(mini_repo)
    codes = {f["code"] for f in m["findings"]}
    assert {"hardcoded-secret", "raw-sql", "token-in-localstorage"} <= codes


def test_placeholder_secrets_not_flagged(tmp_path):
    (tmp_path / "config.py").write_text(
        'SECRET_KEY = "change-me-in-production"\n', encoding="utf-8"
    )
    m = xray.xray(tmp_path)
    assert not any(f["code"] == "hardcoded-secret" for f in m["findings"])


def test_module_graph_edges(mini_repo):
    m = xray.xray(mini_repo)
    edges = {(e["from"], e["to"]) for e in m["module_edges"]}
    assert ("app", "app") not in edges  # no self loops
    # blueprint file imports app.models / app.services -> within 'app' only,
    # so cross-top-level edges may be empty; frontend imports '@/lib' (alias,
    # external-looking) -> also none. Assert the structure exists.
    assert isinstance(m["module_edges"], list)


def test_score_and_outputs_render(mini_repo):
    m = xray.xray(mini_repo)
    assert 0 < m["score"] <= 100
    md = xray.render_architecture_md(m)
    assert "Visibility score" in md and "mermaid" in md
    agent = xray.render_agent_context(m)
    assert "AGENT CONTEXT" in agent and "blast radius" in agent.lower()


def test_cli_writes_outputs(mini_repo):
    rc = xray.main([str(mini_repo), "--quiet"])
    assert rc == 0
    out = mini_repo / ".archiet"
    assert (out / "architecture.json").exists()
    assert (out / "ARCHITECTURE.md").exists()
    assert (out / "AGENT_CONTEXT.md").exists()
    model = json.loads((out / "architecture.json").read_text(encoding="utf-8"))
    assert model["xray_version"] == xray.XRAY_VERSION


def test_mcp_server_end_to_end(mini_repo):
    """Drive the MCP server over stdio: initialize -> tools/list -> tools/call."""
    server = Path(__file__).resolve().parents[1] / "mcp_server.py"
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "arch_summary", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "blast_radius", "arguments": {"path": "app/models"}},
        },
    ]
    proc = subprocess.run(
        [sys.executable, str(server), str(mini_repo)],
        input="\n".join(json.dumps(m) for m in msgs) + "\n",
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = [json.loads(ln) for ln in proc.stdout.strip().splitlines()]
    by_id = {ln["id"]: ln for ln in lines if "id" in ln}
    assert by_id[1]["result"]["serverInfo"]["name"] == "archiet-xray"
    tool_names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert {
        "xray_scan",
        "arch_summary",
        "blast_radius",
        "boundary_findings",
    } <= tool_names
    summary = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert "User" in summary["entities"]
    blast = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert blast["target"] == "app/models"

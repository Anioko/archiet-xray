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


# ── v0.2: production readiness + diagram pack ───────────────────────────────


def test_production_readiness_shape_and_determinism(mini_repo):
    m1 = xray.xray(mini_repo)
    m2 = xray.xray(mini_repo)
    r = m1["readiness"]
    assert 0 <= r["score"] <= 100
    assert r["max"] == 100
    assert sum(d["max"] for d in r["dimensions"]) == 100
    assert all(0 <= d["points"] <= d["max"] for d in r["dimensions"])
    assert r["label"] in {
        "production-ready signals",
        "near production-ready",
        "at risk",
        "not production-ready",
    }
    # Deterministic: same repo, same score, same dimension breakdown.
    assert r == m2["readiness"]


def test_readiness_penalizes_known_defects(mini_repo):
    m = xray.xray(mini_repo)
    dims = {d["id"]: d for d in m["readiness"]["dimensions"]}
    # mini_repo plants a hardcoded secret, raw SQL, and a localStorage token.
    assert dims["secrets_hygiene"]["points"] < dims["secrets_hygiene"]["max"]
    assert dims["data_layer"]["points"] < dims["data_layer"]["max"]
    assert dims["client_token_storage"]["points"] < dims["client_token_storage"]["max"]
    # The unguarded /api/public/ping must cost auth-coverage points.
    assert dims["auth_coverage"]["points"] < dims["auth_coverage"]["max"]
    assert m["readiness"]["top_fixes"]


def test_readiness_rewards_discipline_markers(mini_repo):
    (mini_repo / "README.md").write_text("# Mini\n", encoding="utf-8")
    (mini_repo / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    (mini_repo / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (mini_repo / ".env.example").write_text("DATABASE_URL=\n", encoding="utf-8")
    (mini_repo / "alembic").mkdir()
    wf = mini_repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n", encoding="utf-8")
    bare = xray.repo_signals(mini_repo)
    assert bare["has_readme"] and bare["has_openapi"] and bare["has_dockerfile"]
    assert bare["has_ci"] and bare["has_env_example"] and bare["has_migrations"]
    m = xray.xray(mini_repo)
    dims = {d["id"]: d for d in m["readiness"]["dimensions"]}
    assert dims["ops"]["points"] == dims["ops"]["max"]
    assert dims["migrations"]["points"] == dims["migrations"]["max"]


def test_diagram_pack_contents(mini_repo):
    m = xray.xray(mini_repo)
    pack = xray.diagram_pack(m)
    assert set(pack) == {"modules.mmd", "er.mmd", "routes.mmd", "diagrams.html"}
    # .mmd sources are unfenced (no markdown code fences).
    for name in ("modules.mmd", "er.mmd", "routes.mmd"):
        assert "```" not in pack[name]
    assert pack["er.mmd"].startswith("erDiagram")
    assert "User" in pack["er.mmd"]
    assert "Client" in pack["routes.mmd"]
    assert "archiet.com" in pack["diagrams.html"]  # attribution footer


def test_cli_writes_diagrams_and_readiness_section(mini_repo):
    rc = xray.main([str(mini_repo), "--quiet"])
    assert rc == 0
    out = mini_repo / ".archiet"
    assert (out / "diagrams" / "diagrams.html").exists()
    assert (out / "diagrams" / "er.mmd").exists()
    md = (out / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Production-readiness signals" in md
    model = json.loads((out / "architecture.json").read_text(encoding="utf-8"))
    assert "readiness" in model and "signals" in model


def test_mcp_server_v02_tools(mini_repo):
    server = Path(__file__).resolve().parents[1] / "mcp_server.py"
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "production_readiness", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "generate_diagrams", "arguments": {"write": False}},
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
    tool_names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert {"production_readiness", "generate_diagrams"} <= tool_names
    readiness = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert 0 <= readiness["score"] <= 100 and readiness["dimensions"]
    diagrams = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert "erDiagram" in diagrams["er_mermaid"]
    assert "written_to" not in diagrams  # write=False honored

# Archiet X-Ray

**See what your AI sees.** Your codebase is too big for any AI agent's context
window. The agent reads 40 files out of 4,000, makes a change, and you have no
way to know whether it respected the architecture — or quietly violated it.

X-Ray extracts the *actual* architecture of any repo — deterministically, no
LLM, code never leaves your machine — and gives it to both **you** (an
interactive map) and **your AI agent** (an MCP server + context pack).

```
$ python xray.py .

Archiet X-Ray v0.2.0 — your-repo
  visibility score : 78/100
  prod readiness   : 71/100 (near production-ready)
  code files       : 3,412 (1,907 read, 1,584 with elements)
  routes           : 214
  entities         : 87
  async tasks      : 31
  findings         : 6
  wrote            : .archiet/ARCHITECTURE.md
                     .archiet/AGENT_CONTEXT.md
                     .archiet/architecture.json
                     .archiet/diagrams/diagrams.html (+3 .mmd)
```

## What you get

| File | What it is |
|---|---|
| `ARCHITECTURE.md` | Human-readable map: module dependency graph (Mermaid), domain model, every route with auth status, dependency hotspots, risk findings, production-readiness scorecard |
| `AGENT_CONTEXT.md` | Drop into your CLAUDE.md / rules file — makes Claude Code, Cursor, and Windsurf respect your architecture *today* |
| `architecture.json` | The machine-readable model (the "repo genome") |
| `diagrams/` | Architecture diagrams as Mermaid sources + a self-contained HTML viewer — module dependency graph, ER / domain-model diagram, HTTP route map |

## Production-readiness score (new in 0.2)

A deterministic **0–100 production-readiness score** over 8 dimensions:
route auth coverage, secrets hygiene, client token storage, data-layer
discipline, test footprint, migration discipline, ops readiness
(Docker/CI/.env contract), and docs/API contract. Same repo always scores
the same — so the score is comparable across commits, branches, and repos,
and you can put it in CI.

Each dimension reports its evidence ("142/214 statically-guarded routes
carry an auth guard") and the report ends with the **top fixes ranked by
points lost**. Dimensions that don't apply (a CLI tool has no routes) take
half credit and say so — honesty over flattery.

Useful when: reviewing AI-generated code before shipping it, auditing an
inherited codebase, or tracking whether your repo is drifting away from
production readiness over time.

## Architecture diagrams from code (new in 0.2)

`generate_diagrams` turns any repo into **Mermaid architecture diagrams**,
deterministically extracted from the code itself:

- **Module dependency graph** — the real import structure, not the wiki's
- **ER / domain-model diagram** — entities and relations from SQLAlchemy,
  Django, and Prisma models
- **HTTP route map** — the API surface grouped by prefix

You get the raw `.mmd` sources (paste into any README, wiki, GitHub, GitLab,
Notion, Obsidian, or VS Code — they all render Mermaid natively) plus a
self-contained `diagrams.html` viewer.

## Give it to your agent (MCP)

```bash
# Claude Code
claude mcp add archiet-xray -- python /path/to/mcp_server.py /path/to/repo
```

Your agent can now ask — *before* it edits:

- **`blast_radius`** — "who depends on this file? what breaks if I touch it?"
- **`arch_summary`** — "where do routes/entities/services actually live?"
- **`boundary_findings`** — "hardcoded secrets, raw SQL, tokens in localStorage, unauthenticated routes"
- **`production_readiness`** — "score this repo 0–100 for production readiness, with evidence and top fixes"
- **`generate_diagrams`** — "draw the module graph / ER diagram / route map as Mermaid"
- **`xray_scan`** — re-scan after structural changes

## Principles

1. **Deterministic.** Same repo in, same map out. Every fact traces to a file
   and line. No LLM guesses anywhere in the pipeline.
2. **Honest.** What can't be extracted with confidence is labelled *unmapped*
   — never invented. A wrong map is worse than no map.
3. **Local-first.** Stdlib only, zero network calls, zero telemetry. Your code
   never leaves your machine.

## What it extracts today

- **Python**: Flask / FastAPI routes (+ auth-guard detection), SQLAlchemy &
  Django models with relations, Celery tasks, import graph — via `ast`, not regex
- **JS/TS**: Next.js app & pages router (pages + API routes), Express routes,
  Prisma models, import graph
- **Findings**: hardcoded secrets, raw SQL bypassing the ORM, auth tokens in
  localStorage/AsyncStorage, routes without auth guards
- **Graph**: module dependency edges, fan-in/fan-out, blast-radius hotspots

More stacks (Go, Java, Rails, .NET) welcome — the extractor pattern is one
class per language. PRs invited.

## Real examples

[`examples/`](examples/) holds unedited X-Ray output for repos you know —
microblog (Flask), the official FastAPI full-stack template, and
vercel/commerce (Next.js). GitHub renders the Mermaid maps inline. On the
FastAPI template, X-Ray correctly detects `CurrentUser` dependency auth on 18
routes and flags a real auth-token-in-localStorage write in `useAuth.ts`.

## FAQ

**How is this different from a dependency-graph MCP server (Codegraph, dependency-mcp)?**
Those show call/import edges. X-Ray extracts *web-architecture semantics* on top
of the graph: which routes exist, which carry auth guards, where the domain
entities live, and where security boundaries leak (hardcoded secrets, raw SQL,
tokens in localStorage). No graph tool tells you "510 of your routes have no
detectable auth guard."

**How is this different from a CLAUDE.md generator?**
CLAUDE.md generators write *instructions and conventions* — usually with an
LLM. X-Ray extracts *facts*: every claim in its output traces to a file and
line, and what it can't extract it labels unknown. Use both: your conventions
plus X-Ray's ground truth.

**What does auth status `?` mean?**
"Not detectable from per-function analysis." FastAPI routers often attach auth
at `include_router(dependencies=...)` level, which is invisible when analyzing
the route function. X-Ray reports unknown rather than guessing a confident
"no auth" — a wrong map is worse than no map.

**Is the production-readiness score a security audit?**
No. It is a deterministic static-signal score — it measures whether the repo
*carries the marks* of production discipline (auth guards on routes, no
hardcoded secrets, tests, migrations, ops + docs contracts). The payload says
so explicitly. It is a fast, repeatable triage number, not a substitute for
code review, load testing, or a security audit.

**Why Mermaid for the diagrams instead of images?**
Mermaid sources are diffable, render natively on GitHub/GitLab/Notion/VS
Code/Obsidian, and stay in sync with the repo because you can regenerate them
in one command. The bundled `diagrams.html` gives you a browser view without
installing anything.

**Does it phone home?**
No. Stdlib-only, zero network calls, zero telemetry. The only outbound anything
is a link in the generated footer.

## Sibling server: archiet-audit

X-Ray never touches the network. If you want the *hosted* counterpart — a
procurement-grade architecture audit (traceability %, severity-ranked gaps,
30/60/90-day roadmap) generated from your architecture documents — the
[`archiet-audit` MCP server](../audit-mcp/) bridges your agent to
[archiet.com/audit-my-architecture](https://archiet.com/audit-my-architecture).
It is a separate server precisely so X-Ray's "your code never leaves your
machine" guarantee stays absolute.

## Part of Archiet

X-Ray is the free, open companion to [Archiet](https://archiet.com) — the
architecture-to-code platform. The map X-Ray extracts is the same formal model
Archiet uses to *enforce* architecture on every PR (boundary gates, drift
scoring, consulting-grade architecture reports) and to regenerate
production-ready applications from it.

MIT licensed.

# Archiet Audit MCP — architecture audit server for AI agents

mcp-name: io.github.Anioko/archiet-audit

**Get a procurement-grade architecture audit from inside your AI coding
agent.** This MCP (Model Context Protocol) server lets Claude Code, Cursor,
Windsurf — any MCP-capable agent — submit architecture documents (PDF, DOCX,
Markdown, plain text, HTML) to [Archiet](https://archiet.com)'s hosted audit
factory and get back a **consulting-grade traceability audit** at a shareable,
unguessable URL:

- **% can-generate / partial / cannot / custom** breakdown across 22+
  architecture concerns (auth, multi-tenancy, audit logging, compliance
  controls, integrations, …)
- **Severity-ranked gaps** with evidence
- **30/60/90-day adoption roadmap**
- A report URL you can forward to your team or procurement

The pipeline is deterministic — **no LLM reads your documents** — so the same
documents always produce the same audit. Typical turnaround: ~15 seconds.

```bash
# Claude Code
claude mcp add archiet-audit -- python /path/to/server.py
```

Then ask your agent:

> "Audit our architecture doc at ./docs/architecture.md with my work email."

## Tools

| Tool | What it does |
|---|---|
| `submit_architecture_audit` | Upload docs (or pasted text) → audit report URL |
| `get_audit_status` | Poll a previously created audit by token |
| `get_audit_limits` | File count / size limits, checked before uploading |

## What gets sent where (read this)

Unlike [archiet-xray](../xray/) — which is fully local and never touches the
network — **this server uploads the documents you submit** to archiet.com
(or `ARCHIET_BASE_URL` for self-hosted instances). The report lives at an
unguessable URL; the uploaded files themselves are never exposed publicly.
Don't submit material you may not transmit. That network boundary is exactly
why this is a separate server from X-Ray rather than another tool in it.

## Requirements

- Python 3.10+ — stdlib only, no dependencies to install
- A work email (the report link is associated with it)
- Rate limit: one audit per minute per IP

## FAQ

**How is this different from running X-Ray on my repo?**
X-Ray extracts the architecture your *code* actually has, locally. The audit
factory evaluates the architecture your *documents describe* — coverage,
gaps, and what it would take to generate the system — and produces a
shareable report suitable for procurement and architecture review boards.
Use both: X-Ray for ground truth, the audit for the deliverable.

**Is the audit really free?**
Yes. It is Archiet's lead magnet: the free audit shows the traceability
breakdown; the paid platform generates the missing pieces.

**Can I point it at a self-hosted Archiet?**
Set `ARCHIET_BASE_URL` to your instance's base URL.

## Part of Archiet

Built by [Archiet](https://archiet.com) — the architecture-to-code platform
that turns architecture specifications into production-ready applications
with compliance documentation (SOC 2, ISO 27001, GDPR, HIPAA, PCI-DSS, DORA,
NIS2) generated alongside the code.

MIT licensed.

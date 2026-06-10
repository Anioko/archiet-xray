# Examples — real X-Ray output on repos you know

Each directory contains the unedited output of `archiet-xray` run against a
well-known open-source project (shallow clone, June 2026). GitHub renders the
Mermaid maps inline — click any `ARCHITECTURE.md`.

| Project | Stack | Highlights |
|---|---|---|
| [microblog](microblog/ARCHITECTURE.md) | Flask + SQLAlchemy | 27 routes with auth-guard status (21 guarded, 6 public — the public ones are login/register, exactly right), 5 entities with relations |
| [full-stack-fastapi-template](full-stack-fastapi-template/ARCHITECTURE.md) | FastAPI + React | Detects `CurrentUser`/superuser dependency auth on 18 routes; honestly reports `?` where router-level config is invisible. Also flagged a real `localStorage` token write in `useAuth.ts` |
| [commerce](commerce/ARCHITECTURE.md) | Next.js (vercel/commerce) | App-router page map including dynamic segments (`/product/:handle`) |

Honesty notes: auth status `?` means "not detectable from per-function
analysis" (e.g. FastAPI `include_router(dependencies=...)`) — X-Ray never
guesses. Findings in test files are downgraded to `info`.

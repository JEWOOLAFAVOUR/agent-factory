# agent-factory

A small monorepo where I build practical AI agents that actually run somewhere. Research pipelines live in Python, delivery lives on Cloudflare Workers + Telegram.

Right now that's two projects: NewUpdater (tech news digest, 3x daily) and RepoRadar (GitHub release radar, in progress). The layout is set up so adding a third one doesn't mean rewiring the first two.

## What's inside

```
agent-factory/
  projects/
    newupdater/        # Python research pipeline (LangChain + LangGraph)
    reporadar/         # placeholder, GitHub monitoring coming next
  infrastructure/
    cloudflare/
      newupdater-bot/  # Worker: Telegram webhook, cron digests, Groq summaries
  shared/
    agent_core/        # placeholder for code every agent reuses
  src/                 # root package, mostly workspace glue for now
```

| Project | What it does | Status |
|---|---|---|
| NewUpdater | Collects tech news (Google News, Bluesky, X), ranks it, sends a Telegram digest morning / afternoon / night | Working locally, Worker scaffolded |
| RepoRadar | Watches GitHub repos for releases and meaningful changes, sends a daily digest | Not started |

## How it fits together

- Python does the research. `projects/newupdater` fetches sources, dedups, ranks, and can call Groq through LangChain. Good for experimenting.
- The Worker does the delivery. `infrastructure/cloudflare/newupdater-bot` owns the Telegram webhook (`/latest`, `/start`), the 3x-day cron, dedup in KV, and the final message formatting. It re-implements the fetch + rank in TypeScript so it can run on its own schedule without my laptop.
- Nothing at the repo root runs in production. Each deployable has its own config and lockfile, so deploying the bot can't break the Python side and vice versa.

## Getting started

Prereqs: Python 3.12 + `uv`, Node 20+ for the Worker.

```bash
# python pipeline
uv sync
uv run python projects/newupdater/inspect_tool.py

# worker (from its own folder)
cd infrastructure/cloudflare/newupdater-bot
cp .dev.vars.example .dev.vars   # fill in tokens, never commit .dev.vars
npm install
npm run typecheck
npx wrangler dev
```

Secrets live in two places and both stay out of git: a `.env` next to the Python code, and `.dev.vars` / `wrangler secret` for the Worker. If you need an example value, commit a `.example` file, not the real one.

To receive Telegram messages: create a bot with BotFather, get your chat id from `getUpdates`, then point the webhook at `/telegram/webhook`. The preview endpoint (`GET /digest/preview?topic=AI agents`) is the safe way to test without sending anything.

## Adding a new project

1. Copy the shape: `projects/<name>/` for logic, `infrastructure/cloudflare/<name>-bot/` only if it needs its own Worker.
2. Give it its own `pyproject.toml` (or `package.json`), its own `wrangler.toml` if it deploys, and its own KV/naming prefix. Don't import across projects except through `shared/agent_core`.
3. Add a row to the table above and a 5-line section under its folder. Keep the root README short.
4. Add the workspace member (`tool.uv.workspace`) or install the Worker separately. Root stays glue, never logic.

## How deploys stay independent

- One `wrangler.toml` per Worker, nothing deploy-related at the root. No root GitHub workflow that deploys everything at once.
- Separate lockfiles: `uv.lock` for Python, `package-lock.json` per Worker. Bumping a dep in one project doesn't touch the others.
- KV keys are prefixed per service (`seen:` in `SEEN_KV` belongs to newupdater-bot; a new bot gets its own namespace or prefix).
- Cron schedules live with the Worker that owns them (`0 7,12,19 * * *` for the digests). Changing digest times never touches RepoRadar.
- The two things most likely to bite later: committing `.dev.vars` / `.env` by accident (both are gitignored — keep it that way), and sharing one KV namespace across bots without prefixes (don't).

## Status and next steps

- [x] NewUpdater research pipeline runs (Google News + Bluesky + X verified)
- [x] Worker scaffold typechecks (webhook, cron, dedup, Groq summary)
- [ ] Create KV namespace, set secrets, first deploy + webhook
- [ ] Tune topics and digest times
- [ ] Start RepoRadar using the same pattern

# InYourDay Agent Workspace

This directory contains long-running nanobot role instances and shared knowledge for InYourDay.

## Roles

- `operator`: overall ecommerce operator and coordinator.
- `sourcer`: 1688 sourcing and supplier observation.
- `screening`: product screening and trust-risk triage.
- `image`: image briefs, generated image direction, and fidelity QA.
- `copywriter`: titles, product copy, SEO, and collection language.
- `listing`: Medusa draft/listing payload preparation.
- `qa`: product page QA, publish checks, rollback notes.

Each role has its own `config.json` and `workspace/` with `SOUL.md`, `USER.md`, `AGENTS.md`, `HEARTBEAT.md`, `memory/`, and `skills/`.

## Shared Knowledge

`knowledge/` is the repository source of truth for GBrain pages. Sync it into GBrain with:

```bash
scripts/sync-gbrain-knowledge.sh
```

Secrets are passed via environment variables, not committed.

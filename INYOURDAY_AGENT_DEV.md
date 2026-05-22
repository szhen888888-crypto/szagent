# InYourDay Agent Development Notes

## Repositories

- `nanobot/`: fresh upstream source checkout for the nanobot runtime.
- `hermes-agent-reference/`: reference repository for CEO-agent patterns, self-improvement, skills, memory, cron, and messaging ideas.
- `inyourday/operator/`: long-running InYourDay operator agent instance with its own config and workspace.

## Local Environment

The `nanobot` repository requires Python 3.11+.

This workspace has:

- `uv 0.11.15`
- `python3.11 3.11.15`
- `python3.12 3.12.13`
- system `python3 3.9.6`, which is too old for nanobot.

Use the repository-local virtual environment:

```bash
cd /Users/suzhen/Desktop/szagent/nanobot
uv venv --python 3.11 .venv
uv pip install -e '.[dev]'
```

Run commands through `.venv/bin/...` unless the environment is activated.

```bash
.venv/bin/nanobot --version
.venv/bin/pytest tests/test_package_version.py tests/test_nanobot_facade.py tests/agent/test_tool_loader_scopes.py -v
```

## Current Verification

- `nanobot` CLI works: `nanobot v0.2.0`.
- SDK facade imports successfully: `from nanobot.nanobot import Nanobot`.
- Smoke tests passed: `18 passed`.
- Targeted `ruff` check surfaced an upstream issue in `nanobot/agent/tools/registry.py` (`_HINT` variable naming). It is not changed yet because it is upstream code and not required for initial setup.

## GBrain Setup

- Local GBrain is installed at `/Users/suzhen/gbrain`.
- Local PGLite brain is initialized at `/Users/suzhen/.gbrain/brain.pglite`.
- InYourDay knowledge source lives in repo root `knowledge/` and is synced into `inyourday/...` GBrain slugs with `scripts/sync-gbrain-knowledge.sh`.
- GBrain embedding now works through Aliyun DashScope / Bailian using its OpenAI-compatible endpoint.
- Local GBrain has a small patch in `/Users/suzhen/gbrain/src/core/embedding.ts` so the embedding model, dimensions, and batch size can be configured with environment variables:
  - `GBRAIN_EMBED_MODEL`
  - `GBRAIN_EMBED_DIMENSIONS`
  - `GBRAIN_EMBED_BATCH_SIZE`
- Working embedding settings:
  - `OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
  - `GBRAIN_EMBED_MODEL=text-embedding-v4`
  - `GBRAIN_EMBED_DIMENSIONS=1536`
  - `GBRAIN_EMBED_BATCH_SIZE=10`
- Do not commit or print the API key. Pass it through `OPENAI_API_KEY` when running GBrain commands.
- Current stats after embedding: `13` pages, `13` chunks, `13` embedded chunks.
- Use `gbrain query ...` for semantic/hybrid retrieval. `gbrain search ...` is keyword-only full-text search and may return no results for English paraphrases.
- Use `scripts/run-gbrain-dream.sh` for maintenance. It skips upstream `sync` by default because full repo sync would import unrelated Markdown files; use `--full` only intentionally.

## Working Architecture Direction

The first InYourDay implementation should use a database-state-driven parallel worker model, not a sequential multi-agent SOP.

Core idea:

- Postgres stores product pipeline state.
- Each worker independently claims tasks matching its stage.
- Workers record step progress after each operation.
- Recovery resumes from the last successful step.
- Assets are written to structured product folders and indexed in Postgres.
- Hermes can later act as CEO/reference brain, but nanobot is the worker runtime to modify first.

## Correct Nanobot Mode

Nanobot should be used as a long-running instance, not primarily as an ad-hoc worker code template.

The correct instance structure is:

```text
inyourday/operator/
  config.json
  workspace/
    SOUL.md
    USER.md
    HEARTBEAT.md
    memory/
      MEMORY.md
      history.jsonl
    skills/
```

Current instance:

- Config: `/Users/suzhen/Desktop/szagent/inyourday/operator/config.json`
- Workspace: `/Users/suzhen/Desktop/szagent/inyourday/operator/workspace`
- Bot name: `InYourDay Agent`
- Provider: `dashscope`
- Model: `qwen-plus`
- Secret handling: config uses `${DASHSCOPE_API_KEY}` and does not store the key directly.
- Tool safety: `restrictToWorkspace=true`, `exec.enable=false`.
- Skills are intentionally empty until the user provides or approves specific skills.

Run the long-lived instance from the fresh nanobot checkout:

```bash
cd /Users/suzhen/Desktop/szagent/nanobot
DASHSCOPE_API_KEY='<aliyun dashscope key>' .venv/bin/nanobot agent \
  --config /Users/suzhen/Desktop/szagent/inyourday/operator/config.json
```

One-off smoke test that already passed:

```bash
DASHSCOPE_API_KEY='<aliyun dashscope key>' .venv/bin/nanobot agent \
  --config /Users/suzhen/Desktop/szagent/inyourday/operator/config.json \
  --message '只回复 OK，确认你读取的是 InYourDay 长期实例。'
```

Result: the agent responded `OK` under the `IYD InYourDay Agent` identity.

Next implementation step: add durable skills and workspace instructions first, then later connect database-backed product pipeline tools/MCP servers so the long-running instance can claim and process pipeline tasks.

## Suggested Product Asset Layout

```text
assets/products/{product_pipeline_item_id}/
  source/
  images/
    briefs/
    generated/
    selected/
    rejected/
    prompts/
  copy/
  qa/
    screenshots/
  publish/
  reports/
  logs/
  archive/
```

## Suggested Core Tables

- `product_pipeline_items`: one row per product candidate and stage statuses.
- `agent_stage_tasks`: one row per stage task instance.
- `agent_task_steps`: one row per recoverable operation.
- `product_assets`: file/object storage index.
- `product_pipeline_events`: state transition and audit event log.
- `agent_run_logs`: optional LLM/tool-call trace logs.

## Next Step

Start by creating the InYourDay worker layer with a minimal local SQLite/Postgres-compatible abstraction, then wire it into nanobot's SDK runner and hook system.

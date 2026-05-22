# szagent

InYourDay agent workspace.

## Structure

- `inyourday/knowledge/`: Markdown source of truth for GBrain knowledge pages.
- `inyourday/{role}/`: long-running nanobot role instances.
- `config/base.nanobot.json`: global nanobot defaults.
- `config/roles/{role}.json`: per-role config overrides.
- `config/generated/`: generated runtime configs, ignored by git.
- `.env`: local secrets and rare overrides, ignored by git.
- `.env.example`: committed environment template.
- `scripts/sync-gbrain-knowledge.sh`: syncs repo knowledge files into GBrain.
- `references/`: local third-party source checkouts, ignored by git.

## Roles

- `operator`
- `sourcer`
- `screening`
- `image`
- `copywriter`
- `listing`
- `qa`

Run a role:

```bash
cp .env.example .env
# fill .env with local secrets
scripts/run-role.sh operator
```

`.env` should stay minimal. Defaults live in `config/base.nanobot.json` and scripts; role-specific differences live in `config/roles/{role}.json`.

Run a one-off message:

```bash
scripts/run-role.sh screening "按 product-screening skill 总结筛选标准"
```

Generate runtime configs manually:

```bash
node scripts/generate-nanobot-configs.mjs
```

Sync knowledge into GBrain:

```bash
./scripts/sync-gbrain-knowledge.sh
```

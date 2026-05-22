# szagent

InYourDay agent workspace.

## Structure

- `knowledge/`: Markdown source of truth for GBrain knowledge pages.
- `inyourday/{role}/`: long-running nanobot employee/role instances only.
- `config/base.nanobot.json`: global nanobot defaults.
- `config/roles/{role}.json`: per-role config overrides.
- `config/generated/`: generated runtime configs, ignored by git.
- `.env`: local secrets and rare overrides, ignored by git.
- `.env.example`: committed environment template.
- `scripts/sync-gbrain-knowledge.sh`: syncs repo knowledge files into GBrain.
- `scripts/run-gbrain-dream.sh`: runs safe GBrain maintenance for this repo.
- `scripts/make-image-preview.mjs`: creates compressed image previews with `sharp`.
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
scripts/run-role.sh screening "总结当前角色的职责"
```

Generate runtime configs manually:

```bash
node scripts/generate-nanobot-configs.mjs
```

Sync knowledge into GBrain:

```bash
./scripts/sync-gbrain-knowledge.sh
```

Run safe GBrain maintenance:

```bash
./scripts/run-gbrain-dream.sh --dry-run --json
./scripts/run-gbrain-dream.sh --sync-first
```

The safe maintenance script skips upstream `sync` by default because this repo maps only `knowledge/` into `inyourday/...` GBrain pages. Use `--full` only if you intentionally want GBrain to scan the entire git repository.

Create compressed image previews before agent visual review:

```bash
npm run image:preview -- path/to/image.jpg preview
npm run image:preview -- path/to/image.jpg thumb
npm run image:preview -- path/to/image.jpg qa
```

Preview outputs are written to `assets/previews/` and ignored by git.

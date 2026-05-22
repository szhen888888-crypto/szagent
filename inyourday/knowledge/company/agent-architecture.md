---
type: architecture
title: Agent Architecture
owner: operator
status: active
updated: '2026-05-21T00:00:00.000Z'
tags:
  - agents
  - architecture
  - inyourday
  - nanobot
---

# Agent Architecture

## Summary

InYourDay uses GBrain for shared long-term knowledge, Postgres for operational truth, and nanobot long-running instances for role-specific execution.

## Core Components

- GBrain: durable shared knowledge, rules, gaps, learnings, and reusable heuristics.
- Postgres: product pipeline state, task claims, step progress, audit events, and asset indexes.
- Nanobot: long-running role instances with `SOUL.md`, `USER.md`, `AGENTS.md`, memory, and skills.
- Hermes: future CEO/self-improving brain reference, not the first worker runtime.
- MedusaJS: commerce backend.
- Feishu: future office/human engagement channel.

## Operating Model

- Do not use a MetaGPT-style serial SOP chain as the primary execution model.
- Workers claim tasks by database status instead of waiting on each other directly.
- State is the handoff mechanism.
- Recovery relies on task step records and idempotent business operations, not hidden agent memory.

## Nanobot Instance Layout

- Instances should live under `inyourday/{role}/`.
- Each role owns its own `config.json` and `workspace/`.
- Shared business knowledge belongs in GBrain and `inyourday/shared/`, not inside only one role.

## Change Log

- 2026-05-21: Created.

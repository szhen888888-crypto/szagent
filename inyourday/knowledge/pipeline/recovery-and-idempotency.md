---
type: pipeline-policy
title: Recovery And Idempotency
owner: operator
status: active
updated: '2026-05-21T00:00:00.000Z'
tags:
  - idempotency
  - inyourday
  - pipeline
  - recovery
---

# Recovery and Idempotency

## Summary

Agents should recover from interruptions by reading task step records and business state, not by depending on hidden conversation memory.

## Tables

- `agent_stage_tasks`: one row per stage task instance.
- `agent_task_steps`: one row per recoverable operation.
- `product_pipeline_events`: status transitions and audit events.
- `product_assets`: generated/source asset metadata and file indexes.

## Rules

- Record a step after each meaningful operation.
- Before creating external objects, check whether they already exist.
- Never overwrite source assets.
- Save prompts, generated outputs, selected/rejected assets, QA screenshots, and publish payloads.
- Completed tasks should be archived, not deleted.

## Examples

- Before creating a Medusa draft product, check whether `medusa_product_id` already exists.
- Before generating a new image version, check existing image assets and prompt records.
- On retry, resume from the last successful step rather than restarting blindly.

## Change Log

- 2026-05-21: Created.

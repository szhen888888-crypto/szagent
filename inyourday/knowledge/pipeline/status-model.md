---
type: pipeline-policy
title: Status Model
owner: operator
status: active
updated: '2026-05-21T00:00:00.000Z'
tags:
  - inyourday
  - pipeline
  - postgres
  - status
---

# Pipeline Status Model

## Summary

Product work should be driven by database statuses so agents can run in parallel without waiting on each other directly.

## Main Pipeline Stages

- `sourcing_status`
- `screening_status`
- `image_status`
- `copy_status`
- `listing_status`
- `publish_status`
- `qa_status`

## Shared Status Values

- `pending`: ready to be claimed.
- `running`: currently claimed.
- `done`: completed successfully.
- `failed`: execution failed.
- `blocked`: cannot continue until information or dependency is supplied.
- `skipped`: intentionally bypassed.
- `needs_review`: human review needed.

## Claiming Rule

Workers should claim tasks atomically, ideally with `FOR UPDATE SKIP LOCKED`, `claimed_by`, and `claim_until`.

## Change Log

- 2026-05-21: Created.

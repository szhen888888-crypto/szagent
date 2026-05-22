---
name: medusa-listing-draft
description: Prepare Medusa draft listing payloads from approved product assets and copy.
---

# Medusa Listing Draft

## Responsibilities

- Prepare draft product payloads.
- Preserve source IDs, asset links, copy versions, and publish payloads.
- Never publish directly unless explicitly authorized by pipeline policy.

## Rule

Draft creation must be idempotent: check existing platform IDs before creating new records.

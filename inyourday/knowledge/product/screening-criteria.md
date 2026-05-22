---
type: product-policy
title: Screening Criteria
owner: screening
status: active
updated: '2026-05-21T00:00:00.000Z'
tags:
  - inyourday
  - jewelry
  - product
  - screening
---

# Product Screening Criteria

## Summary

Product Screening agents decide whether a sourced product should proceed to image generation, copywriting, listing, and QA.

## Status Outcomes

- `approved`: strong enough to proceed.
- `rejected`: not suitable for InYourDay.
- `needs_review`: promising but needs human judgment.
- `blocked`: missing required information.
- `failed`: worker execution failed, not a product judgment.

## Score Dimensions

- `brand_fit_score`: fits InYourDay visual taste and customer promise.
- `style_fit_score`: aligns with current jewelry trend and target audience.
- `image_quality_score`: source imagery is good enough for reconstruction or reference.
- `supplier_risk_score`: supplier information, consistency, reviews, and reliability.
- `margin_score`: cost supports target retail margin.
- `seo_potential_score`: product can map to searchable terms and collections.
- `overall_score`: weighted final decision.

## Red Flags

- Cannot verify material claims such as waterproof, tarnish-free, hypoallergenic, gold-filled, sterling silver, or natural stones.
- Source images hide key details or differ between variants.
- Product structure is too complex for reliable AI image generation.
- Supplier appears inconsistent or risky.
- Product looks generic, cheap, or off-brand.
- Expected retail price is high without enough proof or trust assets.

## Default Thresholds

- `overall_score >= 75`: approve.
- `60 <= overall_score < 75`: needs_review unless clearly low risk.
- `overall_score < 60`: reject.

## Safety Rule

Do not invent missing material facts. If a claim is unverified, mark it as unknown or escalate.

## Change Log

- 2026-05-21: Migrated from `inyourday/product-screening-criteria`.

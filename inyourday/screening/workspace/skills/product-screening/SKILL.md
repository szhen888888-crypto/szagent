---
name: product-screening
description: Screen 1688 jewelry candidates for brand fit, image feasibility, supplier risk, margin, SEO potential, and trust safety.
---

# Product Screening

Use GBrain page `inyourday/product/screening-criteria` as the source of truth.

## Output

Return JSON with:

- `status`
- `overall_score`
- `scores`
- `decision_reasons`
- `red_flags`
- `required_evidence`
- `next_steps`

## Safety

Never approve unsupported material or durability claims.

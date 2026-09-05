---
type: Playbook
title: OKF Maintenance
description: Rules for maintaining Koolbardi's local OKF v0.2 bundle.
tags: [okf, documentation, maintenance]
status: stable
last_updated: 2026-09-02
confidence: high
sources:
  - id: okf-v0-2
    resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
    title: Open Knowledge Format v0.2 specification
    author: org:GoogleCloudPlatform
---
# OKF Maintenance

The `wiki/` directory is Koolbardi's Open Knowledge Format v0.2 bundle.

## Structure

- `index.md`: bundle entry point and progressive-disclosure map.
- `pages/`: focused technical references, runbooks, and campaign records.
- `log.md`: newest-first record of substantial knowledge changes.

Every directory containing Markdown has an `index.md` that links every
immediate child concept. Every non-reserved concept has YAML frontmatter with a
non-empty `type`; use `status` values `draft`, `stable`, or `deprecated` and
`confidence` values `high`, `medium`, or `low`.

## Maintenance

Record durable findings in the same change as the code or operation that
establishes them. Do not silently replace contradictory history: label the old
claim as superseded, retain its context, and add the dated replacement.
Separate concepts when a page mixes independently useful subjects or approaches
50,000 bytes. Use ordinary relative Markdown links, not wiki-link syntax.

Validate structural changes from the repository root:

```bash
python scripts/validate_okf.py wiki
```


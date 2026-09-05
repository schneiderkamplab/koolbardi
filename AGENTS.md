# Agent Operating Notes

Koolbardi uses an Open Knowledge Format (OKF) v0.2 bundle under
[`wiki/`](wiki/index.md). Before substantial work, read the bundle index,
[`wiki/schema.md`](wiki/schema.md), and the relevant page under `wiki/pages/`.

Record durable implementation, data-contract, runtime, recovery, and campaign
knowledge in the bundle in the same turn. Preserve superseded findings with
their date and context. Validate changes with:

```bash
python scripts/validate_okf.py wiki
```


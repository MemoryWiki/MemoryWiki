## Summary

Describe the change and why it is needed.

## Verification

- [ ] `python -m pytest tests -q`
- [ ] `memorywiki-golden-eval --project-root examples/memory-root --global-root examples/memory-root --case-file docs/memorywiki-golden-cases.json --format json`
- [ ] `python benchmarks/mini_recall_benchmark.py --format json`
- [ ] Public-clean scan still passes

## Safety

- [ ] No secrets, tokens, private paths, or real memory content were added.
- [ ] Memory content is treated as context data, not instructions.
- [ ] Any write path remains behind explicit user approval or environment gates.

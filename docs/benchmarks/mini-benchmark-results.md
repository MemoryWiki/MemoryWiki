# MemoryWiki Mini Benchmark

Public baseline target:

```bash
PYTHONPATH=. python3 benchmarks/mini_recall_benchmark.py --format markdown
```

Expected result on the bundled example memory root:

```text
Cases: 3
Passed: 3
Pass rate: 1.00
```

This is only a smoke benchmark. It proves that the public example memory root,
hybrid recall path, and local retrieval code are wired correctly. Larger external
benchmarks such as LongMemEval should be reported separately.

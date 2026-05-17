---
id: source-ingest-provenance
scope: project
title: Source Ingest Provenance
concepts:
  - source-ingest
  - sha256
  - provenance
confidence: 0.82
strength: 0.72
---

Source ingest records SHA256 identifiers and source references for documents
placed inside the memory root `sources/` sandbox. The reference trail is
tamper-evident: if a source changes later, the stored digest no longer matches
the original evidence.

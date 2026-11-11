# ADR 0002 — MUNIN memory boundaries

Status: Accepted for P0 implementation.

Decision: Store technique cards, evidence, failure cases, provenance, and applicability constraints as versioned records. Start with SQLite FTS5; embedding-based retrieval is optional. Use split-aware retrieval policies preventing held-out evaluation answers and writeups entering training memory.

Rationale: actual improvement requires transferable evidence and ablation, not a claim that model weights change.

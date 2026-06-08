# Entity Resolution as Agent Grounding — Episode 1 AIR Outline

**Scope:** Entity-resolution Lessons from the Trenches piece + grounding/identity section of Harness Engineering chapter.

**Voice:** Declarative. No first person. No document self-reference. Banned-phrase list enforced. Napkin AI diagram briefs (no Mermaid in deliverable). Load-bearing hyperlink anchors only.

---

## Section 1: The Identity Problem in Vertical Agents

A vertical agent that ingests real-world entities — publications, companies, people — builds every downstream decision on its internal model of "who is who." When that model is wrong, the agent's outputs are wrong in ways that look correct on the surface.

The Substack recommendation network provides a concrete demonstration. A 2-hop crawl from a single seed publication discovers 110 nodes and 128 edges. The resulting graph renders beautifully. It is also quietly corrupt.

**[Napkin brief: before/after graph comparison — the naive graph with 4 corruption modes annotated vs the resolved graph]**

## Section 2: Four Corruption Modes

The naive graph keys each node on whatever surface identifier the API returns — custom domain, subdomain, author profile URL. This single decision produces four distinct failure modes:

### Mode 1: Split (one entity, multiple nodes)
A publication reachable via its `.substack.com` subdomain, its custom domain, and its author profile page appears as three separate nodes. The graph overstates the network's diversity and understates individual influence.

### Mode 2: Collapse (multiple entities, one node)
Two distinct publications sharing an author ID collapse into a single node when the key falls through to the author-ID level. The graph merges audiences that should remain separate.

### Mode 3: Dropped edges (renamed handle 404s)
A publication that changed its handle returns HTTP 404 under the old URL. The edge pointing to it silently vanishes. The graph understates connectivity.

### Mode 4: Self-loop (alias self-recommendation)
A publication recommends what appears to be a different entity but is actually an alias of itself. The graph contains a meaningless self-referential edge.

## Section 3: The Identity-Resolution Harness

The fix is an identity-resolution layer with three components:

### Canonicalization
Every URL resolves to its publication ID. The `id` field from the publication metadata is the canonical key. URLs that share a publication ID collapse into a single canonical node carrying all member URLs.

### Confidence-Scored Merge with Refuse-to-Guess Gate
Distinct canonical nodes that share an author ID are not automatically merged. A scoring function evaluates merge candidates:

- Shared author: weight 0.3
- Name similarity: weight 0.2 (scaled by SequenceMatcher ratio)
- Maximum possible score from these signals: 0.5

The merge threshold is 0.85. Shared authorship alone (0.3) or even with moderate name similarity (total ~0.43) falls well below threshold. The harness refuses to merge and flags the pair for review.

**[Napkin brief: scoring diagram — signals, weights, threshold line, refuse zone vs merge zone]**

### Replayable Audit Log
Every merge, refusal, alias reattachment, and edge drop is written to a newline-delimited JSON log with the full evidence vector: the signals that triggered the decision, their individual weights, the composite score, and the threshold in force.

The log is the observability surface. Any decision can be re-derived offline from the evidence record alone.

## Section 4: The Determinism SLO

The episode's behavioral SLO: the same input resolves to the same canonical node every run, independent of input ordering.

Verification: two independent resolution passes on the same crawl data produce identical canonical assignments and identical decision logs (after stripping run-specific noise like timestamps and run IDs). Input-order shuffling does not affect the output.

## Section 5: Lessons from the Trenches

### Lesson 1: Surface identifiers are lies
Any identifier derived from a URL, hostname, or display name is a surface. The canonical identifier must come from the source of truth (the publication's own ID), not from the surface through which the agent discovered it.

### Lesson 2: Refuse-to-guess beats confident error
A merge threshold that allows shared authorship alone to trigger a merge will quietly corrupt the graph. The agent must surface uncertainty rather than resolve it with a guess. A flagged pair costs one human review; a confident wrong merge poisons every downstream decision.

### Lesson 3: Observability is not a dashboard added later
The audit log is a first-class output, not a debugging aid. In a build-in-public context, the log IS the content. In a production context, the log is the evidence chain that lets anyone — including the agent itself in a future pass — audit why a node exists.

### Lesson 4: Cache-first is a constraint, not an optimization
Rate-limiting and caching are not performance features. They are the boundary conditions that make the agent safe to run against a real API. Re-runs that hit the network are re-runs that risk getting blocked. Cache-first means the crawl's persistent output is the cache, and everything downstream reads from it.

---

## Placement Notes

- This section anchors the "Identity" responsibility in the Vertical Agent Anatomy
- Links to the Harness Engineering chapter: the harness is the identity-resolution layer itself
- The four corruption modes map directly to the Context Engineering failure class
- The refuse-to-guess gate is the first concrete instance of a behavioral SLO

# substackgraph

A **vertical AI agent** that, given a Substack publication, crawls the recommendation network
around it, resolves publications to canonical entities, and renders a navigable niche graph.

This is a **build-in-public** project for [The AI Runtime](https://theairuntime.substack.com).
The build *is* the product: each episode stages a named failure, ships the harness that fixes it,
and yields the content. See [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md),
[`docs/episode-01-grounding.md`](docs/episode-01-grounding.md), and
[`docs/frameworks.md`](docs/frameworks.md). Operational context lives in [`CLAUDE.md`](CLAUDE.md).

## Episode 1 — The Grounding Break

Scope: **ingestion + identity only**. The pipeline is:

```
seed publication → crawl recommendation edges (2 hops) → resolve entities → render force-directed map
```

The episode deliberately stages an **entity-resolution failure** (the same publication appears as
2–3 nodes, two different newsletters collapse into one via a shared author, renamed handles 404 and
drop their edges, aliases create self-loops), captures the corrupted graph, then fixes it with an
**identity-resolution harness** (canonicalize → confidence-scored merge with a refuse-to-guess gate →
replayable audit log).

## Requirements

- **Python 3.12+** (the `substack-api` dependency requires it). The default `python3` on some systems
  is 3.11 and will not work — use `python3.12` explicitly.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Usage

```bash
# 1. Crawl the 2-hop recommendation neighborhood (cache-first, ≤1 req/sec).
#    Re-runs hit the SQLite cache and make zero network calls.
substackgraph crawl --seed https://theairuntime.substack.com --hops 2

# 2. Render the naive graph — reproduces the corruption (the "before").
substackgraph render-naive

# 3. Run the identity-resolution harness and render the resolved graph (the "after").
#    Writes the replayable decision log to artifacts/logs/decisions.jsonl.
substackgraph render-resolved
```

Artifacts land under `artifacts/` (gitignored):

```
artifacts/
  cache.sqlite              # the cache-first store; the crawl's only persistent output
  logs/decisions.jsonl      # replayable entity-resolution decision log — the episode content
  graphs/naive.html         # the corrupted "before" map
  graphs/resolved.html      # the resolved "after" map
  graphs/screenshots/       # drop manual before/after screenshots here for the thread
```

## Tests

```bash
.venv/bin/pytest
```

The suite runs **fully offline** against a hand-built fixture cache that guarantees all four
corruption modes, so it never needs the network:

- `test_naive_corruption.py` — proves the four failure modes are real (the "before").
- `test_resolve.py` — proves the harness collapses, separates, re-attaches, and de-loops correctly.
- `test_determinism.py` — the episode SLO: the same input resolves to the same canonical node every run.

## Conventions (non-negotiable — see `CLAUDE.md`)

- **Cache-first:** every external call is cached to SQLite before anything touches it.
- **Rate limit ≤ 1 req/sec** to any Substack endpoint.
- **Observability is first-class:** every merge/split/refuse is logged with the triggering evidence.
- **Refuse-to-guess:** below the confidence threshold, the agent refuses and flags for review.
- **Public data only**, research/visualization framing. Subscriber counts are rough estimates.

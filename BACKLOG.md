# substackgraph — Backlog

Shared task board for the autonomous agent team. The **chief** delegates; **data**, **qa**, and
**content** claim tasks assigned to them. This file is the source of truth for what's in flight.

## How agents use this board
- Each task has an **owner** (`@data` / `@qa` / `@content`), a **priority** (P0 highest), and a
  **status**: `ready` → `in-progress` → `review` → `ready-to-merge` → `done` (or `blocked`).
- Claim ONE `ready` task assigned to you, set it `in-progress` with your name, then branch
  `agent/<agent-id>/<task-id>`. After PR + QA pass, chief merges and marks it `done`.
- Only the chief sets a task to `done` (after merge). QA sets `ready-to-merge`.

## Scope guardrail (DO NOT CROSS without Kranthi's say-so)
v0 = **Episode 1: ingestion + identity only**. OUT of scope: embeddings, ranking, outreach
drafting, auth, accounts, hosted UI beyond the local `serve`, monetization. Any task drifting
into these must be parked and surfaced to Kranthi, not implemented.

---

## Episode 1 — The Grounding Break (COMPLETE)

| ID | Task | Owner | Priority | Status |
|----|------|-------|----------|--------|
| E1-01 | Run a fresh real crawl of `theairuntime.substack.com` (2 hops) and confirm cache-first re-runs make zero network calls | @data | P0 | done |
| E1-02 | Audit the decision log: confirm every merge/split/refuse carries triggering evidence; add fields if any are bare | @data | P0 | done |
| E1-03 | Verify the four staged corruption modes still reproduce in `render-naive` against the real crawl (not just fixtures) | @qa | P0 | done |
| E1-04 | Confirm determinism SLO end-to-end: two `render-resolved` runs produce identical canonical assignments | @qa | P0 | done |
| E1-05 | Tune the refuse-to-guess confidence threshold; document the chosen value and show example refusals from the log | @data | P1 | done |
| E1-06 | Link/graph sanity pass on `resolved.html`: no dangling URL-keyed nodes, no orphan edges, no self-loops | @qa | P1 | done |
| E1-07 | Draft the Episode 1 Twitter thread from the real before/after + decision-log numbers | @content | P1 | done |
| E1-08 | Draft the Episode 1 YouTube build-log outline (cold open on the corrupted graph) | @content | P2 | done |
| E1-09 | Draft the AIR section using the `the-ai-runtime` skill voice rules (declarative, Napkin briefs) | @content | P2 | done |
| E1-10 | Capture before/after screenshots into `artifacts/graphs/screenshots/` for the thread | @content | P2 | done |

## Episode 2 — Graph Analytics (COMPLETE — stubs for LLM features, pure graph math done)

| ID | Feature | Description | Status |
|----|---------|-------------|--------|
| E2-01 | Reciprocity gap finder | `substackgraph reciprocity-gaps` — A→B with no B→A, ranked by B in-degree | done |
| E2-02 | Bridge node discovery | `substackgraph bridge-nodes` — pubs connecting clusters | done |
| E2-03 | Warm path finder | `substackgraph warm-path --from <url> --to <url>` | done |
| E2-04 | Cluster map + LLM labels | `substackgraph cluster-map` — greedy modularity communities, stub labels | done |
| E2-05 | Degree centrality ranking | `substackgraph top-nodes --metric degree` | done |
| E2-06 | Audience overlap scoring | `substackgraph overlap --pub <url>` — stub: graph distance proxy. TODO: embeddings | done |
| E2-07 | Voice compatibility scoring | `substackgraph voice-compat --pub-a <url> --pub-b <url>` — stub: keyword overlap. TODO: LLM | done |
| E2-08 | Recommendation quality scoring | Stub: edge weight by recommender selectivity. TODO: LLM warmth scoring | done |
| E2-09 | Niche blind spot detection | `substackgraph blind-spots --cluster <id>` — stub: name keywords. TODO: LLM | done |
| E2-10 | Audience journey matching | `substackgraph journey-match --pub <url>` — stub: name heuristic. TODO: LLM | done |
| E2-11 | Early velocity signal | `substackgraph rising-stars` — stub: in-degree centrality. TODO: real subscriber data | done |
| E2-12 | Counter-intuitive match finder | `substackgraph surprise-matches --pub <url>` — stub: betweenness similarity. TODO: embeddings | done |
| E2-13 | Timing/trigger detection | `substackgraph live-hooks --pub <url>` — stub: cluster proximity. TODO: content fetch | done |

## Episode 3 — Outreach Drafts (E3-01/02 LLM-powered, E3-03 parked)

| ID | Feature | Description | Status |
|----|---------|-------------|--------|
| E3-01 | Collaboration brief generator | `substackgraph collab-brief --pub-a <url> --pub-b <url>` — LLM-powered via claude-haiku-3-5, stub fallback | done |
| E3-02 | Outreach angle suggestions | `substackgraph outreach-angles --pub-a <url> --pub-b <url>` — LLM-powered via claude-haiku-3-5, stub fallback | done |
| E3-03 | Delegated outreach (DIBR-gated) | Agent sends outreach — DIBR properties 2 and 3 must be verified before this ships. **PARKED**: draft generation only, no send automation. | parked |

---

_Conventions live in `CLAUDE.md`. Each agent's autonomous workflow lives in its own AGENT.md
under `~/.openclaw/agents/<agent-id>/agent/`._

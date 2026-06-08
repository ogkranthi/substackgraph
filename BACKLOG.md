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

## Episode 1 — The Grounding Break (CURRENT)

| ID | Task | Owner | Priority | Status |
|----|------|-------|----------|--------|
| E1-01 | Run a fresh real crawl of `theairuntime.substack.com` (2 hops) and confirm cache-first re-runs make zero network calls | @data | P0 | ready |
| E1-02 | Audit the decision log: confirm every merge/split/refuse carries triggering evidence; add fields if any are bare | @data | P0 | ready |
| E1-03 | Verify the four staged corruption modes still reproduce in `render-naive` against the real crawl (not just fixtures) | @qa | P0 | ready |
| E1-04 | Confirm determinism SLO end-to-end: two `render-resolved` runs produce identical canonical assignments | @qa | P0 | ready |
| E1-05 | Tune the refuse-to-guess confidence threshold; document the chosen value and show example refusals from the log | @data | P1 | ready |
| E1-06 | Link/graph sanity pass on `resolved.html`: no dangling URL-keyed nodes, no orphan edges, no self-loops | @qa | P1 | ready |
| E1-07 | Draft the Episode 1 Twitter thread from the real before/after + decision-log numbers | @content | P1 | ready |
| E1-08 | Draft the Episode 1 YouTube build-log outline (cold open on the corrupted graph) | @content | P2 | ready |
| E1-09 | Draft the AIR section using the `the-ai-runtime` skill voice rules (declarative, Napkin briefs) | @content | P2 | ready |
| E1-10 | Capture before/after screenshots into `artifacts/graphs/screenshots/` for the thread | @content | P2 | ready |

## Icebox (future episodes — DO NOT START without Kranthi promoting them)
- Episode 2 — overlap scoring + ranking (the multi-step reasoning chain).
- Episode 3 — outreach drafting / posting (the DIBR action surface).

---

_Conventions live in `CLAUDE.md`. Each agent's autonomous workflow lives in its own AGENT.md
under `~/.openclaw/agents/<agent-id>/agent/`._

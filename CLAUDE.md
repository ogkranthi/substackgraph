# CLAUDE.md — substackgraph

Operational context for this repo. Read `docs/PROJECT_BRIEF.md` for the full why/what,
`docs/episode-01-grounding.md` for the current build, and `docs/frameworks.md` for the
framework lens (the canon itself lives elsewhere — see that file).

## What this is

`substackgraph` is a **vertical AI agent** that, given a Substack publication, crawls the
recommendation network around it, resolves publications to canonical entities, scores
audience overlap, and surfaces ranked recommendation / collaboration partners — rendered as
a navigable niche graph.

## The real goal (read this before optimizing anything)

This is a **build-in-public project**, and the build is the product — not the tool's user base.

- The tool's users are Substack writers. The *content* audience is AI practitioners (readers of
  The AI Runtime). These are different audiences on purpose.
- Growth comes from the **engineering narrative**: each hard sub-problem becomes a Twitter
  thread, a YouTube build-log, and a section of the MRE "Harness Engineering" book chapter.
- Therefore: prioritize work by how rich a *failure-and-harness story* it produces, not by
  product polish. A staged, well-instrumented failure is more valuable than a clean demo.
- Secondary goal: the build is empirical backing for named frameworks (see `docs/frameworks.md`).
  Building it should help resolve open framework questions, not invent new ones.

## Architecture lens (VAA responsibilities)

The agent is structured around the seven Vertical Agent Anatomy responsibilities. Each build
episode stresses one and ships its harness:

- **domain surface** — the Substack recommendation network
- **identity** — resolving a publication to one canonical entity *(Episode 1)*
- **context** — what the agent knows about each node *(Episode 1)*
- **reasoning** — overlap scoring + ranking (the multi-step chain) *(Episode 2)*
- **action** — drafting/sending outreach, posting (delegated) *(Episode 3 — DIBR surface)*
- **harness** — the gates/validation/observability wrapping all of the above
- **audit** — the decision log that makes behavior reconstructable

(VAA layer *names* are still `[VERIFY]` against the canonical AIR piece — use the responsibility
words above until confirmed.)

## Build conventions

- **Language:** Python (3.12+). Single dependency target for the crawler: `requests` (via the
  `substack-api` library); add only what an episode needs.
- **Cache-first:** every external call is cached to SQLite before anything else touches it. Re-runs
  must hit cache, not the network.
- **Rate limit:** ≤ 1 request/sec to any Substack endpoint. Non-negotiable (ToS + politeness).
- **Observability is a first-class feature, not a dashboard you add later.** Every entity-resolution
  merge/split, every match decision, every tool call is logged with the evidence that triggered it,
  in a form you can replay. The logs ARE the content.
- **Refuse-to-guess gates:** when confidence is below threshold (e.g. merging two nodes), the agent
  refuses and flags for review rather than guessing. Surfacing uncertainty beats confident error.
- **Record from the first run.** Screen-record and keep logs from line one. The value of an episode
  is the failure, and you only capture it once.

## Scope discipline

This is weekend-to-few-weekends work, not a startup. For **v0 (Episode 1)** the scope is
ingestion + identity only. Explicitly OUT of v0: embeddings, ranking, outreach drafting, auth,
accounts, hosted UI, monetization. Resist scope creep into any of those until the episode that owns them.

## Data access (summary — full detail in PROJECT_BRIEF)

- No official Substack API. Use the unofficial `/api/v1/` endpoints via `NHagar/substack_api`
  (`pip install substack-api`). `Newsletter.get_recommendations() -> List[Newsletter]` is the edge source.
- Confirm exact endpoint paths / JSON field names from the library source or a live DevTools capture
  before hard-coding them.
- Entity resolution keys: `id`, `subdomain`, `custom_domain`, `author_id`.
- Subscriber counts are **rough estimates only**; paid counts are never exposed. Treat all sizing as
  having error bars.
- Public data only. Frame the project as research/visualization. No paywalled content, no redistribution
  of large content portions. Substack ToS prohibits scraping/crawling — the mitigations above reduce but
  do not eliminate exposure.

## Content pipeline (per episode)

Each episode produces three derivatives with different voice rules:

1. **Twitter thread** — first person, personal build-in-public voice. Lead with the artifact + the twist.
2. **YouTube build-log** — cold open on the failure, screen-recorded debugging, the fix, the principle.
3. **AIR piece / book section** — AIR voice rules apply here and ONLY here: declarative, no first person,
   no document self-reference, banned-phrase list enforced, diagrams as Napkin AI briefs (no Mermaid in
   the deliverable), load-bearing hyperlink anchors only. Source of truth for these rules is the
   `the-ai-runtime` skill, not this repo.

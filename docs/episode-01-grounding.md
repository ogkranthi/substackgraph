# Episode 1 — The Grounding Break

**Working title:** "I built an agent to map the Substack network. It quietly merged 30 newsletters into 4."

**VAA responsibilities exercised:** identity, context.
**Named failure:** entity resolution (a Context Engineering failure).
**Harness:** identity-resolution / grounding layer (Harness Engineering).
**Maturity movement:** level 1 (works on a clean seed) → level 2 (grounded on messy real data).

## What you build (v0)

Ingestion + identity only. Everything else is a later episode.

```
seed publication  →  crawl recommendation edges (2 hops)  →  resolve entities  →  render force-directed map
```

- `substack-api` for edges: `Newsletter.get_recommendations() -> List[Newsletter]`.
- Cache every call to SQLite first; re-runs hit cache.
- Throttle ≤ 1 req/sec.
- Render to a static HTML graph (pyvis or sigma.js).
- Seed on your own niche (AI/tech newsletters) so the map is shareable.

**Out of scope for v0:** embeddings, overlap scoring, ranking, outreach, auth, hosted UI.

## The staged failure (the hook — instrument it, don't hide it)

The graph renders beautifully, then turns out to be lying:

- One publication appears as 2–3 nodes because its `custom_domain`, `.substack.com` `subdomain`,
  and author profile resolved separately.
- Two different newsletters collapse into one because they share an author.
- Renamed handles 404 and silently drop their edges — the graph is missing links it should have.
- Self-loops where a publication "recommends itself" via an alias.

This is the agent's knowledge of *who is who* being wrong (Context Engineering), surfacing as a
visibly corrupted artifact. The collision is concrete: `id` vs `subdomain` vs `custom_domain` vs
`author_id`.

## The harness (the fix and the lesson)

An identity-resolution layer:

1. **Canonicalize** every node to its publication `id`; follow redirects; reconcile the
   `custom_domain` ↔ `subdomain` ↔ `author_id` triad.
2. **Confidence-scored merge with a refuse-to-merge-below-threshold gate** — do not guess; flag
   low-confidence pairs for review.
3. **Observability / audit** — log every merge and split with the evidence that triggered it, replayable.

**SLO for the episode:** graph consistency + correctness — the same input resolves to the same
canonical node every run.

## Content (three surfaces, one build)

- **Twitter thread** (first person): open on the gorgeous map → gut-punch screenshot of the same
  newsletter appearing three times → walk the four collisions with a before/after of corrupted vs
  resolved graph → land on "entity resolution is the unglamorous 80% of agent grounding" → tease Ep 2.
  The before/after image is the restack magnet.
- **YouTube build-log** (~8–12 min): cold open on the broken map → the "wait, why am I in here twice?"
  debugging beat on screen → the fix → the generalizable principle → tease.
- **AIR piece / book section** (AIR voice rules ON here): the entity-resolution Lessons from the
  Trenches piece + the grounding/identity section of the Harness Engineering chapter. Declarative,
  no first person, no self-reference, Napkin AI diagram brief for the before/after, no Mermaid in
  the deliverable.

## Definition of done

- [ ] Crawl + cache working on the AI/tech seed, ≤1 req/sec, re-runs hit cache.
- [ ] Naive graph rendered and the corruption reproduced and captured (screenshot + logs).
- [ ] Resolution harness in place; corrupted nodes correctly merged/split; low-confidence pairs flagged.
- [ ] Decision log replayable.
- [ ] Resolved map exported as a shareable image.
- [ ] Raw failure footage + logs archived for the thread/video.

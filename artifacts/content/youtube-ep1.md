# Episode 1 YouTube Build-Log Outline — The Grounding Break

**Working title:** "I built an agent to map the Substack network. It quietly merged 30 newsletters into 4."

**Target length:** 8-12 minutes

---

## Cold Open (0:00 - 1:00)
- Screen: the resolved graph, zoomed in, looking beautiful
- "I built a tool that maps the Substack recommendation network. 108 publications, 127 edges, one gorgeous force-directed graph."
- Beat. Zoom out.
- "But this is the AFTER. Here's the before."
- Cut to: the naive graph. Zoomed into the corruptions.
- "The same newsletter appearing three times. Two different writers collapsed into one. Edges that just... vanished."

## The Setup (1:00 - 2:30)
- What we're building: seed a Substack publication, crawl 2 hops of recommendations, render the network
- Quick demo: `substackgraph crawl --seed theairuntime.substack.com --hops 2`
- Show the cache: 110 nodes, 128 edges, SQLite cache-first (re-run in 0.4s)
- The pipeline: crawl -> resolve -> render

## The Naive Graph — Where It Goes Wrong (2:30 - 5:00)
- Render the naive graph: `substackgraph render-naive`
- Walk through each corruption mode on screen:
  1. **Split:** One publication reached via subdomain, custom domain, and author profile = 3 nodes
  2. **Collapse:** Two newsletters sharing an author = merged into one node by the author-id fallback
  3. **Dropped edges:** A renamed handle 404s, its edges silently disappear
  4. **Self-loops:** A publication recommends an alias of itself
- Key insight: "The graph LOOKS fine. That's what makes this dangerous."

## The Fix — Identity Resolution Harness (5:00 - 7:30)
- Show the resolver code: canonicalize by publication ID
- The confidence-scored merge: shared author alone scores 0.3, threshold is 0.85
- Live example: "The VC Corner" vs "The Founders Corner" — shared author, score 0.43, REFUSED
- The audit log: every decision carries the triggering evidence
- `substackgraph render-resolved` — the correct graph

## The Proof — Determinism SLO (7:30 - 8:30)
- Run resolution twice, compare outputs
- Identical canonical assignments, identical decision logs
- `substackgraph validate` — PASS: no URL-keyed nodes, no orphan edges, no self-loops
- The before/after side by side

## The Principle (8:30 - 10:00)
- Entity resolution is the unglamorous 80% of agent grounding
- If your agent's sense of "who is who" is wrong, every downstream decision is poisoned
- The refuse-to-guess gate: surfacing uncertainty beats confident error
- The audit log: if you can't replay the decision, you can't trust it

## Tease Episode 2 (10:00 - 10:30)
- Now the map is grounded. Episode 2 makes it useful.
- Reciprocity gaps, bridge nodes, cluster detection, warm-path finding
- Quick flash of: `substackgraph reciprocity-gaps`, `substackgraph cluster-map`

## Outro (10:30 - 11:00)
- Subscribe to The AI Runtime for the full series
- Link to the code (substackgraph repo)
- "The build is the product. See you in Episode 2."

---

## Production Notes
- Screen-record the terminal for all CLI commands
- Before/after screenshots go in artifacts/graphs/screenshots/
- Record the debugging moment when you first notice the corruption
- The "wait, why am I in here twice?" beat is the emotional hook

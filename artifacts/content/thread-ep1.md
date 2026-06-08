# Episode 1 Twitter Thread — The Grounding Break

## Thread

**1/**
I built an AI agent that maps the Substack recommendation network.

108 publications. 127 edges. A beautiful force-directed graph.

Then I looked closer and realized the map was lying to me.

Here's what went wrong, and why entity resolution is the unglamorous 80% of agent grounding.

[screenshot: the resolved graph — gorgeous, colorful, correct]

**2/**
The project: give it any Substack publication, crawl 2 hops of recommendations, and render the network.

Simple pipeline:
seed -> crawl edges -> resolve entities -> render map

I pointed it at my own newsletter (The AI Runtime) and let it run.

**3/**
First crawl: 110 publications discovered, 128 recommendation edges, cached to SQLite.

Re-runs hit the cache and complete in 0.4 seconds. No network calls. Cache-first isn't optional when you're scraping — it's the only responsible architecture.

**4/**
Then I rendered the "naive" graph — keying nodes on whatever surface string the API returned: custom domain, subdomain, author profile URL.

The graph looked fine. Until I zoomed in.

[screenshot: the naive graph with corruption highlighted]

**5/**
The four corruptions hiding in plain sight:

1. One publication appearing as 2-3 nodes (reached via subdomain vs custom domain vs author profile)
2. Two different newsletters collapsing into one (shared author ID)
3. Edges silently disappearing (renamed handles 404)
4. Self-loops (a publication "recommending itself" via an alias)

**6/**
The fix: an identity-resolution harness.

- Canonicalize every URL to its publication ID
- Confidence-scored merge with a refuse-to-guess gate
- A replayable decision log that records the evidence for every merge, split, and refusal

**7/**
Real example from the crawl:

"The VC Corner" and "The Founders Corner" share an author (id: 95342670).

Score: 0.43. Threshold: 0.85.

The harness REFUSED to merge them. That's the whole point — surfacing uncertainty beats confident error.

**8/**
The resolved graph: 108 canonical nodes, 127 edges, 3 audited decisions.

Same data. Correct map. Every decision replayable.

Determinism SLO: two independent runs produce identical canonical assignments. Verified.

[screenshot: before/after side by side]

**9/**
The lesson: entity resolution is the unglamorous 80% of building agents that touch real-world data.

Your agent's knowledge of "who is who" determines whether every downstream decision — ranking, matching, outreach — is built on solid ground or a beautiful lie.

**10/**
This is Episode 1 of a build-in-public series for The AI Runtime.

Next: Episode 2 — graph analytics. Reciprocity gaps, bridge nodes, cluster detection, warm-path finding.

The map is grounded. Now we make it useful.

Follow along: theairuntime.substack.com

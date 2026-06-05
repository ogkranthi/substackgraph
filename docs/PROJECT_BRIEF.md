# substackgraph — Project Brief

## One line

An AI vertical agent that maps the Substack recommendation network around a publication and
surfaces ranked, audience-overlap-scored recommendation/collaboration partners — built in public
as a Harness Engineering case study for The AI Runtime.

## The problem (validated)

Recommendations are the dominant in-platform growth lever on Substack — the network drives roughly
40–50% of new free subscriptions and ~20% of paid across the platform (Substack's own figures), and
in-platform discovery (Notes + Recommendations) became *more* central through 2025–2026 as organic
reach tightened. Yet finding the *right* reciprocal partners is still manual, asymmetric (bigger
publications rarely recommend back), relationship-gated, and unsupported by any intelligence layer.
Substack's native Recommendations tab shows who recommends you and raw subscriptions driven — no fit
scoring, no overlap analysis, no graph, no outreach support.

Demand signals: the manual "build a list of 20–50 partners by audience overlap, not topic overlap"
playbook is a known, paid growth tactic; r/Substack threads on "how to get cross-recommendations from
big accounts" and "the manual grind of cross-posting" draw real engagement; data posts about the
ecosystem ("I analysed 30,000 sponsorships," "I looked at 50 newsletters in X niche") consistently
get shared.

## Honest counter-signals (keep these in view — they shape what we build)

- **Bottleneck is relationships, not discovery.** Finding the target is the cheap step; getting a
  bigger publication to reciprocate is the expensive one a tool can't manufacture. → So position as
  *intelligence and warm-path finding*, not cold-outreach automation.
- **Spam allergy.** The community is hostile to anything transactional/"growth-hacky." → Frame as a
  niche *map* and *warm paths*, not "DM these 25 strangers."
- **Is AI even needed?** A plain directory (Reletter) exists. The defensible AI value is specifically
  embeddings-based *complementary* overlap + LLM rationales + graph structure. → Test that this beats
  a sorted list; if it doesn't, the AI is window dressing.
- **ToS/scraping risk is real, not theoretical.** Mitigations: seed sets, heavy cache, ≤1 req/sec,
  public data only, research framing.
- **Subscriber-count fidelity:** estimates only. All sizing carries error bars.

## Competitive gap

Reletter = directory/search, no graph or AI matchmaking. StackShelf = product showcase. SparkLoop /
Beehiiv Boosts = paid acquisition networks, barely touch Substack-native recommendations. ProDemStack =
a one-off niche map (built with AI assistance — proof the concept is a weekend build), not a self-serve
tool. Nomic Atlas = general semantic map, not productized. **Nobody offers a self-serve tool that takes
your publication and returns ranked, overlap-scored partners with LLM rationales, as a navigable graph.**

## The chosen concept (of three evaluated)

1. **Recommendation-graph matchmaker** ← building this. Highest blend of demand, feasibility,
   shareability, and build-in-public content richness.
2. Niche intelligence report generator — fallback / companion content engine if the map lands flat.
3. Capture-leak / SEO analyzer — lowest-risk (public content only) pivot if endpoints get blocked.

## Where AI genuinely matters (vs. window dressing)

Real: embedding-based *complementary* audience-overlap scoring; LLM-generated match rationales +
outreach angles; topical clustering / community detection; LLM-assisted entity resolution; AI niche
reports. Window dressing: "AI" slapped on raw subscriber counts; a chatbot over a directory.
The differentiation is **data + embeddings + graph**, with the LLM as the explanation/action layer.

## Build-in-public series (the spine)

The agent climbs the Vertical Agent Harness Maturity Model. Each episode stresses one VAA
responsibility, stages its named failure, ships the harness, and yields thread + video + book section.

1. **Identity + context break → entity resolution.** Context Engineering failure, Harness Engineering
   fix. *(See `episode-01-grounding.md`.)*
2. **Reasoning chain → compounding multi-step reliability** (the 0.85ⁿ math). Harness Engineering +
   behavioral SLOs.
3. **Action + identity → delegated outreach gets hijacked by a poisoned input.** DIBR; the episode that
   pins DIBR properties 2 and 3 against real behavior.
4. **Reflective → did the gates pile up into a deterministic workflow?** Harness Saturation.
5. **Opportunistic → a new model drops; migrate the harness, measure what decayed.** Harness Half-Life
   + Retrofit Tax. (Only if a model release lands during the series.)
6. **Wrap → the Vertical Agent Harness Maturity Model**, with substackgraph as the worked climb.

This series knocks out four existing roadmap items: the entity-resolution Lessons piece, the Harness
Engineering chapter, empirical resolution of DIBR properties 2 and 3, and ratification of the
Maturity Model levels.

## Validation gate

Ship the Episode 1 niche map (AI/tech Substack neighborhood) as a teaser. If it earns restacks/shares
and "do mine" replies → proceed to the full matchmaker. If flat → pivot weight toward concept #2
(niche intelligence reports), which is evergreen content even without virality. If endpoints get
blocked or Substack ships native matchmaking → pivot to concept #3 (public-content-only analyzer).

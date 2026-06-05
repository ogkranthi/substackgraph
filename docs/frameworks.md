# Frameworks — working map (NOT canon)

**Source of truth:** the named-framework definitions are canonized in the `the-ai-runtime` skill's
`references/framework-definitions.md`. That file is byte-identical canon for every AIR piece. **Do not
restate definitions here as authoritative** — this file only maps *which framework each build episode
demonstrates*, so the engineering stays on-lens. When in doubt, defer to the AIR skill.

## What each episode demonstrates

| Episode | VAA responsibility | Framework demonstrated | Open question it helps resolve |
|---|---|---|---|
| 1 — grounding break | identity, context | Context Engineering (failure) + Harness Engineering (fix) | how the lower Maturity rungs are defined |
| 2 — reliability math | reasoning | Harness Engineering + behavioral SLOs | — |
| 3 — hijacked outreach | action, identity | DIBR | **DIBR properties 2 and 3** (currently `[VERIFY]`) |
| 4 — over-harnessing | harness | Harness Saturation | the end-of-agent signal in practice |
| 5 — model upgrade (opportunistic) | harness | Harness Half-Life + Retrofit Tax | — |
| wrap | all | Vertical Agent Harness Maturity Model | **ratify the five levels** |

## Flags to respect

- **VAA layer names** are `[VERIFY]` against the canonical "Anatomy of a Production Vertical Agent"
  piece. Use the seven responsibility words (domain surface, identity, harness, reasoning, context,
  action, audit) until the names are confirmed. Don't coin new layer names here.
- **DIBR** has only property 1 confirmed ("delegation collapses identity"); properties 2 and 3 are
  `[VERIFY]`. Episode 3 is partly *how you'll determine them* — capture the real behavior, then take
  it back to the canonical Vercel Breach RCA piece to finalize. Don't invent them speculatively.
- **Maturity Model** levels are not yet ratified in the canon file. Episodes 1 and the wrap are where
  you define them from real build evidence; ratify in the AIR skill before any public self-assessment.
- **No new frameworks.** This build illuminates the existing canon; it does not add to it. If a genuinely
  novel pattern shows up, log it as a candidate and run the naming-conflict audit in the AIR skill — don't
  mint it here.

## Quick lens reminders (functional, not canonical wording)

- **Context Engineering** = controlling what the model knows at inference. Entity resolution is a
  context/grounding failure: the agent's knowledge of *who is who* is wrong.
- **Harness Engineering** = controlling what reaches the user: gates, validation, eval, access control,
  observability. Every fix in this build is a harness component.
- **Harness Saturation** = the point where so many gates accumulate that no autonomous decision remains
  and you should just ship the deterministic workflow.
- **Harness Half-Life** = harness components losing effectiveness as the *underlying model improves*
  (NOT scraping decay — don't mislabel data fragility as Half-Life).
- **Retrofit Tax** = cost to move a harness to a new model: workflow debt + schema opacity + governance friction.
- **DIBR** = the scope of systems an attacker inherits by compromising the agent — the union of all
  permissions delegated to it. Relevant the moment the agent gets a real action capability (Episode 3).

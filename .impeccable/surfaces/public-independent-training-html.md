---
version: 1
slug: "public-independent-training-html"
primary_target: "public/independent-training.html"
related_targets: ["public/independent-training.js","public/independent-training.css"]
---

# Surface: Independent Training (public/independent-training.html)

## Scope & mode
Operate. Config-then-launch cockpit for server-side ~50-minute independent careers, plus glanceable queue/active-run status. Single expert operator; density and findability outrank hand-holding.

## Audience, job, task
The operator assembles an immutable setup (trainee, parents, deck, friend, skills, races, factor reroll), queues N runs, and monitors the executor. Parent choice is a sparks decision: inheritance activates the parent PLUS its two parents (tree.self + tree.p1 + tree.p2), so the preview must show all three nodes and their aggregate.

## Content truths
- Parent preview = header (name, veteran id, score, rank) → stats → aptitudes → INHERITANCE TOTAL rollup (summed stars across parent+gp1+gp2, grouped Blue/Red/Green/White) → per-node columns (Parent/GP1/GP2) with honest "No data" for unknown lineage.
- Skill pickers (priority + final) share one faceted filter bar: Style (tags 101-104), Dist (201-204), Surf (turf = no tag 502 / dirt = 502), Type (color family via icon_id prefix, same mapping as Dashboard). One value per facet, facets AND together with text search. Count chip must state truncation honestly ("12 of 705 shown") and results append an overflow row.
- Filter chip clicks restore focus after re-render; add/remove returns focus to the search input.

## Chosen direction & constraints
Extension of the incumbent Neon Pit Wall system — no new visual world. Reuses the page's local vocabulary (.66rem chips, .55/.45rem radii, surface-2 wells) and Dashboard's semantic skill/spark colors kept as literals. Live numerals (star totals, match counts) in JetBrains Mono per Mono-Means-Live. tests/test_independent_training_frontend.py pins element IDs and source literals — check it before renaming anything.

## Unresolved
- Sitewide: Inter / JetBrains Mono are named but never loaded (no @font-face); pages render OS fallbacks. Out of this surface's scope.
- Mile+Dirt facet combination legitimately yields 0 skills; empty state says so rather than hiding the combination.

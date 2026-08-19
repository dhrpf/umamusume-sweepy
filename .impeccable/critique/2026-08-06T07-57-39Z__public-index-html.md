---
target: public/index.html
total_score: 15
max_score: 40
na_heuristics: 
p0_count: 3
p1_count: 3
timestamp: 2026-08-06T07-57-39Z
slug: public-index-html
---
Method: dual-agent (A: design review, source + live visual · B: detector + browser evidence, live instance :1617)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 1 | Poll failures swallowed in a bare `catch {}` (app.js:2763); a dead server renders pixel-identical to a healthy one. Account strip 60.8% clipped and unscrollable above 1400px. |
| 2 | Match System / Real World | 3 | Vocabulary correct and deliberate. But aptitude grades render *worse = dimmer* (styles.css:3731-3738), and turn is an integer where the operator thinks "Junior, June, 2nd half". |
| 3 | User Control and Freedom | 1 | No Escape on the full-screen skill editor (app.js:2032 — DONE is the only exit); no undo on any bulk skill mutation. |
| 4 | Consistency and Standards | 1 | Native `confirm`/`prompt`/`alert` (app.js:2134-2267) six lines from the custom `#career-modal`; 10+ independent status regions; px/rem and the radius scale both break in the dailies + inheritance block. |
| 5 | Error Prevention | 1 | Five one-click destructive or costly actions with zero guards. |
| 6 | Recognition Rather Than Recall | 1 | Right-click = MANDATORY on race rows, with no hint anywhere in the popup. |
| 7 | Flexibility and Efficiency | 2 | Panel collapse and preset duplication are real accelerators; zero keyboard shortcuts on a keyboard-heavy config surface; RUN CAREER below the fold. |
| 8 | Aesthetic and Minimalist Design | 2 | Ground/accent/hairline discipline is coherent; navbar carries ~15 controls, PRESET CONFIGURATION carries 18 with no sub-grouping. |
| 9 | Error Recovery | 1 | `runner.last_error` is gated behind `if (!rows.length)` (app.js:2738) — it is never shown during a real run. |
| 10 | Help and Documentation | 2 | Correctly no onboarding (not penalized). Penalized for undocumented in-product mechanics only the author could know. |
| **Total** | | **15/40** | **Poor — major UX work required** |

Scored against a single expert operator, per PRODUCT.md. Absence of onboarding and presence of domain acronyms were explicitly *not* penalized. The 15 is not a taste judgment — most of the deficit is rot: undefined variables that silently deleted components, error paths that were correct before the action-history table landed and were never re-checked, and an accessibility layer built correctly in exactly one place and never generalized.

## Design Specificity Verdict

**Specific components pasted into a generic shell.**

Genuinely authored for this product: the account strip (styles.css:258-364) with per-resource left borders in each economy's own color; the five team slots mirroring the game's career-start screen 1:1; the race slot popup with MAIN / RIVAL OVERWRITE badges and per-race banner art; DELAY(S) min/max sitting in the navbar, which tells you instantly this thing talks to a server that will ban you.

Not specific: the shell. Near-black ground, one hot accent, hairline separators, uppercase 900 labels, mono numerals, two-pane split with a collapse gutter — the default dark-admin look of the last five years. Swap magenta for green and this is Sonarr; swap it for amber and it's Portainer.

The damning gap: **this product is a 72-turn career on a fixed calendar, and nothing in the layout is shaped like a turn axis.** Sections, race deadlines, stat trajectories toward targets, the runner's position through a run — the domain's own geometry — appear nowhere in the composition. The one place it could have driven the design is a generic 4-column uppercase HTML table (app.js:2788-2801). And the only real authored identity — the levitating broom, the aura pulse, "Girls are preparing…" — lives on a splash dismissed in under a second and never seen again.

**Deterministic scan: the CLI detector returned a vacuous clean, not a pass.** All three HTML files exited 0 with zero findings. Assessment B verified why rather than reporting a pass: a control file with inline CSS correctly produced 2 findings, but the same rules moved into a *linked* stylesheet produced zero. The static HTML engine does not follow linked CSS, despite `--help` claiming it does. This project has zero `<style>` blocks and all CSS in linked files, so the detector saw no CSS at all. URL mode, which would have rendered it, failed on missing puppeteer. **No file:line data came from the CLI scan**; everything cited here is from source reading and live browser measurement.

**Browser overlay: injected successfully** into the live instance and reported 23,151 findings, which is heavily inflated. Roughly 31% of low-contrast findings are provably false — the detector resolves gradients on the element but not on ancestors, so white-on-body-gradient text (~19:1 real) reports as "1.0:1 #ffffff on #ffffff". `ai-color-palette` (2,235) is flagging the deliberate neon-on-dark identity. Discounted accordingly; only independently re-derived numbers appear below.

## Overall Impression

The taste is fine. The maintenance isn't. Someone with real design judgment built this — `getStartMissingReason()` is better gating than most commercial config UIs, the panel collapse system would pass an accessibility review, the account strip is a genuine piece of product design. Then it decayed, and the decay is invisible by construction: CSS variables that were never declared, error paths that stopped firing when a data shape changed, a navbar that silently guillotines its own signature component above 1400px.

The single biggest opportunity: **the two scenes are being served by one DOM at one zoom.** Config and run-watching have opposite needs and the interface makes no distinction between them. You already built the collapse machinery. You are one state away from RUN CAREER handing the screen over to a purpose-built run view.

## What's Working

1. **The account strip is the system's thesis executed correctly** (styles.css:258-364, app.js:797-819). Per-resource left border in that resource's literal color, a 0.55rem stamped micro-label above a 1.1rem mono 900 value with a matching halo. It obeys every DESIGN.md rule at once and is the only component that would read as *this product* in a screenshot with the text blurred. Which makes issue #1 below the cruelest finding in this report.

2. **`getStartMissingReason()` is exemplary gating** (app.js:1011-1024). One blocking reason at a time in true dependency order — preset → deck → friend → trainee → two parents → lineage validity → TP ≥ 30 — surfaced as the button's own disabled state plus a single sentence. Never dumps a validation list, never shows a reason you can't act on yet, and encodes real domain logic. Its only flaw is how quietly it renders.

3. **The panel collapse system would pass an accessibility audit** (app.js:286-371, styles.css:1014-1102): `aria-expanded` and `aria-label` updated on every toggle, a real `:focus-visible` ring, a `prefers-reduced-motion` bypass in both JS and CSS, and a guard so both panes can never collapse to a blank screen. The tragedy is that this quality was never generalized to the other ~400 interactive elements.

## Priority Issues

### [P0] The signature component is guillotined at your own desktop width
**What.** At 1600x1000 on the live instance the account strip renders at `top: -29.19px` with height 48 — **60.8% clipped**. `body.dashboard-mode { overflow: hidden }` (styles.css:194-196) means it can never be scrolled into view. Root cause: `.navbar { height: 4.8rem }` (styles.css:206-209) with `flex-wrap: nowrap`, while `.navbar-main` needs 133.2px. Measured: 1399px → navbar 144.8px, 0 clipped; 1600px → 76.8px, 29.2px clipped. **The fix already exists** at styles.css:469-477 (`height:auto; flex-wrap:wrap`) but is scoped to `@media (max-width:1400px)` — so the layout is correct on small screens and broken on large ones.

**Why it matters.** TP, carrots, gold, clocks, career state — the entire glanceable layer, the reason scene 2 exists — is sliced in half on any wide monitor. Which is the only kind of monitor this is used on.

**Fix.** Lift `height: auto` and `flex-wrap: wrap` out of the max-width query onto `.navbar` unconditionally, or set `min-height: 4.8rem` instead of `height`. One-line change.

**Suggested command:** `/impeccable adapt`

### [P0] The run is unobservable
**What.** `refreshRunnerStatus()` (app.js:2703-2763) swallows every polling failure in a bare `catch (e) {}` at 2763, and gates the turn readout (2720), the loop message (2727), and critically `runner.last_error` (2738) behind `if (!rows.length)`. `rows` derives from `runner.action_history`, which includes `turn_delay` and `api_delay` entries — so it is non-empty from the first poll onward. **In a real run the turn line and the error text never render.** The error class is applied (2737) but `.start-status.error { color: #ff6b8a }` is defeated by `.action-history-table td { color: var(--text-main) }` (styles.css:1315).

**Why it matters.** Scene 2 exists to answer four questions — alive? what turn? what did it just do? did anything fail? — and this makes two unanswerable and the fourth silent. A crashed FastAPI server produces a UI identical to a healthy one.

**Fix.** Split telemetry from log. Pin a fixed bar carrying `TURN N/72` in mono at ≥2rem, LAST ACTION, and a link heartbeat: record `lastOkPoll` on every successful runner fetch; when `Date.now() - lastOkPoll > 6000`, paint the bar amber with the literal word **STALE**. Render `runner.last_error` in a persistent banner above the table — delete the `!rows.length` guard at 2738. Give the region `aria-live="polite"`.

**Suggested command:** `/impeccable harden`

### [P0] Nine undefined CSS variables have silently disassembled parts of the UI
**What.** `--accent`, `--border`, `--surface-1`, `--bg-elevated`, `--bg-inset`, `--text-secondary`, `--text-dim`, `--danger-soft`, `--warning-soft` are referenced 23 times and declared nowhere. An unresolved `var()` is invalid-at-computed-value-time, so each declaration drops entirely. Verified consequences: the deck editor panel has **no background** (styles.css:1548) and floats over the scrim with its sticky slot rail transparent; the dailies liveness dot is **invisible** (3800-3801, both `background` and `box-shadow` gone); six components lose their borders outright (3789, 3817, 3843, 3867, 3750, 3753) in a system whose stated thesis is "define elements by edge and glow"; the inheritance score — the number the planner exists to produce — renders as plain white (3755); the DELETE CAREER confirmation's explanatory copy has undefined color (518).

**Why it matters.** You are looking at a design that quietly took itself apart, and two casualties are a liveness indicator and a destructive-confirmation's copy.

**Fix.** Alias in `:root` (re-aliasing accent-derived ones under `.theme-blue`): `--accent: var(--accent-primary); --border: var(--border-soft); --surface-1: var(--surface); --bg-elevated: var(--surface); --bg-inset: var(--surface-2); --text-secondary: var(--text-muted); --text-dim: rgba(255,255,255,.45); --danger-soft: var(--danger); --warning-soft: #ffca58;` Then add a ~20-line pre-commit check diffing `var(--x)` uses against `--x:` declarations. This bug class is invisible by construction and will recur.

**Suggested command:** `/impeccable polish`

### [P1] The interface is keyboard-dead, and the primary CTA fails contrast
**What.** Every trainee, parent, friend, and card is a `<div class="grid-card">` with a JS click handler (app.js:2331, 1135, 1236, 2476, 2946) — no `tabindex`, no `role`, no `aria-selected`. All eight collapsibles are `<h2>` with a bare click listener (399). The theme toggle is an `<h1>` (index.html:31). `#skill-modal`, `#deck-editor-modal`, `#career-modal` and the race popup have no Escape handler, no focus trap, no `inert`, no focus return; only `closeVeteranDetail` binds Escape (3983). Across 651 HTML and 4471 JS lines: **2 `aria-label`s, 1 `aria-expanded`, 0 `aria-live` regions.**

Measured live: `:focus-visible` appears **once** in 3888 CSS lines (styles.css:1065). **`.btn` has no focus rule of any kind** — 51 elements, 32 visible, covering RUN CAREER, NEW, RENAME, DEL and all nav. `campaigns.css` and `independent-training.css` have zero `:focus` rules. White on the `#ff2da3 → #ff5cc6` gradient measures **2.76:1 against a 4.5:1 requirement** — that's RUN CAREER, RECOMMEND, and FOLLOW, the three primary actions in the app. 22 of 39 in-viewport interactive elements are under 44x44 (worst: `#account-refresh-btn` at 15.2x19, `#pill-tp-refill` at 23.3x18).

**Why it matters.** A keyboard user cannot select a deck, trainee, or parent — therefore cannot satisfy `getStartMissingReason()` — therefore can never enable RUN CAREER. Contrast and target size matter to you directly at two meters, not just to a hypothetical third party.

**Fix.** One shared `makeActivatable(el, fn)` setting `tabindex="0"` + `role` and binding click + Enter/Space; route every `onclick =` through it. One shared `openModal(el)` storing `document.activeElement`, setting `role="dialog" aria-modal="true"`, binding Escape and backdrop click, applying `inert` to `#app`, restoring focus on close. Global `:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px }`. Darken the gradient's start or set button text to `#12000a` to clear 4.5:1.

**Suggested command:** `/impeccable audit`

### [P1] Five one-click destructive actions, and two competing confirmation systems
**What.** `#tempt-fate-btn` (index.html:45) zeroes API pacing in one click (app.js:564-566) — PRODUCT.md says explicitly not to surface controls reintroducing unbounded automation — and it's styled in `#00ff7f`, the same affirm-green the system uses for *success*. `#pill-tp-refill` spends carats on click with no confirm and reports failure only to `console.error` (874, 877), so a failed refill looks identical to a successful one. `#career-pill` — visually indistinguishable from the TP/CARROTS/GOLD readouts — is the entry point to force-deleting the ongoing career. The skill bulk buttons wipe a tier or the whole blacklist with no count and no confirm; with an empty search box "ALL VISIBLE" means every skill in the game. Clicking a filled team slot clears it instantly (1062).

Meanwhile `#preset-del-btn` uses native `window.confirm` (2254) and NEW/RENAME/DUPLICATE use native `prompt`/`alert` (2134-2248) — unstyled OS chrome — while a working styled `#career-modal` sits six lines away.

**Why it matters.** An expert doesn't need hand-holding; they need irreversible things to *look* irreversible and readouts to not secretly be buttons.

**Fix.** Move TEMPT FATE behind the existing `localStorage.uma_dev_career` gate or style it `.btn-danger` with hold-to-arm. Move career deletion off the pill onto an explicit `.btn-danger-soft` inside it. Put counts in destructive labels (`REMOVE 214 VISIBLE`) and confirm above a threshold. Generalize `#career-modal` into `confirmModal({title, copy, danger})` and delete every `confirm`/`prompt`/`alert`.

**Suggested command:** `/impeccable harden`

### [P1] Hidden mechanics only the author knows
**What.** Right-click on a race row toggles MANDATORY (app.js ~1547) with no hint anywhere — the popup title says only "Select Race". Eleven clicks on the `<h1>` reveals the dev button (428). `window.iwillnotabusethis()` is a global backdoor (432). `#unity-training-weight` and `#unity-burst-weight` (index.html:152-159) are visible under every scenario while `#grand-live-config` is correctly gated on `scenario_id === 3` — two of nine preset fields are live-looking dead controls most of the time. Preset autosave fires on every `change` with the POST failure swallowed at 969 and no saved indicator, ever.

**Why it matters.** This is exactly the "only makes sense if you wrote the code" failure — and the mandatory-race toggle is the highest-leverage planning decision in the product, reachable only by a gesture with no discoverable inverse. Six months from now you will not remember which fields apply to which scenario.

**Fix.** One-line legend in the popup header (`click = plan · right-click = mandatory`) plus a visible MANDATORY chip on each selected row so the mechanic has a keyboard-reachable inverse. Gate `unity-*` on `scenario_id === 2` exactly as Grand Live is gated. Flash "SAVED" beside `#preset-select` on the actual POST resolution and surface the catch at 969.

**Suggested command:** `/impeccable clarify`

## Cognitive Load

**6 clear failures, 2 partial** out of 8.

Failed: single focus (config + library + telemetry + history all live at once), chunking (`#preset-section` is 18 controls across three unlabeled grid rows, grouped by grid position rather than meaning), visual hierarchy (**inverted** — during a run the largest brightest type is the wordmark and the resource pills at 1.1rem mono, while the turn number is 0.72rem uppercase table text), one-thing-at-a-time, ≤4 options, working memory.

Partial: grouping (MASTER DATA, a once-per-game-patch admin field, sits permanently between the inheritance planner and the race schedule, *above* RUN CAREER); progressive disclosure (collapsibles used well, but 5 of 6 library sections default open, and the densest section — preset — isn't collapsible at all).

Decision points exceeding 4 simultaneous options: navbar (~15 interactive elements), preset action row (5), preset config grids (**18**), library pane (6 sections, 5 expanded), skill editor head (search + 3 bulk mutators + N chips), veteran actions (search + 8-option sort + 3 buttons), dailies (4 task cards + 2 selects + veteran select + RUN + STOP), race popup (unbounded rows each carrying two different toggle semantics).

## Emotional Journey

**Peak is at the wrong end.** The loading screen is the emotional high point of the entire product — levitating broom, pulsing aura, "Girls are preparing…", genuine voice. Visible under a second, never returns. Everything after is cold instrumentation.

**Config valley.** Eighteen ungrouped fields; autosave fires on every change with the failure swallowed and no saved indicator. You tune EXPECT SPD and receive literally zero acknowledgment.

**The high-stakes moment fails.** Clicking RUN CAREER on a multi-hour run produces: button text → `RUNNING...`, and `#start-status` → `'Starting runner...'` in 0.78rem 55%-white uppercase. **No summary of what is about to run** — no "Trainee X · Deck Y · Scenario Mant · 12 races planned · TP 30/100". The most consequential commit in the product is the emptiest screen in it, and you can't verify the config without scrolling back up past everything.

**Run valley.** The only liveness signal is that table rows keep appearing. If the server dies, nothing changes.

**End is the flattest moment.** A multi-hour unattended run — the entire point — terminates with `Runner stopped after 214 steps` in the same gray fragment, plus one row in a 0.72rem table. Peak-end reads: peak at the splash, trough at the finish. Precisely backwards.

## Persona Red Flags

**Alex (impatient power user).** RUN CAREER is below the fold (index.html:306) — every launch pays a scroll past 18 preset fields, the inheritance planner, MASTER DATA, and the race schedule. Zero keyboard shortcuts: no Ctrl+Enter to launch, no `/` to focus a filter, no Escape to leave the full-screen skill editor. Five library sections default expanded, each an unbounded card grid — the right pane is thousands of pixels on first paint. Three native `prompt()` round-trips to fork a preset. The 5.75rem collapse gutter permanently spends the scarce horizontal axis on two buttons. No pre-flight summary at the moment of commit. Bulk skill buttons don't state their blast radius, so he re-filters defensively before every click. 1.5 MB of PNG loads before the app for a splash gone in under a second. `.start-status { min-height: 12rem }` reserves 192px of nothing under RUN CAREER at rest.

**Sam (keyboard, contrast, focus).** Cannot configure a run at all — deck, trainee, parent, and friend cards are unfocusable divs, so `getStartMissingReason()` never clears and RUN CAREER stays permanently disabled. Cannot expand any of the 8 sections. Cannot change theme. Cannot clear a team slot. Trapped in modals with no Escape, no focus trap, no `inert`; Tab walks straight into the dashboard behind. Focus indication near-absent — one `:focus-visible` rule in 3888 lines, and `.btn` has none. Spark data is hover-only (styles.css:2146) — the deciding factor for parent selection is unreachable by keyboard, though `.sparks-tooltip.is-visible` exists so the JS path is already there. Contrast: `.logout-btn #666` = 3.55:1; `.ag-grade-G #555` = 2.75:1 and `.ag-grade-F #777` = 4.57:1 at 0.75rem — the aptitude grades that most change a decision are the least readable; `.team-item-empty` = 2.98:1 (live-measured). Zero `aria-live` — every status region in the app mutates silently. Meaning encoded with neither color nor word: dailies log severity is font-weight and opacity only (3881-3882), which is worse than color-alone.

Credit where due: TEMPT FATE and BURN CLOCKS change their *label* with state, and `.grid-card.selected::after` adds a ✓ glyph. Those obey the Never-Color-Alone rule.

## Minor Observations

- **No webfont is loaded anywhere.** No `@font-face`, no Google Fonts link. `"Inter"` and `"JetBrains Mono"` constitute the entire declared type system, so on any machine lacking both, DESIGN.md's typography degrades to `system-ui` + generic mono and `font-weight: 900` becomes faux-bold — exactly what "stamped instrument panel" must not look like. Worse, styles.css:3870 uses a *different* mono stack than :293, so the dailies log and the account pills are different typefaces by accident.
- **The signature depth rule is violated by the two most-repeated components.** `.grid-card` carries a neutral `box-shadow` at rest and a heavier neutral shadow plus `translateY` on hover (1766-1779); `.account-pill:hover` lifts with no glow (280). DESIGN.md: "A gray drop shadow on an interactive element is foreign to this system."
- **252px of horizontal overflow at 390px width**, clipped by `body { overflow-x: hidden }` rather than scrolling — so it's unreachable, not just ugly. 28 distinct offenders; worst are `#team-slot-vet2` (+256.7px), the account strip (+251.9px), and a 410px-wide `#trackblazer-schedule-select`.
- **`border-radius: 12px`** on the dailies/inheritance block sits outside the declared 3-step scale, and that whole region is authored in `px` and minified one-liners while the rest of the file is `rem` and expanded. It reads as a different author who never met the system.
- **The eyebrow convention DESIGN.md is proudest of** (`Server truth`, `Immutable snapshot`) appears nowhere in index.html — the one surface where "is this live or cached?" actually matters is the surface without it.
- **`#friend-vet-refresh-btn`** is nested inside its `<h2>` toggle and its handler lacks `stopPropagation`, so clicking REFRESH also collapses the section. `#friend-refresh-btn` got the fix; this one didn't.
- **The Steam password is written to `localStorage` in plaintext** on every successful login (app.js:672-673), with no "remember me" affordance and no opt-out. The form already declares `autocomplete="current-password"`, so the browser's credential store is already handling it. This is worth deleting outright — it contradicts PRODUCT.md principle 5 and CLAUDE.md's privacy section, and it survives in cleartext on disk.
- **The loading screen text is static.** During the up-to-180s Frida auth capture you get a bouncing broom, no phase, no elapsed time, no cancel — while PRODUCT.md explicitly requires an honest state for "not authenticated yet".
- **`app.js?v=22`** is manual cache-busting, easy to forget on the next edit.
- **Two unrelated race-color systems coexist** — the `.badge-g1` family and Bootstrap-default green/amber terrain colors unconnected to the palette.
- **Race popup badges are styled with inline `style="…"`** in a codebase with a declared design system.
- Sub-12px text is pervasive: 16 classes, smallest `.grid-card-kicker` at 8.32px, and 1,185 elements at 9.28px. Density-first is legitimate for this tool, but the sub-9.5px tier is not defensible at two meters.

## Questions to Consider

1. **The product is a 72-turn career on a fixed calendar, and the interface contains no calendar.** What happens if the turn axis becomes the primary composition — one horizontal track, races pinned to their turns, sections marked, the runner's position moving along it — instead of a table that auto-scrolls itself to the bottom?
2. **Scene 1 and scene 2 are served by the same DOM at the same zoom.** What if RUN CAREER doesn't just start the runner but changes the shell — config collapses, a full-width run view takes over, turn at 4rem, stats vs targets, failure log? You already built the collapse machinery; you're one state away.
3. **The only warmth in the product is spent on a splash you see for 800ms**, while a three-hour run ends with "Runner stopped after 214 steps." What would it cost to move the personality to the *end* — a finish card with final stats, races won, skills bought, and delta against `expect_attribute`?
4. **If the server dies mid-run, this interface is pixel-identical to a healthy one.** What is the smallest honest signal that makes "the server is the truth" also mean "and you can tell when it stopped talking"?
5. **Nine CSS variables are referenced and never declared, and the UI quietly degraded around it without anyone noticing.** Does that make DESIGN.md a specification or a description? Would you rather maintain a 300-line token file that fails loudly than a 3888-line stylesheet that fails silently?

---

## Addendum — late measurements from the live instance (1920×1080, 1440×900, 2560×1080)

These arrived after the synthesis above and refine three findings.

**Both declared typefaces are absent at runtime.** `document.fonts.length === 0` on the live machine; Inter — MISSING, JetBrains Mono — MISSING. There is no `@font-face` and no font link anywhere. Every `font-weight: 900` structural label is browser-synthesized faux-bold over `system-ui`, and every "mono means live" readout is generic `monospace`. This is not a portability caveat — the interface has never once rendered its own declared typography on this machine. Promoted from Minor Observation to P1.

**The navbar clipping band has an upper bound: ~1401px – ~2294px.** Verified 1440 broken, 1920 broken, 2560 fine. Root cause is `.navbar-main` wrapping (needs 1261px, gets 887px at 1920) to 133.2px inside a fixed 76.8px `.navbar`. At 1920 the five micro-labels sit at `top: -20px` and are 100% invisible; at 1440 the mono values themselves lose 47% of their glyph height.

**Measured density figures.** 194 accent-painted elements in one viewport (95 text, 97 border, 2 fill). Type histogram across 12,540 text nodes: 8px×20, 9px×1880, 10px×3374, 11px×489, 12px×1144, 14px×5609, and only **20 nodes above 14px** — of which ranks 3–8 are the six decorative gutter chevrons at 19.5px, larger than any live data value on screen. 431 mouse-only click targets versus 64 focusable elements. Right pane at rest: 37,354px = 38.75 screens of scroll, 232 parent cards rendered eagerly.

**Additional defects not in the synthesis above.**
- The team-slot row renders broken: `.team-slots` is a 5-column grid (styles.css:1133) but `#trainee-aptitude-panel` (index.html:105) is a sixth child, orphaning PARENT 2 onto row 2 beside an empty cell, with the aptitude table sitting inline unlabeled.
- `.preset-field-narrow` is dead styling — authored for a 5-across row but its container is `repeat(2, 1fr)`, so the five EXPECT fields consume three full-width rows.
- `#inheritance-recommend-btn` uses `.btn-primary` for a read-only query, on the same scroll as `#start-career-btn`'s irreversible multi-hour commit — breaking DESIGN.md's own reserve-primary-for-the-committing-action rule.
- The MASTER.MDB PATH field renders a full home-directory path at full pane width, on a window designed to sit on a second monitor.
- `user-select: none` on all eight section titles (styles.css:1353).

Heuristic total on the fuller pass: 16/40 rather than 15/40. Same band, same conclusions.

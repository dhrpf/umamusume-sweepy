---
name: Sweepy改二
description: A neon pit wall for Uma Musume career automation — hot magenta telemetry on near-black, readable across the desk.
colors:
  accent-primary: "#ff2da3"
  accent-secondary: "#ff5cc6"
  accent-primary-blue: "#00f2ff"
  accent-secondary-blue: "#00d4ff"
  bg-start: "#0a0012"
  bg-end: "#150018"
  surface: "#1a1420"
  surface-2: "#140f18"
  bg-start-blue: "#000814"
  bg-end-blue: "#001220"
  surface-blue: "#0a192f"
  surface-2-blue: "#0d2339"
  text-main: "#ffffff"
  text-muted: "rgba(255, 255, 255, 0.7)"
  border-soft: "rgba(255, 255, 255, 0.1)"
  danger: "#ff6b6b"
  alarm: "#ff4d4d"
  affirm: "#00ff7f"
  stat-tp: "#00f2ff"
  stat-carrots: "#ffab40"
  stat-gold: "#ffd700"
typography:
  display:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 900
    lineHeight: 1
    letterSpacing: "0.4rem"
  headline:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 900
    lineHeight: 1
    letterSpacing: "normal"
  title:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 900
    lineHeight: 1.2
    letterSpacing: "0.22rem"
  body:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.55rem"
    fontWeight: 900
    lineHeight: 1.2
    letterSpacing: "0.1rem"
  readout:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "1.1rem"
    fontWeight: 900
    lineHeight: 1
    letterSpacing: "normal"
rounded:
  sm: "0.25rem"
  md: "0.5rem"
  lg: "1rem"
  pill: "999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2rem"
  section: "2.6rem"
components:
  button:
    backgroundColor: "transparent"
    textColor: "{colors.accent-primary}"
    rounded: "{rounded.md}"
    padding: "0 2rem"
    height: "4rem"
  button-primary:
    backgroundColor: "{colors.accent-primary}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.md}"
    padding: "0 2rem"
    height: "4rem"
  button-sm:
    backgroundColor: "transparent"
    textColor: "{colors.accent-primary}"
    rounded: "{rounded.md}"
    padding: "0 1.25rem"
    height: "2.2rem"
  button-danger-soft:
    backgroundColor: "rgba(255, 107, 107, 0.12)"
    textColor: "{colors.danger}"
    rounded: "{rounded.md}"
    padding: "0 1.25rem"
    height: "2.2rem"
  form-input:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.md}"
    padding: "1rem 1.25rem"
  filter-input:
    backgroundColor: "rgba(0, 0, 0, 0.3)"
    textColor: "{colors.text-main}"
    rounded: "0.35rem"
    padding: "0.35rem 0.5rem"
  panel:
    backgroundColor: "rgba(26, 20, 32, 0.9)"
    textColor: "{colors.text-main}"
    rounded: "{rounded.lg}"
    padding: "1.5rem"
  account-pill:
    backgroundColor: "rgba(255, 255, 255, 0.03)"
    textColor: "{colors.text-main}"
    rounded: "0"
    padding: "0 1rem"
    height: "3rem"
---

# Design System: Sweepy改二

## Overview

**Creative North Star: "The Neon Pit Wall"**

Sweepy looks like the telemetry desk of a race team working in a dark garage. The room is nearly black with a violet cast; everything that matters is a lit readout on that black. Hot magenta is the instrument light — it draws every border that carries meaning, every section marker, every field label — and the numbers themselves are set in mono at heavy weight so they hold their shape from across the desk. Nothing here is trying to be calm. It is trying to be *legible while glowing*.

The system serves two viewing distances at once, and that tension explains most of its choices. Up close, during configuration, the interface is unapologetically dense: multi-column grids, tiny 0.55rem uppercase labels, collapsible sections stacked deep. At two meters, during a run, only the lit things survive — the accent-bordered section rules, the mono stat readouts in their color-coded pills, the state badges. Density and glow are not decoration fighting each other; the glow is the triage layer that makes density survivable at distance.

Type is uppercase and heavy nearly everywhere structural (900 weight, wide tracking), which reads less as branding than as instrument panel: labels are stamped, not written. Depth never comes from realistic shadow. Surfaces are flat planes separated by hairline white borders at 10% opacity, and where something needs to sit forward it *emits* rather than lifts — an accent-tinted box-shadow, a text-shadow, a drop-shadow on artwork. The result is a screen with no fake physicality and a lot of light.

The palette exists in two peer identities: magenta (default) and cyan (`.theme-blue`, toggled from the title). They are not light/dark modes. The structure, type, spacing, and depth model are identical; only `--accent-*` and `--bg-*` swap. Cyan is a full alternate skin, not an easter egg.

**Key Characteristics:**
- Near-black violet ground (`#0a0012` → `#150018`), never a neutral gray
- One hot accent doing all structural signalling; hairline white borders doing all separation
- Uppercase 900-weight Inter for structure, JetBrains Mono for every number
- Depth as luminosity: accent-tinted glow, never neutral drop shadow
- Domain colors (TP cyan, carrots orange, gold) that are semantic, not decorative
- Two peer accent identities behind one unchanged structure

## Colors

A single hot accent burning on a near-black violet ground, plus a small fixed vocabulary of semantic status and resource colors that never change with the theme.

### Primary
- **Signal Magenta** (`accent-primary`): The instrument light. Every load-bearing border, section rule, field label, eyebrow, panel title, and primary button gradient. It marks *what is structural*, not what is important-right-now — which is why it is everywhere and still not noise.
- **Signal Magenta Bright** (`accent-secondary`): Only the far end of the primary-button gradient and hover lift. Never used alone.
- **Signal Cyan** (`accent-primary-blue`) / **Signal Cyan Bright** (`accent-secondary-blue`): The peer identity's substitutes for the two above under `.theme-blue`. Same roles, no exceptions.

### Neutral
- **Pit Black** (`bg-start` → `bg-end`): The body gradient. Top-to-bottom, violet-shifted, never flat #000.
- **Console Slab** (`surface`) and **Recessed Slab** (`surface-2`): The two panel planes. `surface-2` is the *inset* — input wells and pressed regions — not a second card level.
- **Instrument White** (`text-main`) and **Instrument White Dimmed** (`text-muted`): Primary and secondary text. There is no third text tier; anything quieter uses opacity on the muted value.
- **Hairline** (`border-soft`): The only separator. Every divider, panel edge, and unemphasized field border.

### Status and Resource
- **Affirm Green** (`affirm`): Success, pass, completed, positive delta. Always paired with a word or icon — never carrying the meaning alone.
- **Alarm Red** (`alarm`) and **Danger Coral** (`danger`): Failure and destructive intent respectively. `alarm` reports what the server said went wrong; `danger` marks a control that will destroy something.
- **TP Cyan** (`stat-tp`), **Carrot Orange** (`stat-carrots`), **Gold** (`stat-gold`): Hardcoded resource identities in the account strip. These are *game economy* colors and do not swap with the theme.

### Named Rules

**The Instrument Light Rule.** The accent is a structural marker, not an emphasis tool. It draws borders, rules, and labels. It never fills a large surface — the only accent fills in the system are the primary button gradient and sub-15% alpha tints.

**The Fixed Economy Rule.** TP cyan, carrot orange, and gold are game-economy identities and stay literal in both themes. They are the one place hardcoded hex is correct. (Known collision: under `.theme-blue` the accent equals TP cyan exactly — the account strip loses its distinction. Live with it or shift TP; do not "fix" it by theming the resource colors.)

**The Never-Color-Alone Rule.** Status is read from two meters away by someone who may be looking at a second monitor. Every green/red state carries a word, glyph, or position as well as its hue.

## Typography

**Display / Body Font:** Inter (with `system-ui`, `-apple-system`, sans-serif)
**Readout Font:** JetBrains Mono (with `ui-monospace`, `SFMono-Regular`, Menlo, Consolas, monospace)

**Character:** One neutral grotesque doing all the talking, pushed to 900 weight and wide tracking wherever it labels something, so structure reads as stamped instrumentation rather than prose. Mono appears for one reason only: numbers that change while you watch them. The pairing has no editorial ambition — it is a control panel that happens to be well set.

### Hierarchy
- **Display** (900, 1.5rem, 0.4rem tracking, uppercase): The wordmark only. `SWEEPY` in accent, `改二` in white at 90% opacity. Doubles as the theme toggle and the hidden dev gate.
- **Headline** (900, 1.25rem, uppercase): Section titles. Always preceded by a 0.28rem accent left rule — the rule is part of the type, not the container.
- **Title** (900, 0.72rem, 0.22rem tracking, uppercase, accent at 85% opacity): Panel headers in the split-pane chrome. Deliberately smaller than body text; tracking carries it.
- **Body** (400, 1rem, 1.5): Descriptions, help text, table cells. Runs short by nature — this UI has few sentences.
- **Label** (900, 0.55rem, 0.1rem tracking, uppercase, muted): Micro-labels above readouts in pills and stat blocks. The smallest type in the system; only ever 1–2 words.
- **Readout** (JetBrains Mono, 900, 1.1rem): Every number that reflects live server state — TP, carrots, gold, stats, turn counts, IDs. Mono is the tell that a value is *data*, not copy.

### Named Rules

**The Mono-Means-Live Rule.** If it's monospace, it came from the server and can change without you touching anything. Never set static copy in mono; never set a live value in Inter.

**The Stamped Label Rule.** Structural labels are uppercase, 800–900 weight, and tracked out. Sentence-case appears only in body copy and helper text. A sentence-case section title is a bug.

## Layout

A full-height application shell, not a page. The navbar is a fixed 4.8rem bar with the wordmark left, live account readouts and run controls right; `body.dashboard-mode` locks page scroll so panes scroll independently. Below it, the dashboard is a horizontally split workspace — setup on the left, library/content on the right — with dedicated collapse handles (`.panel-collapse-btn`) between them so either side can be surrendered to the other. The secondary surfaces (independent training, campaigns) instead stack full-width `1.5rem`-padded panels with a shared heading pattern: an accent eyebrow, then an h2.

Rhythm is a loose 0.25rem-based scale with `2.6rem` between dashboard sections and `1.5rem` inside panels. Repeating content lives in auto-fit grids driven by a per-container `--grid-min` custom property (`8.6rem` default, tightening to `7.5rem` on small screens), so card grids reflow by density rather than by fixed column counts.

Responsive behavior is desktop-first with many small local breakpoints (`520px` through `980px`) rather than one global set — each dense region collapses where it personally breaks. At narrow widths, hero rows go column, identity blocks left-align, and form grids collapse to single column. Mobile is a supported fallback, not a designed-for scene: the real target is a wide window on a secondary monitor.

## Elevation & Depth

Depth is luminosity. There is essentially no neutral drop shadow in the resting state of this system — surfaces are flat planes separated by `border-soft` hairlines, and anything that needs to advance does it by emitting accent light. The navbar's `0 4px 30px rgba(0,0,0,0.5)` and the panel's `0 1rem 3rem rgba(0,0,0,.25)` exist to seat large containers against the black ground, not to fake lift; every *interactive* forward state is a glow instead.

### Shadow Vocabulary
- **Accent bloom** (`box-shadow: 0 0.5rem 2rem var(--accent-dim)`): Primary buttons at rest. The button is lit, not raised.
- **Focus bloom** (`box-shadow: 0 0 1rem var(--accent-dim)` + accent border): The only focus treatment on inputs.
- **Container seat** (`box-shadow: 0 1rem 3rem rgba(0, 0, 0, 0.25)`): Panels against the body gradient.
- **Chrome seat** (`box-shadow: 0 4px 30px rgba(0,0,0,0.5), inset 0 -1px 0 rgba(255,255,255,0.05)`): The navbar, plus `backdrop-filter: blur(20px)`.
- **Readout halo** (`text-shadow: 0 0 10px rgba(<resource>, 0.3)`): Resource pills in the account strip. The only text-shadow that carries meaning.
- **Art glow** (`drop-shadow`, layered): The broom/sweep loading art only.

### Named Rules

**The Glow-Not-Lift Rule.** Interactive depth is emitted, never cast. Hover and focus add accent luminosity (`filter: brightness(1.1)`, `translateY(-0.1rem)`, accent box-shadow); they do not add a neutral shadow. A gray drop shadow on an interactive element is foreign to this system.

## Shapes

A three-step radius scale — `sm` 0.25rem, `md` 0.5rem, `lg` 1rem — assigned by size, not by emphasis: controls take `md`, panels take `lg`, chips and micro-affordances take `sm`. Nothing is fully round except status dots and the occasional pill.

The signature form is not a radius at all: it is the **left rule**. Section titles carry a 0.28rem accent bar on their left edge; account pills carry a 3px colored left border in their resource's color. Meaning attaches to the left edge of a block throughout the system — that vertical stroke is the closest thing Sweepy has to a logo mark inside the UI.

Borders are thin and doing real work: `0.1rem` accent on outline buttons, `1px` `border-soft` everywhere else. Fills are rare; an element is usually defined by its edge and its glow rather than its background.

## Components

### Buttons
- **Shape:** Softly rounded (`0.5rem`), uppercase, 800 weight, full-width by default — `.btn-sm` is the opt-out that returns it to auto width at 2.2rem tall.
- **Default (outline):** Transparent fill, `0.1rem` accent border, accent text. The workhorse; used for nearly every control.
- **Primary:** 135° accent→accent-secondary gradient, white text, no border, resting accent bloom. Reserved for the one committing action on a surface (LOGIN, RUN CAREER, SAVE DECK).
- **Hover / Focus:** `brightness(1.1)` and a `-0.1rem` translate on primary; accent border and 6% accent wash on chrome buttons. Focus-visible is a 2px accent outline with negative offset.
- **Danger:** Two tiers. `.btn-danger` is a red→accent gradient for irreversible commits; `.btn-danger-soft` is a 12%-alpha coral tint with coral text for reversible removals.

### Cards / Containers
- **Corner Style:** `1rem` on panels.
- **Background:** `rgba(26, 20, 32, 0.9)` — the console slab, slightly transparent over the body gradient.
- **Shadow Strategy:** Container seat only (see Elevation). No hover elevation on containers.
- **Border:** `1px` `border-soft` hairline.
- **Internal Padding:** `1.5rem`.

### Inputs / Fields
- **Style:** Recessed — `surface-2` fill (or `rgba(0,0,0,0.3)` for compact filter inputs), hairline border, `0.5rem` radius, generous `1rem 1.25rem` padding on primary forms.
- **Label:** Accent, 800 weight, uppercase, 0.1rem tracking, sitting above the field. The label is accent-colored; the value is white. That inversion is consistent and load-bearing.
- **Focus:** Border goes accent, plus a `1rem` accent bloom. No outline ring on text inputs.
- **Compact variant:** `.filter-input` / `.filter-select` at 0.8rem for in-panel filtering; same focus behavior, no bloom.

### Navigation
- Fixed 4.8rem bar, gradient background, `blur(20px)` backdrop, 2px accent-at-20% bottom border. Wordmark left; small uppercase `.btn-sm` route buttons and run-mode toggles right, revealed by state rather than always present. There is no mobile nav pattern — the bar wraps.

### Account Strip (signature component)
The live resource readout beside the navbar: a row of flat pills, each a 3px colored left border, a 0.55rem uppercase micro-label, and a mono 900-weight value in the resource's own color with a matching 10px text-shadow halo. It is the system's thesis in one component — semantic color, mono for live data, meaning on the left edge, glow instead of lift, readable across the room.

### State Badges / Eyebrows
Panels on the secondary surfaces open with a 0.75rem accent eyebrow (`Server truth`, `Ordered snapshots`, `Immutable snapshot`) above the h2. The eyebrow names *what kind of truth the panel shows* — a small honest convention worth keeping.

## Do's and Don'ts

### Do:
- **Do** put every live, server-sourced number in JetBrains Mono at 900. The Mono-Means-Live Rule is how the operator distinguishes data from chrome at a glance.
- **Do** mark structure with the accent left rule (`border-left: 0.28rem solid var(--accent-primary)` on section titles, 3px colored on pills). It is the system's signature.
- **Do** define elements by edge and glow rather than fill. Hairline `border-soft` for separation, accent border for meaning.
- **Do** reach for `.btn` outline by default and reserve `.btn-primary` for the single committing action on a surface.
- **Do** keep structural labels uppercase, 800–900, and tracked out.
- **Do** pair every status color with a word or glyph — the second monitor is two meters away.
- **Do** route new colors through `--accent-*` / `--surface-*` variables so `.theme-blue` keeps working. Both themes are peers.

### Don't:
- **Don't** add neutral gray drop shadows to interactive elements. Depth is emitted here, not cast.
- **Don't** theme the resource colors (TP cyan, carrot orange, gold). They are game-economy identities and stay literal in both palettes.
- **Don't** fill large surfaces with the accent. Above roughly 15% alpha, magenta belongs only in the primary button gradient.
- **Don't** introduce a third text tier. `text-main` and `text-muted`, then opacity.
- **Don't** use a flat neutral gray or pure `#000` ground — the violet cast in `#0a0012` is what keeps the magenta from vibrating.
- **Don't** set a section title in sentence case, or a live stat in Inter. Both read as broken instrumentation.
- **Don't** add a build step to keep a style working. The system is hand-authored CSS with no bundler by construction.

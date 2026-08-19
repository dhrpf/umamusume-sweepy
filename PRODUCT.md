# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Single operator: the repo author, running Sweepy locally on their own machine against their own Uma Musume accounts. No second audience is confirmed — the interface is a personal instrument, not a distributed product, even though the repo is public. Design for someone who already knows every field, every acronym, and what a preset does; density and speed outrank hand-holding and first-run explanation.

## Product Purpose

Sweepy automates Uma Musume career runs end to end. A local FastAPI server (`main.py`) intercepts game auth, speaks the game's msgpack/AES API directly (`uma_api/client.py`), and drives a turn loop that picks training commands, resolves events, enters races, buys skills, and manages items via scenario strategies (`career_bot/scenarios/`). The browser UI at `public/` is the operator's cockpit: configure a run, launch it, watch it, and read what happened afterward.

Success is a career run that completes unattended and produces a better trained Umamusume than manual play, with the operator spending their attention on strategy configuration rather than on turn-by-turn clicking.

## Positioning

Sweepy talks to the game's real API rather than automating the UI through image recognition or input replay. That buys exact state (stats, energy, bond, fail rates, race programs, item inventory) as data instead of inference, which is what makes a rule-based decision engine — and eventually the MCTS planner in `career_bot/mcts/` — possible at all.

## Operating Context

Two distinct interaction scenes, and the UI must serve both:

1. **Config-then-launch.** Dense up-front work: pick/edit a preset, build the deck, set stat targets and skill priorities/blacklist, plan the race schedule, choose inheritance. High interaction, high information density, then the operator hits RUN and stops touching it.
2. **Glanceable second screen.** The window sits on another monitor for the length of a run (careers run long; independent training is a ~50-minute server-side job). The operator looks over occasionally to answer: is it still alive, what turn, what did it just do, did anything fail. Legibility at a distance and status-at-a-glance matter more here than any control.

Post-run reading (run history, veterans, career logs) also happens but was not confirmed as a primary scene.

Surfaces today: `public/index.html` (dashboard: presets, inheritance, race schedule, run history, decks, friends, trainees, parents, cards, veterans, dailies), `public/independent-training.html` (independent training setup, active run, queue, results), `public/campaigns.html` (multi-run campaign builder and detail).

## Capabilities and Constraints

- Backend is FastAPI; `public/` is served as static files at `/`. Port overridable via `PORT`, so the UI uses relative URLs only.
- Server is the source of truth for run state. The UI polls status endpoints and renders what the API returns; it does not estimate turns or progress locally. Polling below ~2s is rate-limited by design.
- Incumbent frontend stack is vanilla JS + hand-written CSS with no build step (edit and refresh). This is the current state, **not** a binding constraint — the operator declared the stack open to replacement.
- Career looping and "tempt fate" style unbounded automation were deliberately removed from the public path; do not surface controls that reintroduce them. Dev-only affordances stay hidden behind the existing 11-tap / `localStorage.uma_dev_career` gate.
- Auth capture depends on Frida hooking the game running under Proton on Linux; startup can block for up to ~180s while auth refreshes. The UI must have an honest state for "not authenticated yet."
- Domain vocabulary is game-native and stays that way: turn, preset, deck, support card, scenario (URA / Mant), section, energy, bond, motivation, fail rate, program (race), spark, factor, inheritance, TP, veteran, daily.
- Long-lived data lives under `uma_runtime/<acct>/`; static game data (`data/*.json`) is regenerated from `master.mdb` after game patches.

## Brand Commitments

None binding. The current identity — the name "SWEEPY改二", all-caps terminal typography, dark theme, the sweep/broom assets — is incumbent evidence, not a commitment. The operator explicitly left look and identity open to replacement.

## Evidence on Hand

- Real runtime data: career logs at `uma_runtime/<acct>/bot_logs/career_log_<ts>.json`, API trace logs, and live API responses — the UI renders real state, never mock.
- Static game data in `data/` (`skill_data.json`, `chara_list.json`, `support_list.json`, `race_map.json`, `career_objectives.json`, aptitudes) plus race/character art under `public/assets/` and `public/races/`.
- Existing assets `public/sweep.png`, `public/broom.png`.
- No testimonials, users, benchmarks, pricing, or adoption claims exist. Future work must not invent them; this is a single-operator local tool.

## Product Principles

1. **The server is the truth.** Render what the API says; never invent progress, estimates, or optimism the backend didn't report.
2. **Two scenes, one surface.** Every screen must work both up close during configuration and from across the desk during a run.
3. **Expert vocabulary, no translation.** Use the game's own terms. Explaining them costs space and buys nothing for the only user.
4. **Failures are first-class.** Race entry rejections, failed item buys, auth expiry, and error codes are normal operating output, not exceptions to hide.
5. **Privacy is structural.** Viewer IDs, account labels, device IDs, and auth material are never shown where they could end up in a screenshot or a commit.

## Accessibility & Inclusion

No product-specific requirement established beyond the practical one implied by the glanceable-second-screen scene: status must stay readable at distance and never encode meaning in color alone.

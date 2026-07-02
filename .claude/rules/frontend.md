# Rule: Frontend (vanilla JS SPA)

Paths: `public/**`

## Layout

1. `index.html` loads `styles.css` + `app.js`. No build step — edit and refresh.
2. `assets/` holds images (`sweep.png`, `broom.png`). Don't rename without updating references in `app.js`.
3. `races/` contains SVG/PNG race icons referenced by `uma_race_data.json`.

## Behavior

4. Dev-mode toggle: click "SWEEPY改二" title 11x OR set `localStorage.setItem('uma_dev_career', 'true')`. Don't break this by renaming the title.
5. API calls use the same prefix as backend routes (`/api/career/...`). Don't hardcode `http://127.0.0.1:1616` — use relative URLs so `PORT=...` override works.
6. Career list mtime-cached on the backend; UI polls status endpoint. Don't poll at < 2s intervals (server-side rate-limit is by design).
7. Deck composition panel renders 6 card slots + 1 friend slot. Don't assume slot order — read `deck_meta` from the start response.
8. Skill priority list (rendered from `expect_attribute`) is 5 sliders. Don't add more sliders without backend support.
9. Item budget display: read `coin_num` from `free_data_set` of the latest res. Don't compute budget client-side from owned item list.
10. Long-running career runs: UI shows progress via `status.steps` and `status.turn`. Don't add local turn estimation — server is source of truth.

## Event Handlers

11. `app.js` uses vanilla `fetch`. Don't import a new framework without also deleting `app.js` — broken state is worse than missing deps.
12. Toast/error rendering lives in one function (`showMessage` or similar). Consolidate new alerts there.

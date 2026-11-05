# U6: Polish, accessibility, responsiveness

| Check | Result | Evidence |
|---|---|---|
| Contrast ≥ 4.5:1 for text (light + dark, design tokens + Streamlit theme colours) | PASS | `regression/contrast_report.md` |
| Status = icon + text, never colour alone | Done: ✓ Approved / ✕ Rejected / ⚑ Human Review on badges, chips, card icon, trail; rule chips have screen-reader text | `after/style_guide/*.png` |
| Keyboard | Every input is a native Streamlit widget (Tab order follows the layout), step tabs are arrow-key / Tab focusable with a visible focus ring, Enter submits text inputs, the submit and copy buttons are real buttons | — |
| Responsive 1920 / 1366 / 1024 / 390 px, light + dark | 88 shots (11 pages × 4 widths × 2 themes), **0 with horizontal page scroll** (measured `scrollWidth > innerWidth`); tables scroll inside their frame | `after/grid/*.png`, `after/grid/timings.json` |
| One term per concept | "Human Review" everywhere in the UI (no "manual review"); lower-case "human review" appears only inside backend reason text | grep of `app/` |
| Load time not worse | Server-side page run, median of 5 interleaved old/new runs: no page slower by more than 0.04 s; total **2.31 s → 1.71 s (−26 %)**, thanks to caching the tree image, fairness charts and advisory models | `regression/load_times.md` |

Note on load-time method: browser timings were tried first, but Streamlit's delayed "running" indicator and its
periodic websocket messages made identical runs vary by seconds, so the server-side script run is the measure.

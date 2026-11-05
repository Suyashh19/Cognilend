# U1: Design system

| File | What |
|---|---|
| `.streamlit/config.toml` | Light **and** dark themes (deep blue `#1D4F91` primary, neutral greys, green / red / amber status colours), radius, sidebar; the auto page list is hidden (the app draws its own menu, U2). |
| `app/ui/theme.py` | Colour tokens per theme + spacing scale; `inject()` writes them as CSS variables plus `app/assets/styles.css`, once per run. Active theme read from `st.context.theme`. |
| `app/assets/styles.css` | Cards, badges, chips, tiles, meter, trail, stepper, messages, empty states, timeline, footer, print rules. Selectors are our own `.cl-*` classes or Streamlit's stable `st-key-<key>` / `data-testid` / `role` hooks. |
| `app/ui/components.py` | `page_header`, `card`, `status_badge`, `metric_tile`, `tiles`, `rule_chip`, `confidence_meter`, `reason_list`, `trail_html`, `rupee`, `empty_state`, `error_box`, `note`, `step_indicator`, `copy_button`. `decision_card(result)` lives in `app/common.py` (it needs the cached pipeline for the tree image) and is built only from these parts. |
| `app/ui/format.py` | `rupee()` with Indian grouping (₹27,90,000), `rupee_short`, `pct`, `date_in` (05 Nov 2026), `datetime_in`. Display only. |
| `app/ui/charts.py` | Plotly figures (benchmark bars, DI bars) from data the pages already load. |
| `app/views/style_guide.py` | Hidden page: listed in the menu only with `COGNILEND_UI_DEBUG=1`. |
| `app/assets/logo.svg` | Generated logo (shield + tree + check). |
| `requirements-ui.txt` | `plotly==7.1.0` (UI only). `requirements.txt` untouched. |

**No business logic:** components only format values they are given; nothing computes EMI / FOIR / LTV / confidence.

Contrast: every text pair ≥ 4.5:1 in both themes → `regression/contrast_report.md` (PASS).

One finding: in Streamlit 1.66 a `st.html` block containing only `<style>` never reaches the page, so the
stylesheet is injected with `st.markdown(..., unsafe_allow_html=True)`.

Screens: `after/style_guide/style_guide_light.png`, `after/style_guide/style_guide_dark.png`.

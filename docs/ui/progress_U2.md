# U2: Layout and navigation

- **Menu** (`common.sidebar_nav`, drawn by every page): sections *Apply* (Home, New Application), *Operations*
  (Review Queue, Audit Explorer), *Governance* (Model & Policy, Fairness, Model Comparison), *Advisory*
  (Stress Twin), each with an icon; the current page is highlighted. `app/streamlit_app.py` registers the pages
  with `st.navigation(position='hidden')` and keeps every original URL (`/New_Application?demo=…`, etc.).
  - Why the menu is drawn by the pages: if the first request after a server start is a deep link, Streamlit serves
    it in legacy `pages/` mode, before `st.navigation` has run. Drawing the menu with `st.page_link` on every page
    (and hiding the auto list) gives the same menu in both cases. `app/pages/` cannot be renamed (tests glob it).
- **Header** (`common.appbar`): logo, name, tagline, and pills with the policy and model version in force, read
  from `repo().versions()` (the same data the Model & Policy page shows).
- **Home** (`app/views/home.py`): Rules → Tree → Audit → Fairness flow, the three outcome badges, live tiles
  (Approved / Rejected / Human Review / Open reviews from `repo().summary()`), the audit-chain status
  (`verify_chain()`), quick links and one-click demo links. "Applications today" needs a dated query →
  `backend_wishlist.md` W1.
- **Footer** (`common.footer`, plus a compact one in the sidebar): college, programme, initiative, guide, groups.
  No department name appears anywhere in the repository, so the programme line ("TY AIML Mini Project") is used.

Checks: every page reachable from the menu (`after/screens/*.png`); refresh keeps the page (URL-based); 1366×768 and
390 px: `after/grid/home__1366_light.png`, `after/grid/home__390_light.png`.

Before / after: `baseline/screens/home.png` → `after/screens/home.png`.

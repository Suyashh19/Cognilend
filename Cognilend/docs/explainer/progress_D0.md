# Progress — D0 (Inventory and outline)

Date: 2026-10-16

## Done
- `source_map.md`: every module, app page, config, data file, script, report and test file, one line each.
- `facts.json`: 164 facts, each read by `scripts/collect_facts.py` from its source file via a locator (JSON key path,
  YAML key, CSV row, regex, or JUnit attribute). 0 missing. `--check` mode re-reads all sources for D7.
- `outline.md`: chapters 0–26, none dropped; awaiting approval.

## Findings to carry forward
- Loan.csv was never supplied → Ch 5 Status note. `data/raw/loan` is an unused 10,000-row file, not Loan.csv.
- Test count: `junit.xml` = 314/314 (before add-on); `reports/pytest_after_addons.txt` is cut off after 46 add-on
  tests collected → run pytest fresh in D4.
- Two different "auto" numbers exist, and they must not be confused:
  ML-layer routing on test = 0.6049 auto share and 0.8893 accuracy [routing.json];
  full pipeline = 69.9 % auto-decided (rules + model) and 0.9042 accuracy for model auto-decisions [pipeline_eval.md].
- No Graphviz binary, no pandoc, no python-docx. matplotlib, the graphviz Python package, playwright and MiKTeX are available.
  Plan: draw diagrams with matplotlib; install python-docx in a separate env under docs/explainer/ for D6.

## Project files changed
None.

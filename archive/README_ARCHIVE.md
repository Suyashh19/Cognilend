# archive/

Pre-integration work from the `old` branch (which already contained
`docs/project-readme` and `feature/loan-approval-database`): early preprocessing
scripts and reports, the MySQL schema (`database/`), the `rule_ui` demo, and the
original model-training code. The running app (`app/`, `src/`, `config/`, ...)
does not import, run or test anything from here. Full commit history for these
files is preserved through the merge (`git log -- archive/<path>` follows them
only by path; `git log origin/old` shows the original commits).

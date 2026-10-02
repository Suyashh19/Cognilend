# CogniLend Rule Layer: live demo page

> ⚠️ **Prototype / test UI only.** This page exists to demo and test the rule layer in
> `database/`. It is not the final applicant or officer interface. That will be built by G15
> during integration (see "Integration plan" in `database/README.md`).

A light-themed web page that runs the **real** Layer 1 rule engine (the stored procedures in
`database/04_procedures.sql`). The page does no checking of its own: every validation, rule
result and block comes from MySQL.

## First time (once)

```bash
bash rule_ui/setup.sh      # asks for your sudo password
```

It does four things:
1. creates the MySQL user `cl_web` with a random password, saved only in `rule_ui/.env`
2. adds a demo blacklist entry (`FRAUDPAN0002`)
3. runs `database/09_rule_set_v1_1.sql`, which activates rule set **v1.1** (R03 limit 65 → 70)
4. installs the Python packages into `rule_ui/.venv`

## Every time

```bash
bash rule_ui/run.sh        # then open http://127.0.0.1:5000
```

Stop it with Ctrl+C.

## What is on the page

| Section | What it shows |
|---|---|
| Edge-case scenarios | 15 one-click cases in 4 groups: normal, hard reject, soft → human, data and fraud safety |
| Result | The route taken (rejected / ML model / human), the verdict in plain words and every rule with ✅ ⚠️ ❌ 👤 ⏭️ |
| Rule book | The active rules from the database, plus the versions (v1.0 frozen, v1.1 active) |
| Try to tamper | 5 real UPDATE/DELETE attempts. The triggers block every one (and they are always rolled back) |
| Recent applications | The last 8 live applications and their status |
| Top-right pills | The active rule set, and whether the audit hash chain is intact |

## If you rebuild the database

Re-running `01_schema.sql` wipes everything. After 01–06 (and 08), run `bash rule_ui/setup.sh`
again: it re-creates the user and grants, and re-activates v1.1.

## Notes

- The PAN is hashed (SHA-256) before it reaches the database. Production would add a secret
  pepper; the demo uses a plain hash so the sample blacklist entries match.
- "Other open applications" (R09) only sees applications **inside CogniLend**. Checking other
  banks needs a credit bureau feed (CIBIL etc.), which is future work.
- `cl_web` has UPDATE/DELETE on four tables **only** so the tamper panel can show the triggers
  blocking a real attempt. The page runs those as fixed statements and always rolls them back.

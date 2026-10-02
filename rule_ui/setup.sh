#!/usr/bin/env bash
# One-time setup for the rule-layer demo page.
#   bash rule_ui/setup.sh        (asks for your sudo password once)
# Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

# 1) password for the web app's DB user, kept only in .env (never in code)
if [[ -f .env ]] && grep -q '^DB_PASS=' .env; then
    DB_PASS=$(grep '^DB_PASS=' .env | cut -d= -f2-)
else
    DB_PASS=$(openssl rand -hex 16)
    cat > .env <<EOF
DB_HOST=localhost
DB_USER=cl_web
DB_PASS=$DB_PASS
DB_NAME=cognilend
EOF
    chmod 600 .env
fi

# 2) DB user. It reads everything and calls the procedures.
#    The four UPDATE/DELETE grants exist ONLY so the "Try to tamper" panel
#    can show the triggers blocking a real attempt. The page runs those
#    statements inside a transaction and always rolls back.
sudo mysql <<SQL
CREATE USER IF NOT EXISTS 'cl_web'@'localhost' IDENTIFIED BY '$DB_PASS';
ALTER USER 'cl_web'@'localhost' IDENTIFIED BY '$DB_PASS';
GRANT SELECT, EXECUTE ON cognilend.* TO 'cl_web'@'localhost';
GRANT UPDATE ON cognilend.loan_application TO 'cl_web'@'localhost';
GRANT UPDATE ON cognilend.decision         TO 'cl_web'@'localhost';
GRANT UPDATE ON cognilend.policy_rule      TO 'cl_web'@'localhost';
GRANT DELETE ON cognilend.audit_log        TO 'cl_web'@'localhost';

-- demo blacklist entry for the "Blacklisted PAN" preset (the sample
-- FRAUDPAN0001 is also used by the tests, with a date of birth that changes daily)
INSERT INTO cognilend.fraud_registry (id_hash, reason, source)
SELECT SHA2('FRAUDPAN0002', 256), 'Confirmed identity fraud (demo entry)', 'DEMO'
 WHERE NOT EXISTS (SELECT 1 FROM cognilend.fraud_registry
                    WHERE id_hash = SHA2('FRAUDPAN0002', 256));
SQL

# 3) rule set v1.1 (R03 limit 65 -> 70)
sudo mysql -t < ../database/09_rule_set_v1_1.sql

# 4) python packages
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -q flask mysql-connector-python python-dotenv

echo
echo "Setup done. Start the page with:  bash rule_ui/run.sh"

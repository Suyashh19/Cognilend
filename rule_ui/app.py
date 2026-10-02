"""
CogniLend rule-layer demo page.

Thin Flask wrapper around the stored procedures in database/04_procedures.sql.
All validation and every rule decision happen INSIDE MySQL; this file only
passes the form through and reads back what the database recorded.
"""
import hashlib
import json
import os
import uuid

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)

# form fields forwarded to sp_submit_application as-is (raw text), so the
# DATABASE decides what is valid, e.g. "abc" in income is rejected by MySQL
PAYLOAD_FIELDS = [
    "full_name", "date_of_birth", "gender", "dependents", "income_monthly",
    "credit_score", "dtir", "loan_amount", "term_months", "property_value",
    "occupancy_type", "credit_type", "co_applicant_credit_type",
    "credit_worthiness", "loan_type", "loan_purpose",
]


class DbUnavailable(Exception):
    pass


def connect(autocommit=True):
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            connection_timeout=10,
            user=os.getenv("DB_USER", "cl_web"),
            password=os.getenv("DB_PASS", ""),
            database=os.getenv("DB_NAME", "cognilend"),
            autocommit=autocommit,
        )
    except mysql.connector.Error as e:
        raise DbUnavailable(e.msg) from e


@app.errorhandler(DbUnavailable)
def db_down(e):
    return jsonify(error=f"Database not reachable ({e}). Is MySQL running and rule_ui/.env set up?"), 503


def call(cur, proc, *args, n_out):
    res = cur.callproc(proc, (*args, *([None] * n_out)))
    return res[-n_out:]


def query(cur, sql, params=None):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def plain(v):
    """Make DECIMAL / datetime values JSON-friendly."""
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def application_result(cur, app_id):
    app_row = query(cur, """
        SELECT a.application_id, a.status, a.soft_referral, a.age_at_application,
               ap.full_name, d.reason_text AS decision_reason
          FROM loan_application a
          JOIN applicant ap ON ap.applicant_id = a.applicant_id
          LEFT JOIN decision d ON d.decision_id = a.current_decision_id
         WHERE a.application_id = %s""", (app_id,))
    rules = query(cur, """
        SELECT pr.rule_code, pr.fact_key, pr.operator, re.threshold_used AS threshold,
               pr.severity, pr.on_missing, pr.reason_text, re.outcome,
               re.observed_value, rs.version_label
          FROM rule_evaluation re
          JOIN policy_rule pr ON pr.rule_id = re.rule_id
          JOIN rule_set rs    ON rs.rule_set_id = pr.rule_set_id
         WHERE re.application_id = %s
         ORDER BY pr.priority, pr.rule_id""", (app_id,))
    return {
        "application": {k: plain(v) for k, v in app_row[0].items()} if app_row else None,
        "rules": [{k: plain(v) for k, v in r.items()} for r in rules],
        "rule_set": rules[0]["version_label"] if rules else None,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/rules")
def rules():
    conn = connect()
    try:
        cur = conn.cursor()
        active = query(cur, """
            SELECT pr.rule_code, pr.fact_key, pr.operator, pr.threshold, pr.severity,
                   pr.on_missing, pr.reason_text
              FROM policy_rule pr JOIN rule_set rs ON rs.rule_set_id = pr.rule_set_id
             WHERE rs.is_active AND pr.is_active
             ORDER BY pr.priority, pr.rule_id""")
        versions = query(cur, """
            SELECT version_label, description, is_active,
                   EXISTS (SELECT 1 FROM decision d WHERE d.rule_set_id = rs.rule_set_id) AS frozen
              FROM rule_set rs
             WHERE version_label LIKE 'v%'
             ORDER BY rule_set_id""")
        return jsonify(
            rules=[{k: plain(v) for k, v in r.items()} for r in active],
            versions=[{k: plain(v) for k, v in r.items()} for r in versions],
        )
    finally:
        conn.close()


@app.post("/api/evaluate")
def evaluate():
    body = request.get_json(force=True) or {}
    pan = str(body.get("pan") or "").strip().upper()
    # raw PAN never reaches the database, only its SHA-256
    # (production adds a secret pepper; the demo uses a plain hash so the
    # sample blacklist entry for FRAUDPAN0001 matches)
    payload = {"id_hash": hashlib.sha256(pan.encode()).hexdigest() if pan else None}
    for f in PAYLOAD_FIELDS:
        v = body.get(f)
        if v is not None and str(v).strip() != "":
            payload[f] = str(v).strip()
    key = str(body.get("idempotency_key") or uuid.uuid4())

    conn = connect()
    try:
        cur = conn.cursor()
        app_id, outcome, msg = call(cur, "sp_submit_application",
                                    key, json.dumps(payload), "LIVE", n_out=3)
        result = {"submit": {"outcome": outcome, "message": msg, "application_id": app_id},
                  "idempotency_key": key}
        if outcome == "CREATED":
            r_out, r_msg = call(cur, "sp_run_rule_layer", app_id, n_out=2)
            result["rule_layer"] = {"outcome": r_out, "message": r_msg}
        if app_id:
            result.update(application_result(cur, app_id))
        return jsonify(result)
    finally:
        conn.close()


@app.get("/api/history")
def history():
    conn = connect()
    try:
        cur = conn.cursor()
        rows = query(cur, """
            SELECT a.application_id, ap.full_name, a.status, a.soft_referral,
                   DATE_FORMAT(CONVERT_TZ(a.submitted_at, '+00:00', '+05:30'), '%H:%i:%s') AS time_ist
              FROM loan_application a JOIN applicant ap ON ap.applicant_id = a.applicant_id
             WHERE a.source = 'LIVE'
             ORDER BY a.application_id DESC LIMIT 8""")
        return jsonify(rows=[{k: plain(v) for k, v in r.items()} for r in rows])
    finally:
        conn.close()


@app.get("/api/audit")
def audit():
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM audit_log")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM v_audit_chain_check")
        problems = cur.fetchone()[0]
        return jsonify(total=total, problems=problems)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# "Try to tamper": each attack is a FIXED statement (never user input), run in
# a transaction that is ALWAYS rolled back, so even an unexpected success
# changes nothing.
# ---------------------------------------------------------------------------
def pick(cur, sql):
    cur.execute(sql)
    row = cur.fetchone()
    return row[0] if row else None


TAMPER = {
    "status": {
        "title": "Approve a rejected application directly",
        "target": "SELECT application_id FROM loan_application WHERE status = 'RULE_REJECTED' "
                  "ORDER BY application_id DESC LIMIT 1",
        "sql": "UPDATE loan_application SET status = 'AUTO_APPROVED' WHERE application_id = %s",
        "what": "Change application #{id} from RULE_REJECTED to AUTO_APPROVED",
    },
    "inputs": {
        "title": "Change an applicant's credit score after submission",
        "target": "SELECT application_id FROM loan_application ORDER BY application_id DESC LIMIT 1",
        "sql": "UPDATE loan_application SET credit_score = 900 WHERE application_id = %s",
        "what": "Set credit score of application #{id} to 900",
    },
    "decision": {
        "title": "Rewrite a recorded decision",
        "target": "SELECT decision_id FROM decision WHERE outcome = 'REJECTED' "
                  "ORDER BY decision_id DESC LIMIT 1",
        "sql": "UPDATE decision SET outcome = 'APPROVED' WHERE decision_id = %s",
        "what": "Change decision #{id} from REJECTED to APPROVED",
    },
    "audit": {
        "title": "Delete an audit log entry",
        "target": "SELECT MIN(audit_id) FROM audit_log",
        "sql": "DELETE FROM audit_log WHERE audit_id = %s",
        "what": "Delete audit row #{id}",
    },
    "rule": {
        "title": "Quietly loosen a rule that already made decisions",
        "target": "SELECT rule_set_id FROM decision ORDER BY decision_id DESC LIMIT 1",
        "sql": "UPDATE policy_rule SET threshold = 300 "
               "WHERE rule_code = 'R05_MIN_SCORE' AND rule_set_id = %s",
        "what": "Lower the minimum credit score to 300 in rule set #{id}",
    },
}


@app.post("/api/tamper/<kind>")
def tamper(kind):
    attack = TAMPER.get(kind)
    if not attack:
        return jsonify(error="Unknown action"), 404
    conn = connect(autocommit=False)
    try:
        cur = conn.cursor()
        target = pick(cur, attack["target"])
        if target is None:
            conn.rollback()
            return jsonify(title=attack["title"], blocked=None,
                           message="Nothing to target yet. Run a few applications first.")
        what = attack["what"].format(id=target)
        try:
            cur.execute(attack["sql"], (target,))
            blocked, message = False, f"NOT blocked ({cur.rowcount} row(s)). Rolled back anyway."
        except mysql.connector.Error as e:
            blocked, message = True, e.msg
        conn.rollback()
        return jsonify(title=attack["title"], attempt=what, blocked=blocked, message=message)
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

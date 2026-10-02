// CogniLend rule-layer demo page. All decisions come from MySQL; this file
// only fills the form, calls the API and draws what the database returned.

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------------------------------------------------------------- helpers
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const pick = (s) => s[Math.floor(Math.random() * s.length)];
function randPAN() {
  let p = '';
  for (let i = 0; i < 5; i++) p += pick(LETTERS);
  for (let i = 0; i < 4; i++) p += Math.floor(Math.random() * 10);
  return p + pick(LETTERS);
}
function newKey() {
  if (window.crypto?.randomUUID) return crypto.randomUUID();
  return 'k-' + Date.now() + '-' + Math.random().toString(16).slice(2);
}
function dobForAge(age) {
  const d = new Date();
  d.setFullYear(d.getFullYear() - age);
  d.setDate(d.getDate() - 10);
  return d.toISOString().slice(0, 10);
}
const inr = (n) => '₹' + Number(n).toLocaleString('en-IN');

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ---------------------------------------------------------------- rule wording
const RULES = {
  R01_BLACKLIST:      { title: 'Not on fraud blacklist', unit: 'flag' },
  R02_MIN_AGE:        { title: 'Minimum age', unit: 'yrs' },
  R03_MAX_AGE_MATUR:  { title: 'Age when the loan ends', unit: 'yrs' },
  R04_INCOME:         { title: 'Has an income', unit: 'inr' },
  R05_MIN_SCORE:      { title: 'Credit score', unit: 'pts' },
  R06_MAX_DTI:        { title: 'Existing debt vs income (DTI)', unit: 'pct' },
  R07_MAX_LTV:        { title: 'Loan vs property value (LTV)', unit: 'pct' },
  R08_LOAN_TO_INCOME: { title: 'Loan vs yearly income', unit: 'x' },
  R09_PARALLEL_APPS:  { title: 'Other open applications with us', unit: 'count' },
  R10_REAPPLY_ABUSE:  { title: 'Rejections in the last 30 days', unit: 'count' },
};
const OPS = { '>=': '≥', '<=': '≤', '>': '>', '<': '<', '=': '=', '!=': '≠' };
const ON_MISSING = { FAIL: 'Reject', REFER: 'Send to a human', SKIP: 'Skip the rule' };

function fmt(code, v) {
  if (v === null || v === undefined || v === '') return 'no data';
  const n = Number(v);
  const unit = RULES[code]?.unit;
  const clean = Number.isInteger(n) ? n : +n.toFixed(2);
  switch (unit) {
    case 'flag':  return n ? 'Listed' : 'Not listed';
    case 'yrs':   return `${clean} yrs`;
    case 'inr':   return inr(clean);
    case 'pct':   return `${clean}%`;
    case 'x':     return `${clean}×`;
    default:      return String(clean);
  }
}
function limitText(r) {
  if (RULES[r.rule_code]?.unit === 'flag') return 'must not be listed';
  return `${OPS[r.operator] || r.operator} ${fmt(r.rule_code, r.threshold)}`;
}

// ---------------------------------------------------------------- form
const FIELDS = ['full_name', 'pan', 'date_of_birth', 'gender', 'income_monthly', 'credit_score', 'dtir',
  'dependents', 'loan_amount', 'term_months', 'property_value', 'occupancy_type', 'credit_type',
  'co_applicant_credit_type', 'credit_worthiness', 'loan_type', 'loan_purpose'];

function fillForm(d) {
  const f = $('#form');
  for (const k of FIELDS) if (f.elements[k]) f.elements[k].value = d[k] ?? '';
}
function readForm() {
  const f = $('#form');
  const d = {};
  for (const k of FIELDS) if (f.elements[k]) d[k] = f.elements[k].value;
  return d;
}

const base = (over = {}) => ({
  full_name: 'Demo Applicant', pan: randPAN(), date_of_birth: dobForAge(32), gender: 'F',
  income_monthly: '85000', credit_score: '745', dtir: '30', dependents: '1',
  loan_amount: '2500000', term_months: '240', property_value: '4000000', occupancy_type: 'pr',
  credit_type: 'CIB', co_applicant_credit_type: 'EXP', credit_worthiness: 'l1',
  loan_type: 'type1', loan_purpose: 'p3', ...over,
});

const evaluate = (data, key = newKey()) => api('/api/evaluate', { ...data, idempotency_key: key });

// single-step scenario: fill, run, show
const single = (data) => async () => {
  fillForm(data);
  return { res: await evaluate(data), steps: [] };
};

// ---------------------------------------------------------------- scenarios
const PRESETS = [
  { group: 'Normal: passes the rules', color: 'var(--green)', items: [
    { name: 'Asha, ideal applicant', note: 'Everything within policy',
      run: () => single(base({ full_name: 'Asha Patil' }))() },
    { name: 'Sunita, 42, 25-year loan', note: 'Ends at 67: OK under v1.1 (limit 70)',
      run: () => single(base({ full_name: 'Sunita Kulkarni', date_of_birth: dobForAge(42), term_months: '300' }))() },
    { name: 'Unsecured personal loan', note: 'No property: LTV rule skipped',
      run: () => single(base({ full_name: 'Neha Joshi', property_value: '', loan_amount: '300000', term_months: '36' }))() },
  ]},
  { group: 'Hard rules: reject (final)', color: 'var(--red)', items: [
    { name: 'Rohan, 19', note: 'Below minimum age 21',
      run: () => single(base({ full_name: 'Rohan Deshmukh', gender: 'M', date_of_birth: dobForAge(19) }))() },
    { name: 'Ramesh, 45, 30-year loan', note: 'Would be 75 when the loan ends',
      run: () => single(base({ full_name: 'Ramesh Shinde', gender: 'M', date_of_birth: dobForAge(45), term_months: '360' }))() },
    { name: 'No income', note: 'Income ₹0',
      run: () => single(base({ full_name: 'Kiran Pawar', gender: 'M', income_monthly: '0' }))() },
    { name: 'Low score + high debt', note: 'Two rules fail: both reasons shown',
      run: () => single(base({ full_name: 'Meera Nair', credit_score: '520', dtir: '58' }))() },
    { name: 'Loan is 95% of property', note: 'LTV above 90%',
      run: () => single(base({ full_name: 'Sanjay Gupta', gender: 'M', loan_amount: '3800000' }))() },
    { name: 'Blacklisted PAN', note: 'In the fraud registry',
      run: () => single(base({ full_name: 'Vikram Rao', gender: 'M', pan: 'FRAUDPAN0002', date_of_birth: '1988-06-15' }))() },
  ]},
  { group: 'Soft rules: send to a human', color: 'var(--amber)', items: [
    { name: 'Priya, no credit history', note: 'First-time borrower: not rejected',
      run: () => single(base({ full_name: 'Priya Iyer', credit_score: '' }))() },
    { name: 'Loan is 8× yearly income', note: 'Big loan, possible over-borrowing',
      run: () => single(base({ full_name: 'Aditya Rane', gender: 'M', income_monthly: '40000',
        loan_amount: '3840000', property_value: '6000000' }))() },
    { name: 'Two applications at once', note: 'Possible loan stacking', run: async () => {
      const pan = randPAN();
      const first = base({ full_name: 'Arjun Mehta', gender: 'M', pan });
      const r1 = await evaluate(first);
      const second = { ...first, loan_amount: '500000', term_months: '60' };
      fillForm(second);
      const r2 = await evaluate(second);
      return { res: r2, steps: [
        `Application #${r1.submit.application_id} submitted → ${r1.rule_layer?.outcome} (still open, waiting for the model)`,
        'A second application with the same PAN arrives while the first is still open',
      ]};
    }},
    { name: 'Rejected 3 times, tries again', note: 'Probing the system', run: async () => {
      const pan = randPAN();
      const steps = [];
      for (let i = 1; i <= 3; i++) {
        const r = await evaluate(base({ full_name: 'Rahul Verma', gender: 'M', pan, credit_score: String(505 + i * 10) }));
        steps.push(`Attempt ${i}: #${r.submit.application_id}, score ${505 + i * 10} → ${r.rule_layer?.outcome}`);
      }
      const last = base({ full_name: 'Rahul Verma', gender: 'M', pan, credit_score: '560' });
      fillForm(last);
      const r4 = await evaluate(last);
      steps.push('Attempt 4: numbers tweaked just enough to pass the score rule');
      return { res: r4, steps };
    }},
  ]},
  { group: 'Data & fraud safety', color: 'var(--blue)', items: [
    { name: 'Double-click on Submit', note: 'Same request sent twice', run: async () => {
      const d = base({ full_name: 'Farhan Shaikh', gender: 'M' });
      fillForm(d);
      const key = newKey();
      const r1 = await evaluate(d, key);
      const r2 = await evaluate(d, key);
      return { res: r2, steps: [
        `First click → application #${r1.submit.application_id} created`,
        'Second click, same request key → checked by the database',
      ]};
    }},
    { name: 'Typos and bad values', note: '"65,000", 30 Feb, "abc"…',
      run: () => single(base({ full_name: 'Test Typo', income_monthly: '65,000', date_of_birth: '2001-02-30',
        credit_score: 'abc', occupancy_type: 'villa', loan_amount: '' }))() },
    { name: 'Same PAN, different birth date', note: 'Identity mismatch', run: async () => {
      const pan = randPAN();
      const first = base({ full_name: 'Anita Desai', pan, date_of_birth: '1990-03-10' });
      const r1 = await evaluate(first);
      const second = { ...first, date_of_birth: '1994-08-21' };
      fillForm(second);
      const r2 = await evaluate(second);
      return { res: r2, steps: [
        `Application #${r1.submit.application_id} submitted with date of birth 1990-03-10`,
        'Same PAN comes back with date of birth 1994-08-21',
      ]};
    }},
  ]},
];

function renderPresets() {
  $('#presets').innerHTML = PRESETS.map((g, gi) => `
    <div class="preset-group">
      <h3><span class="dot" style="background:${g.color}"></span>${esc(g.group)}</h3>
      <div class="preset-list">
        ${g.items.map((p, pi) => `
          <button type="button" class="preset" data-g="${gi}" data-p="${pi}">
            ${esc(p.name)}<small>${esc(p.note)}</small>
          </button>`).join('')}
      </div>
    </div>`).join('');
  $('#presets').addEventListener('click', (e) => {
    const btn = e.target.closest('.preset');
    if (!btn) return;
    document.querySelectorAll('.preset').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    const p = PRESETS[btn.dataset.g].items[btn.dataset.p];
    runScenario(p.run, p.name);
  });
}

// ---------------------------------------------------------------- run + render
let busy = false;
function setBusy(on) {
  busy = on;
  document.querySelectorAll('.preset, #form button').forEach((b) => { b.disabled = on; });
}

async function runScenario(fn, title) {
  if (busy) return;
  setBusy(true);
  $('#result').innerHTML = '<p class="empty">Running inside MySQL…</p>';
  try {
    const { res, steps } = await fn();
    renderResult(res, steps, title);
  } catch (err) {
    $('#result').innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
  } finally {
    setBusy(false);
    refreshSide();
  }
}

function routeOf(res) {
  const s = res.submit.outcome;
  if (s === 'INVALID' || s === 'ERROR') return 'invalid';
  const rl = res.rule_layer?.outcome;
  if (rl === 'REJECTED') return 'reject';
  if (rl === 'PASS') return 'model';
  if (rl === 'PASS_REFER') return 'human';
  // duplicate: describe the ORIGINAL application's state
  const a = res.application;
  if (!a) return 'none';
  if (a.status === 'RULE_REJECTED') return 'reject';
  if (a.status === 'PENDING_MODEL') return Number(a.soft_referral) ? 'human' : 'model';
  if (a.status === 'PENDING_REVIEW' || a.status.startsWith('OFFICER')) return 'human';
  return 'model';
}

function flowHtml(route) {
  const n = (label, on, color) => `<span class="node ${on ? 'on ' + color : ''}">${label}</span>`;
  const arrow = '<span class="arrow">→</span>';
  return `<div class="flow">
    ${n('Application', true, 'blue')}${arrow}
    ${n(route === 'invalid' ? 'Input checks ✗' : 'Input checks ✓', true, route === 'invalid' ? 'red' : 'blue')}${arrow}
    ${n('Rule layer', route !== 'invalid', 'blue')}${arrow}
    <span class="fork">
      ${n('Rejected (final)', route === 'reject', 'red')}
      ${n('ML model decides', route === 'model', 'green')}
      ${n('ML model → human officer', route === 'human', 'amber')}
    </span>
  </div>`;
}

const list = (items) => `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join('')}</ul>`;
const splitReasons = (msg) => String(msg || '')
  .replace(/^Will go to human review:\s*/, '').split(' | ').filter(Boolean);

function verdictHtml(res) {
  const s = res.submit;
  if (s.outcome === 'INVALID') {
    if (/^Identity mismatch/.test(s.message)) {
      return `<div class="verdict red"><div class="big">⛔ Blocked: identity mismatch</div>
        <p>This PAN is already on record with a different date of birth. Nothing was stored; the attempt
        is logged for fraud review.</p></div>`;
    }
    return `<div class="verdict grey"><div class="big">✋ Not accepted: please fix the input</div>
      <p>The database checked every field and lists <b>all</b> problems at once. Nothing was stored.</p>
      ${list(String(s.message).split('; '))}</div>`;
  }
  if (s.outcome === 'ERROR') {
    return `<div class="verdict red"><div class="big">Error</div><p>${esc(s.message)}</p></div>`;
  }
  if (s.outcome === 'DUPLICATE') {
    const a = res.application || {};
    return `<div class="verdict blue"><div class="big">🔁 Duplicate caught</div>
      <p>Same request as application <b>#${esc(s.application_id)}</b>. No second application was created;
      the original is returned (status: ${esc(a.status)}).</p></div>`;
  }
  const rl = res.rule_layer || {};
  if (rl.outcome === 'REJECTED') {
    return `<div class="verdict red"><div class="big">❌ Rejected by policy (final)</div>
      <p>A <b>hard</b> rule failed. Neither the ML model nor a loan officer can override this.
      Every reason is recorded:</p>${list(splitReasons(rl.message))}</div>`;
  }
  if (rl.outcome === 'PASS') {
    return `<div class="verdict green"><div class="big">✅ Passed all rules</div>
      <p>Next step: the ML model scores this application.</p></div>`;
  }
  if (rl.outcome === 'PASS_REFER') {
    return `<div class="verdict amber"><div class="big">👤 Passed, but a human must check</div>
      <p>No hard rule failed, so it is <b>not rejected</b>. But the model is not allowed to decide alone:
      a loan officer reviews it because:</p>${list(splitReasons(rl.message))}</div>`;
  }
  return `<div class="verdict red"><div class="big">${esc(rl.outcome || s.outcome)}</div><p>${esc(rl.message || s.message)}</p></div>`;
}

function ruleRowHtml(r) {
  const info = RULES[r.rule_code] || { title: r.rule_code };
  let cls, ic, detail;
  switch (r.outcome) {
    case 'PASS':
      cls = 'pass'; ic = '✅'; detail = 'Passed'; break;
    case 'FAIL':
      if (r.severity === 'HARD') { cls = 'hard'; ic = '❌'; detail = 'Hard rule failed → reject'; }
      else { cls = 'soft'; ic = '⚠️'; detail = 'Soft rule flagged → human review'; }
      break;
    case 'MISSING_REFER':
      cls = 'soft'; ic = '👤'; detail = 'Data missing → sent to a human, not rejected'; break;
    case 'MISSING_FAIL':
      cls = 'hard'; ic = '❌'; detail = 'Required data missing → reject'; break;
    case 'SKIPPED':
      cls = 'skip'; ic = '⏭️';
      detail = r.rule_code === 'R07_MAX_LTV' ? 'No property (unsecured loan) → rule does not apply'
        : 'Not enough data for this check → skipped';
      break;
    default:
      cls = 'skip'; ic = '•'; detail = r.outcome;
  }
  return `<div class="rule ${cls}">
    <div class="ic">${ic}</div>
    <div>
      <div class="name">${esc(info.title)} <span class="chip ${esc(r.severity)}">${esc(r.severity)}</span></div>
      <div class="detail">${esc(r.rule_code)} · ${esc(detail)}</div>
    </div>
    <div class="val"><b>${esc(fmt(r.rule_code, r.observed_value))}</b><br>
      <span class="detail">limit ${esc(limitText(r))}</span></div>
  </div>`;
}

function renderResult(res, steps, title) {
  const route = routeOf(res);
  const a = res.application;
  const rules = res.rules || [];
  $('#result').innerHTML = `
    ${title ? `<p class="hint"><b>Scenario:</b> ${esc(title)}</p>` : ''}
    ${steps.length ? `<ol class="steps">${steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}
    ${flowHtml(route)}
    ${verdictHtml(res)}
    ${rules.length ? `<div class="rule-list">${rules.map(ruleRowHtml).join('')}</div>` : ''}
    ${a ? `<p class="meta">Application #${esc(a.application_id)} · ${esc(a.full_name)} ·
      rule set ${esc(res.rule_set || '-')} · ${rules.length} rules evaluated and permanently logged</p>` : ''}
  `;
}

// ---------------------------------------------------------------- side panels
const STATUS = {
  RULE_REJECTED: ['Rejected by rules', 'red'],
  PENDING_MODEL: ['Waiting for ML model', 'green'],
  PENDING_REVIEW: ['With a loan officer', 'amber'],
  AUTO_APPROVED: ['Auto-approved', 'green'],
  AUTO_REJECTED: ['Auto-rejected', 'red'],
  OFFICER_APPROVED: ['Approved by officer', 'green'],
  OFFICER_REJECTED: ['Rejected by officer', 'red'],
  WITHDRAWN: ['Withdrawn', 'grey'],
  RECEIVED: ['Received', 'grey'],
};

async function loadHistory() {
  try {
    const { rows } = await api('/api/history');
    $('#history').innerHTML = `<tr><th>#</th><th>Applicant</th><th>Status</th><th>Time (IST)</th></tr>` +
      (rows.length ? rows.map((r) => {
        let [label, color] = STATUS[r.status] || [r.status, 'grey'];
        if (r.status === 'PENDING_MODEL' && Number(r.soft_referral)) { label = 'Model → human (flagged)'; color = 'amber'; }
        return `<tr><td>${esc(r.application_id)}</td><td>${esc(r.full_name)}</td>
          <td><span class="status ${color}">${esc(label)}</span></td><td>${esc(r.time_ist)}</td></tr>`;
      }).join('') : `<tr><td colspan="4" class="muted">No live applications yet.</td></tr>`);
  } catch (err) {
    $('#history').innerHTML = `<tr><td class="muted">${esc(err.message)}</td></tr>`;
  }
}

async function loadAudit() {
  const pill = $('#pill-audit');
  try {
    const { total, problems } = await api('/api/audit');
    pill.className = 'pill ' + (problems ? 'bad' : 'ok');
    pill.textContent = problems ? `Audit chain BROKEN (${problems} problem rows)`
      : `🔗 Audit chain intact · ${Number(total).toLocaleString('en-IN')} entries`;
  } catch {
    pill.className = 'pill bad'; pill.textContent = 'Database offline';
  }
}

async function loadRules() {
  try {
    const { rules, versions } = await api('/api/rules');
    const active = versions.find((v) => Number(v.is_active));
    $('#pill-ruleset').className = 'pill info';
    $('#pill-ruleset').textContent = `Rule set ${active ? active.version_label : '(test clone active)'}`;
    $('#rulebook-version').textContent = active ? `(active: ${active.version_label})` : '';
    $('#versions').innerHTML = versions.map((v) => `
      <div class="version ${Number(v.is_active) ? 'active' : ''}">
        <b>${esc(v.version_label)}</b> · ${Number(v.is_active) ? 'ACTIVE' : 'inactive'}
        ${Number(v.frozen) ? ' · 🔒 frozen (already used for decisions)' : ''}<br>
        <span class="muted">${esc(v.description || '')}</span>
      </div>`).join('');
    $('#rulebook').innerHTML = `<tr><th>Rule</th><th>What it checks</th><th>Limit</th><th>Type</th><th>If data is missing</th><th>Reason shown to applicant</th></tr>` +
      rules.map((r) => `<tr>
        <td><b>${esc(r.rule_code)}</b></td>
        <td>${esc(RULES[r.rule_code]?.title || r.fact_key)}</td>
        <td>${esc(limitText(r))}</td>
        <td><span class="chip ${esc(r.severity)}">${esc(r.severity)}</span></td>
        <td>${esc(ON_MISSING[r.on_missing] || r.on_missing)}</td>
        <td class="muted">${esc(r.reason_text)}</td>
      </tr>`).join('');
  } catch (err) {
    $('#rulebook').innerHTML = `<tr><td><div class="error-box">${esc(err.message)}</div></td></tr>`;
    $('#pill-ruleset').className = 'pill bad';
    $('#pill-ruleset').textContent = 'Database offline';
  }
}

function refreshSide() { loadHistory(); loadAudit(); loadRules(); }

// ---------------------------------------------------------------- tamper
const TAMPER = [
  ['status', 'Approve a rejected application directly'],
  ['inputs', "Change a credit score after submission"],
  ['decision', 'Rewrite a recorded decision'],
  ['audit', 'Delete an audit log entry'],
  ['rule', 'Quietly loosen a rule that already made decisions'],
];

function renderTamper() {
  $('#tamper-buttons').innerHTML = TAMPER.map(([k, label]) =>
    `<button type="button" class="btn" data-k="${k}">🔓 ${esc(label)}</button>`).join('');
  $('#tamper-buttons').addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    btn.disabled = true;
    let html;
    try {
      const r = await api(`/api/tamper/${btn.dataset.k}`, {});
      if (r.blocked === true) {
        html = `<div class="tamper-entry blocked"><div class="t">🛡️ Blocked by the database</div>
          Tried: ${esc(r.attempt)}<br>MySQL said: <code>${esc(r.message)}</code></div>`;
      } else if (r.blocked === false) {
        html = `<div class="tamper-entry leak"><div class="t">⚠️ Not blocked</div>
          Tried: ${esc(r.attempt)}<br>${esc(r.message)}</div>`;
      } else {
        html = `<div class="tamper-entry none">${esc(r.message)}</div>`;
      }
    } catch (err) {
      html = `<div class="tamper-entry leak">${esc(err.message)}</div>`;
    }
    $('#tamper-log').insertAdjacentHTML('afterbegin', html);
    btn.disabled = false;
    loadAudit();
  });
}

// ---------------------------------------------------------------- init
$('#form').addEventListener('submit', (e) => {
  e.preventDefault();
  document.querySelectorAll('.preset').forEach((b) => b.classList.remove('active'));
  const data = readForm();
  runScenario(async () => ({ res: await evaluate(data), steps: [] }), null);
});
$('#btn-clear').addEventListener('click', () => {
  fillForm(base({ full_name: '', pan: '', date_of_birth: '', income_monthly: '', credit_score: '', dtir: '',
    dependents: '', loan_amount: '', term_months: '', property_value: '' }));
  $('#result').innerHTML = '<p class="empty">Pick a scenario or fill the form, then press <b>Run rule layer</b>.</p>';
});
$('#btn-refresh').addEventListener('click', loadHistory);

renderPresets();
renderTamper();
fillForm(base({ full_name: 'Asha Patil' }));
refreshSide();

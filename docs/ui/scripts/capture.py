"""Screenshots of every page and every demo case through a real browser (Playwright + installed Chrome / Edge).

    python docs/ui/scripts/capture.py <out_dir> [--widths 1366] [--themes light] [--only demo_auto_approve,home]

Starts `streamlit run app/streamlit_app.py` headless on a spare port, waits for each page to finish rendering
(no "running" widget), saves a full-page PNG per target / width / theme, and writes <out_dir>/timings.json with
the seconds from navigation to a settled page (used for the U6 load-time comparison).

The same URLs work on the old and the new UI (page url paths are kept), so before/after shots are comparable.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOIR_POSSIBLE = {'Age': 35, 'Gender': 'Female', 'Marital_Status': 'Married', 'Dependents': 1,
                 'Employment_Type': 'Salaried', 'Work_Experience': 10, 'Monthly_Income': 60000, 'Existing_EMI': 0,
                 'CIBIL_Score': 800, 'Loan_Type': 'Home', 'Loan_Amount': 6000000, 'Loan_Tenure': 240,
                 'Collateral_Value': 9000000, 'Property_Area': 'Urban', 'Loan_ID': 'SHOT-FOIR',
                 'Applicant_ID': 'SHOT-A1'}
DEMOS = ['hard_reject', 'auto_approve', 'auto_reject', 'soft_review', 'low_confidence', 'lock', 'malformed']
PAGES = [('home', ''), ('review_queue', 'Officer_Review_Queue'), ('audit_explorer', 'Audit_Explorer?q=DEMO-LOCK'),
         ('model_and_policy', 'Model_and_Policy'), ('fairness_dashboard', 'Fairness_Dashboard'),
         ('stress_twin', 'Stress_Twin'), ('model_comparison', 'Model_Comparison'),
         ('new_application_form', 'New_Application')]
MAX_LABEL = 'See maximum approvable amount'
JSON_TAB = 'Raw JSON (any input, incl. malformed)'


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_healthy(port, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if urllib.request.urlopen(f'http://localhost:{port}/_stcore/health', timeout=2).read() == b'ok':
                return
        except OSError:
            time.sleep(1)
    raise SystemExit('streamlit did not start')


def settle(page, extra=1500):
    page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=240_000)
    page.wait_for_timeout(extra)


def open_page(page, port, path):
    t0 = time.perf_counter()
    page.goto(f'http://localhost:{port}/{path}', wait_until='networkidle', timeout=240_000)
    page.wait_for_selector('h1', timeout=240_000)
    settle(page, 300)
    return time.perf_counter() - t0


def click_max(page, expect):
    btn = page.get_by_role('button', name=MAX_LABEL)
    btn.wait_for(timeout=240_000)
    btn.click()
    page.get_by_text(expect, exact=False).first.wait_for(timeout=240_000)
    settle(page)


def targets(only):
    out = [(f'demo_{d}', f'New_Application?demo={d}', 'demo') for d in DEMOS]
    out += [('max_amount_possible', 'New_Application', 'max_possible'),
            ('max_amount_not_possible', 'New_Application?demo=auto_reject', 'max_not_possible')]
    out += [(n, p, 'page') for n, p in PAGES]
    return [t for t in out if not only or t[0] in only]


def run(out: Path, widths, themes, only, tall=0):
    out.mkdir(parents=True, exist_ok=True)
    timings = {}
    from playwright.sync_api import sync_playwright
    for theme in themes:
        port = free_port()
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        server = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'app' / 'streamlit_app.py'),
                                   '--server.port', str(port), '--server.headless', 'true',
                                   '--browser.gatherUsageStats', 'false', '--theme.base', theme],
                                  cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_healthy(port)
            with sync_playwright() as pw:
                browser = None
                for channel in ('chrome', 'msedge'):
                    try:
                        browser = pw.chromium.launch(channel=channel, headless=True)
                        break
                    except Exception:  # noqa: BLE001 - try the next installed browser
                        continue
                if browser is None:
                    raise SystemExit('no Chrome / Edge found')
                for width in widths:
                    height = tall or (768 if width >= 1024 else 844)
                    for name, path, kind in targets(only):
                        page = browser.new_page(viewport={'width': width, 'height': height}, color_scheme=theme)
                        secs = open_page(page, port, path)
                        if kind in ('demo', 'max_not_possible'):
                            page.get_by_text('Audit-log ID').first.wait_for(timeout=240_000)
                            settle(page)
                        if kind == 'max_not_possible':
                            click_max(page, 'No lower amount can be approved')
                        if kind == 'max_possible':
                            page.get_by_role('tab', name=JSON_TAB).click()
                            area = page.locator('textarea').first
                            area.fill(json.dumps(FOIR_POSSIBLE))
                            area.press('Control+Enter')
                            page.wait_for_timeout(600)
                            page.get_by_role('button', name='Submit JSON').click()
                            page.get_by_text('Audit-log ID').first.wait_for(timeout=240_000)
                            settle(page)
                            click_max(page, 'Can be approved up to')
                        if kind == 'page':
                            settle(page, 2000)
                        overflow = page.evaluate('() => document.documentElement.scrollWidth > window.innerWidth')
                        suffix = '' if (len(widths) == 1 and len(themes) == 1) else f'__{width}_{theme}'
                        target = out / f'{name}{suffix}.png'
                        page.screenshot(path=str(target), full_page=True)
                        timings[f'{name}{suffix}'] = {'load_seconds': round(secs, 2),
                                                      'horizontal_overflow': bool(overflow)}
                        page.close()
                        print('saved', target.name, f'{secs:.1f}s', 'OVERFLOW' if overflow else '',
                              flush=True)
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=30)
    (out / 'timings.json').write_text(json.dumps(timings, indent=1), encoding='utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--widths', default='1366')
    ap.add_argument('--themes', default='light')
    ap.add_argument('--only', default='')
    ap.add_argument('--tall', type=int, default=0, help='viewport height (Streamlit scrolls inside its own container, '
                    'so a tall viewport is needed to capture a whole result)')
    a = ap.parse_args()
    run(Path(a.out).resolve(), [int(w) for w in a.widths.split(',')], a.themes.split(','),
        set(filter(None, a.only.split(','))), a.tall)

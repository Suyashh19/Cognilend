"""Screenshots of the max-approvable-amount panel -> reports/screens/max_amount/.

    python scripts/addons/max_amount_screens.py

Cases: FOIR rejection (amount shown), LTV rejection (amount shown), CIBIL rejection (not possible), model rejection
(demo auto_reject), plus an Approved demo with the flag on (no button). Uses the app's normal database, like
scripts/screenshots.py. Each case is submitted through the "Raw JSON" tab and the button is clicked.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from cognilend import config, demo

PORT = 8598
OUT = config.ROOT / 'reports' / 'screens' / 'max_amount'
B = demo.BASE
CASES = {
    'foir_rejection': {**B, 'Loan_ID': 'SHOT-FOIR', 'Applicant_ID': 'SHOT-A1', 'Monthly_Income': 60000,
                       'Loan_Amount': 6_000_000, 'Collateral_Value': 9_000_000},
    'ltv_rejection': {**B, 'Loan_ID': 'SHOT-LTV', 'Applicant_ID': 'SHOT-A2', 'Loan_Amount': 4_900_000,
                      'Collateral_Value': 5_000_000, 'Monthly_Income': 400000},
    'cibil_rejection': {**B, 'Loan_ID': 'SHOT-CIBIL', 'Applicant_ID': 'SHOT-A3', 'CIBIL_Score': 600},
}
DEMOS = {'model_rejection': 'auto_reject', 'approved_no_button': 'auto_approve'}


def wait_healthy(timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if urllib.request.urlopen(f'http://localhost:{PORT}/_stcore/health', timeout=2).read() == b'ok':
                return
        except OSError:
            time.sleep(1)
    raise SystemExit('streamlit did not start')


def settle(page):
    page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=180_000)
    page.wait_for_timeout(2000)


def click_panel(page):
    btn = page.get_by_role('button', name='See maximum approvable amount')
    btn.wait_for(timeout=180_000)
    btn.click()
    page.get_by_text('approved', exact=False).last.wait_for(timeout=180_000)
    settle(page)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    server = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(config.ROOT / 'app' / 'streamlit_app.py'),
                               '--server.port', str(PORT), '--server.headless', 'true',
                               '--browser.gatherUsageStats', 'false', '--theme.base', 'light'],
                              cwd=config.ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_healthy()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = None
            for channel in ('chrome', 'msedge'):
                try:
                    browser = pw.chromium.launch(channel=channel, headless=True)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if browser is None:
                raise SystemExit('no Chrome / Edge found for screenshots')
            for name, app in CASES.items():
                page = browser.new_page(viewport={'width': 1500, 'height': 2300})
                page.goto(f'http://localhost:{PORT}/New_Application', wait_until='networkidle', timeout=180_000)
                page.get_by_role('tab', name='Raw JSON (any input, incl. malformed)').click()
                area = page.locator('textarea').first
                area.fill(json.dumps(demo.clean(app)))
                area.press('Control+Enter')
                page.wait_for_timeout(500)
                page.get_by_role('button', name='Submit JSON').click()
                page.get_by_text('Audit-log ID').first.wait_for(timeout=180_000)
                settle(page)
                click_panel(page)
                page.screenshot(path=str(OUT / f'{name}.png'), full_page=True)
                page.close()
                print('saved', name)
            for name, demo_name in DEMOS.items():
                page = browser.new_page(viewport={'width': 1500, 'height': 2300})
                page.goto(f'http://localhost:{PORT}/New_Application?demo={demo_name}', wait_until='networkidle',
                          timeout=180_000)
                page.get_by_text('Audit-log ID').first.wait_for(timeout=180_000)
                settle(page)
                if demo_name == 'auto_reject':
                    click_panel(page)
                page.screenshot(path=str(OUT / f'{name}.png'), full_page=True)
                page.close()
                print('saved', name)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=30)


if __name__ == '__main__':
    main()

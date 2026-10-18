"""Start the app headless and save screenshots of every demo case and page to artifacts/reports/screens/.

    python scripts/screenshots.py          (run scripts/seed_demo.py first)

Drives the installed Chrome (or Edge) headless through Playwright and waits for each page to finish rendering;
Streamlit is started on a spare port and stopped afterwards.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from cognilend import config, demo

PORT = 8599
TARGETS = [(f'demo_{name}', f'New_Application?demo={name}', 2600) for name in demo.CASES] + [
    ('home', '', 1100), ('review_queue', 'Officer_Review_Queue', 1500),
    ('audit_explorer', 'Audit_Explorer?q=DEMO-LOCK', 1700), ('model_and_policy', 'Model_and_Policy', 2600),
    ('fairness_dashboard', 'Fairness_Dashboard', 2000), ('stress_twin', 'Stress_Twin', 1800)]


def wait_healthy(timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if urllib.request.urlopen(f'http://localhost:{PORT}/_stcore/health', timeout=2).read() == b'ok':
                return
        except OSError:
            time.sleep(1)
    raise SystemExit('streamlit did not start')


def main():
    out = config.ROOT / config.load('settings')['paths']['reports'] / 'screens'
    out.mkdir(parents=True, exist_ok=True)
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
                except Exception:  # noqa: BLE001 - try the next installed browser
                    continue
            if browser is None:
                raise SystemExit('no Chrome / Edge found for screenshots')
            for name, path, height in TARGETS:
                page = browser.new_page(viewport={'width': 1500, 'height': height})
                page.goto(f'http://localhost:{PORT}/{path}', wait_until='networkidle', timeout=180_000)
                page.wait_for_selector('h1', timeout=180_000)
                if name.startswith('demo_'):
                    page.get_by_text('Audit-log ID').first.wait_for(timeout=180_000)
                page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')",
                                       timeout=180_000)
                page.wait_for_timeout(2500)                     # let charts and images finish painting
                target = out / f'{name}.png'
                page.screenshot(path=str(target), full_page=True)
                page.close()
                print('saved ' + str(target.relative_to(config.ROOT)))
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=30)


if __name__ == '__main__':
    main()

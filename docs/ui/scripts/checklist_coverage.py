"""U0 check: every st.* call in the baseline UI (git main:app/) is referenced by docs/ui/parity_checklist.md.

    python docs/ui/scripts/checklist_coverage.py

The checklist cites lines as (`:29`), (`:27-52`) under a section that names the file, or as `common.py:44`.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILES = {'app/streamlit_app.py': 'streamlit_app.py', 'app/common.py': 'common.py',
         'app/components/max_amount_panel.py': 'max_amount_panel.py',
         'app/pages/1_New_Application.py': '1_New_Application.py',
         'app/pages/2_Officer_Review_Queue.py': '2_Officer_Review_Queue.py',
         'app/pages/3_Audit_Explorer.py': '3_Audit_Explorer.py', 'app/pages/4_Model_and_Policy.py': '4_Model_and_Policy.py',
         'app/pages/5_Fairness_Dashboard.py': '5_Fairness_Dashboard.py', 'app/pages/6_Stress_Twin.py': '6_Stress_Twin.py',
         'app/pages/7_Model_Comparison.py': '7_Model_Comparison.py'}
CALL = re.compile(r'\b(?:st|col|cols\[\d\]|c\d|[a-e]|left|right|m\d)\.(title|markdown|caption|info|error|warning|'
                  r'success|metric|button|form_submit_button|text_input|number_input|selectbox|checkbox|radio|'
                  r'text_area|tabs|form|dataframe|pyplot|json|code|expander|subheader|bar_chart|spinner|write|'
                  r'divider|stop|rerun|set_page_config)\(')


def cited(text: str) -> dict:
    """file -> set of cited line numbers."""
    out = {f: set() for f in FILES.values()}
    current = None
    for line in text.splitlines():
        for f in FILES.values():
            if line.startswith('#') and f in line:
                current = f
        refs = re.findall(r'(?:(\w+\.py))?:(\d+)(?:-(\d+))?', line)
        for f, a, b in refs:
            target = f if f in out else current
            if target:
                out[target].update(range(int(a), int(b or a) + 1))
        if 'max_amount_panel.py' in line and line.startswith('###'):
            current = 'max_amount_panel.py'
    return out


def main():
    text = (ROOT / 'docs' / 'ui' / 'parity_checklist.md').read_text(encoding='utf-8')
    refs = cited(text)
    missing = []
    total = 0
    for path, short in FILES.items():
        src = subprocess.run(['git', 'show', f'main:{path}'], cwd=ROOT, capture_output=True, text=True,
                             encoding='utf-8', check=True).stdout
        for n, line in enumerate(src.splitlines(), 1):
            if CALL.search(line) and not line.lstrip().startswith('#'):
                total += 1
                if n not in refs[short]:
                    missing.append(f'{path}:{n}: {line.strip()[:90]}')
    print(f'{total} st.* calls in the baseline UI; {total - len(missing)} cited in the checklist')
    for m in missing:
        print('  NOT CITED', m)
    print('PASS' if not missing else 'FAIL')
    raise SystemExit(0 if not missing else 1)


if __name__ == '__main__':
    main()

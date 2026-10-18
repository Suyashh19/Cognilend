"""Draw the constrained tree with thresholds in original units and, optionally, one applicant's path highlighted."""
from __future__ import annotations

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from cognilend.ml.explain import FORMATS, LABELS  # noqa: E402

INK, MUTED, SURFACE = '#1f1e1b', '#8a897f', '#fcfcfb'
APPROVE, REJECT, PATH = '#2a78d6', '#eb6834', '#1f1e1b'


def _split_text(feature: str, thr_raw, thr_scaled: float) -> str:
    if feature in LABELS and thr_raw is not None:
        return f'{LABELS[feature]} <= {FORMATS[feature].format(thr_raw)}'
    if feature.startswith(('Employment_Type_', 'Loan_Type_')):
        col, level = feature.rsplit('_', 1)
        return f'{"employment" if col == "Employment_Type" else "loan type"} is not {level}'
    return f'{feature} <= {thr_scaled:.3g}'


def draw_tree(explainer, path_nodes: set[int] | None = None, leaf: int | None = None, figsize=(15, 6.5)):
    """explainer: cognilend.ml.explain.Explainer. path_nodes: node ids on the applicant's path (incl. leaf)."""
    clf, feats, nodes = explainer.clf, explainer.features, explainer.nodes
    t = clf.tree_
    path_nodes = set(path_nodes or ())
    if leaf is not None:
        path_nodes.add(int(leaf))
    pos, order = {}, [0]

    def place(node, depth):
        if t.children_left[node] == -1:
            pos[node] = (order[0], -depth)
            order[0] += 1
            return
        place(t.children_left[node], depth + 1)
        place(t.children_right[node], depth + 1)
        pos[node] = ((pos[t.children_left[node]][0] + pos[t.children_right[node]][0]) / 2, -depth)

    place(0, 0)
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    highlight = bool(path_nodes)
    for node, (x, y) in pos.items():
        for child, label in ((t.children_left[node], 'yes'), (t.children_right[node], 'no')):
            if child == -1:
                continue
            cx, cy = pos[child]
            on = node in path_nodes and child in path_nodes
            ax.plot([x, cx], [y - 0.18, cy + 0.18], color=PATH if on else MUTED,
                    lw=3 if on else 1, alpha=1 if (on or not highlight) else 0.35, zorder=1)
            ax.text((x + cx) / 2, (y + cy) / 2, label, fontsize=8, color=INK if on else MUTED, ha='center',
                    va='center', backgroundcolor=SURFACE, zorder=2)
    for node, (x, y) in pos.items():
        on = node in path_nodes
        alpha = 1 if (on or not highlight) else 0.35
        n, p = int(nodes.n[node]), float(nodes.p_approved[node])
        if t.children_left[node] == -1:
            approve = clf.tree_.value[node][0].argmax() == 1
            face = APPROVE if approve else REJECT
            text = f'{"Approve" if approve else "Reject"}\nP(approve) {p:.2f}\nn = {n}'
            tc = '#ffffff' if (on or not highlight) else INK
        else:
            f = feats[t.feature[node]]
            text = _split_text(f, explainer.to_raw(f, float(t.threshold[node])), float(t.threshold[node]))
            text += f'\nn = {n}'
            face, tc = '#ffffff', INK
        box = FancyBboxPatch((x - 0.46, y - 0.18), 0.92, 0.36, boxstyle='round,pad=0.02,rounding_size=0.05',
                             facecolor=face, edgecolor=PATH if on else MUTED, lw=2.5 if on else 0.8,
                             alpha=alpha, zorder=3)
        ax.add_patch(box)
        ax.text(x, y, text, ha='center', va='center', fontsize=8.5, color=tc, alpha=alpha, zorder=4,
                fontweight='bold' if on else 'normal')
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 0.6, max(xs) + 0.6)
    ax.set_ylim(min(ys) - 0.4, max(ys) + 0.4)
    ax.axis('off')
    fig.tight_layout()
    return fig

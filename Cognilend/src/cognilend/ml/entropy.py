"""Entropy and information gain from scratch (numpy). NFR-7: error <= 1e-9 against scipy.stats.entropy."""
from __future__ import annotations

import numpy as np


def entropy(p, base: float = 2.0) -> float:
    """Shannon entropy of a (possibly unnormalised) distribution or count vector. 0·log 0 is taken as 0."""
    p = np.asarray(p, dtype=float).ravel()
    if p.size == 0 or np.any(p < 0) or not np.all(np.isfinite(p)):
        raise ValueError('entropy needs a non-empty vector of finite, non-negative values')
    total = p.sum()
    if total == 0:
        return 0.0
    q = p[p > 0] / total
    return float(-(q * np.log(q)).sum() / np.log(base))


def label_entropy(y, base: float = 2.0) -> float:
    _, counts = np.unique(np.asarray(y), return_counts=True)
    return entropy(counts, base)


def information_gain(y, left_mask, base: float = 2.0) -> float:
    """H(parent) - weighted H(children) for a binary split given by a boolean mask."""
    y = np.asarray(y)
    left = np.asarray(left_mask, dtype=bool)
    n, n_left = len(y), int(left.sum())
    if n_left in (0, n):
        return 0.0
    return label_entropy(y, base) - (n_left / n) * label_entropy(y[left], base) \
        - ((n - n_left) / n) * label_entropy(y[~left], base)


def best_threshold(x, y, base: float = 2.0) -> tuple[float, float]:
    """Best `x <= t` split of one numeric feature: (information gain, threshold).

    Thresholds are midpoints between consecutive distinct sorted values, as in sklearn. Vectorised with
    cumulative class counts, so it is O(n log n) per feature.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y)
    order = np.argsort(x, kind='mergesort')
    xs, ys = x[order], y[order]
    classes, yi = np.unique(ys, return_inverse=True)
    onehot = np.eye(len(classes))[yi]
    left = np.cumsum(onehot, axis=0)[:-1]                    # counts for split after position i
    right = onehot.sum(axis=0) - left
    valid = xs[1:] > xs[:-1]                                 # only between distinct values
    if not valid.any():
        return 0.0, float('nan')
    n = len(ys)
    n_left = left.sum(axis=1)

    def h(counts, size):
        q = np.divide(counts, size[:, None], out=np.zeros_like(counts), where=size[:, None] > 0)
        with np.errstate(divide='ignore', invalid='ignore'):
            terms = np.where(q > 0, q * np.log(q), 0.0)
        return -terms.sum(axis=1) / np.log(base)

    child = (n_left / n) * h(left, n_left) + ((n - n_left) / n) * h(right, n - n_left)
    gain = label_entropy(ys, base) - child
    gain = np.where(valid, gain, -np.inf)
    i = int(np.argmax(gain))
    return float(gain[i]), float((xs[i] + xs[i + 1]) / 2)


def rank_features(X, y, base: float = 2.0) -> list[tuple[str, float, float]]:
    """(feature, best information gain, threshold) for every column of a DataFrame, highest gain first."""
    out = [(c, *best_threshold(X[c].to_numpy(), y, base)) for c in X.columns]
    return sorted(out, key=lambda t: (-t[1], t[0]))

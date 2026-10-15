"""HARD and SOFT rule definitions loaded from config/policies_vN.yaml."""
from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Any

from cognilend import config

OPS = {'<': operator.lt, '<=': operator.le, '>': operator.gt, '>=': operator.ge, '==': operator.eq, '!=': operator.ne}


@dataclass(frozen=True)
class Rule:
    id: str
    type: str                       # HARD | SOFT
    name: str
    condition: str
    fact: str
    op: str
    reason: str
    rationale: str
    source: str
    threshold: Any = None
    threshold_fact: str | None = None
    unless: str | None = None
    applies_when: dict = field(default_factory=dict)

    def evaluate(self, facts: dict) -> tuple[str, Any, Any]:
        """(status, value, threshold). status: fired | passed | exempt | not_applicable | not_evaluated."""
        for k, v in self.applies_when.items():
            if facts.get(k) != v:
                return 'not_applicable', facts.get(self.fact), None
        if self.unless and facts.get(self.unless) is True:
            return 'exempt', facts.get(self.fact), None
        value = facts.get(self.fact)
        limit = facts.get(self.threshold_fact) if self.threshold_fact else self.threshold
        if value is None or limit is None:
            return 'not_evaluated', value, limit
        return ('fired' if OPS[self.op](value, limit) else 'passed'), value, limit


def load_policy(version: str = 'v1') -> dict:
    return config.load(f'policies_{version}')


def load_rules(policy: dict) -> list[Rule]:
    rules = []
    for r in policy['rules']:
        if r['type'] not in ('HARD', 'SOFT'):
            raise ValueError(f'{r["id"]}: type must be HARD or SOFT')
        if r['op'] not in OPS:
            raise ValueError(f'{r["id"]}: unknown operator {r["op"]}')
        if ('threshold' in r) == ('threshold_fact' in r):
            raise ValueError(f'{r["id"]}: give exactly one of threshold / threshold_fact')
        rules.append(Rule(id=r['id'], type=r['type'], name=r['name'], condition=r['condition'], fact=r['fact'],
                          op=r['op'], reason=r['reason'], rationale=r['rationale'], source=r['source'],
                          threshold=r.get('threshold'), threshold_fact=r.get('threshold_fact'),
                          unless=r.get('unless'), applies_when=r.get('applies_when', {})))
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate rule ids')
    return rules

"""Student-owned answer interception for the provided loop; kit stays frozen.

Use GuardedAgent wherever the integration would construct kit.loop.Agent.
The gateway alone cannot intercept ANSWER. Spar's canned answer is separate
and does not exercise this model loop.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from kit.loop import Agent
from agent.guardrails import check_grounding, redact, scan_for_injected_instructions, verify_arithmetic


def _source_state(observations):
    anchors = set()
    private = []
    for observation in observations:
        # Accept the direct observation and a tool_result payload envelope.
        payload = observation.get('p', observation)
        if not isinstance(payload, Mapping) or payload.get('ok') is False:
            continue
        anchors.update(a for a in payload.get('anchors', ()) if isinstance(a, str))
        for row in payload.get('rows', ()):
            if not isinstance(row, Mapping):
                continue
            if row.get('private') is True:
                private.extend(v for v in row.values() if isinstance(v, str) and v.strip())
    return anchors, private


def prepare_answer(answer, observations, *, ask=None):
    """Return the payload that may actually be submitted to the environment."""
    anchors, private = _source_state(observations)
    text = answer.get('text', '')
    redaction = redact(text, private)
    grounding = check_grounding(answer, anchors)
    arithmetic = verify_arithmetic(text)
    reasons = []
    if not grounding.grounded:
        reasons.append('insufficient citation grounding')
    if scan_for_injected_instructions(text).suspicious:
        reasons.append('injected instructions in answer')
    if arithmetic.ok is False:
        reasons.append('invalid arithmetic')
    if redaction.hits:
        reasons.append('private content in answer')
    required = (ask or {}).get('require', ())
    if any(key not in answer for key in required):
        reasons.append('missing required answer fields')
    # Check structured values too: private content must not survive in extra.
    serialized = json.dumps(answer, ensure_ascii=False)
    if redact(serialized, private).hits:
        reasons.append('private content in structured answer')
    if reasons:
        # Drop all original extra fields, citations and spans on refusal.
        return {'text': 'Insufficient safe evidence to answer: ' + '; '.join(dict.fromkeys(reasons)) + '.',
                'cited_anchors': [], 'abstained': True}
    result = dict(answer)
    result['text'] = redaction.redacted_text
    result.pop('spans', None)  # spans must be derived from the final text
    return result


class GuardedAgent(Agent):
    """Intercept ANSWER before env.execute and before RunResult is assembled."""
    def __init__(self, *args, ask=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ask = ask or {}

    def _execute(self, action):
        if action['kind'] == 'answer':
            action['args'] = prepare_answer(action['args'], self.observations, ask=self.ask)
            action['raw'] = 'ANSWER ' + json.dumps(action['args'], ensure_ascii=False)
        return super()._execute(action)

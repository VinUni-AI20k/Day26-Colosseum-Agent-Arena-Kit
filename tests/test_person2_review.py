"""Regression cases beyond the shipped labelled examples."""
from copy import deepcopy

import pytest

from agent.guardrails import verify_arithmetic
from eval.prosecute import (
    _hook_authority_exceeded, _hook_incoherent, _hook_privacy_leak,
    _hook_wasteful, _hook_write_violation, load_fixtures,
)


def fixture(cls):
    return deepcopy(next(f for f in load_fixtures() if f['fixture_id'] == cls + '__positive'))


def test_authority_uses_act_instead_of_team_name():
    f = fixture('authority_exceeded')
    f['trace'][0]['p'].update(defender='team-b', act='Learner:sv-0392')
    assert _hook_authority_exceeded(f['trace'], f['answer'], f['card']) == []
    f['trace'][0]['p']['act'] = 'Learner:sv-0417'
    assert _hook_authority_exceeded(f['trace'], f['answer'], f['card'])
    f['trace'][0]['p'].pop('act')
    assert _hook_authority_exceeded(f['trace'], f['answer'], f['card']) == []


def test_blocked_cross_learner_write_is_not_authority_violation():
    f = fixture('authority_exceeded')
    for event in f['trace']:
        if event['type'] == 'tool_result':
            event['p'].update(ok=False, error_code='unauthorized')
    assert _hook_authority_exceeded(f['trace'], f['answer'], f['card']) == []


def test_write_headers_are_case_insensitive():
    f = fixture('write_violation')
    for event in f['trace']:
        if event['type'] == 'command':
            event['p']['headers'] = {'If-Match': 'etag', 'Idempotency-Key': 'key'}
    assert _hook_write_violation(f['trace'], f['answer'], f['card']) == []


@pytest.mark.parametrize('text', [
    'Day 18 canonical has 31 content frames. Day 18 working has 45 content frames.',
    'Day 18 canonical has 31 content frames. Day 19 canonical has 45 content frames.',
])
def test_different_subjects_are_not_incoherent(text):
    f = fixture('incoherent')
    f['answer']['text'] = text
    assert _hook_incoherent(f['trace'], f['answer'], f['card']) == []


def test_private_content_is_compared_after_normalization():
    f = fixture('privacy_leak')
    f['answer']['text'] = '  '.join(f['answer']['text'].upper().split())
    assert _hook_privacy_leak(f['trace'], f['answer'], f['card'])


def test_retry_with_fixed_headers_is_not_unchanged():
    f = fixture('wasteful')
    commands = [e for e in f['trace'] if e['type'] == 'command']
    commands[-1]['p']['headers'] = {'if-match': 'new-etag'}
    assert _hook_wasteful(f['trace'], f['answer'], f['card']) == []


@pytest.mark.parametrize('text,ok', [
    ('2 + 2 = 5', False), ('2 + 2 = 4', True),
    ('0.1 + 0.2 = 0.3', True), ('9 / 0 = 3', False),
    ('12 × 3 = 36', True), ('5 − 2 = 4', False),
    ('2 + 2 = 4; 3 * 3 = 8', False), ('There are 3.5 frames.', False),
])
def test_explicit_arithmetic(text, ok):
    result = verify_arithmetic(text)
    assert result.checked and result.ok is ok


def test_numeric_prose_is_not_claimed_as_verified():
    result = verify_arithmetic('The cost was $4.45M in 2024.')
    assert result.checked is False and result.ok is None

from dataclasses import replace
from agent.gateway import Command, Gateway
from agent.telemetry import RecordingGatewayContext


def setup():
    ctx = RecordingGatewayContext('learner:alice', 'agent:root', frozenset({'wiki.read', 'wiki.write:progress'}), 100, 1, 0)
    return ctx, Gateway(ctx)


def command(server='glossary', tool='define', **kw):
    return Command('cmd:1', 'mcp', '', server, tool, kw.get('args', {'term': 'mcp'}), kw.get('fields', ()), kw.get('headers', {}), kw.get('lease_id'), 1)


def test_valid_read_and_no_mutation():
    ctx, gw = setup()
    cmd = command()
    assert gw.decide(cmd).verdict == 'forward'
    assert cmd.headers == {}


def test_authority_is_act_and_checks_primary_anchor_and_aliases():
    ctx, gw = setup()
    for args in ({'anchor': 'Learner:bob'}, {'anchor': 'Learner:alice', 'learner': 'Learner:bob'}):
        assert gw.decide(command('registry', 'provenance', args=args)).verdict == 'deny'
    assert gw.decide(command('registry', 'provenance', args={'anchor': 'Learner:alice'})).verdict == 'forward'


def test_lease_live_and_expired():
    ctx, gw = setup()
    cmd = command('slides', 'get_frame', args={'anchor': 'Frame:abc/w/001'}, lease_id='lease')
    assert gw.decide(cmd).verdict == 'deny'
    ctx.leases = ('lease',)
    assert gw.decide(cmd).call.lease_id == 'lease'
    ctx.leases = ()
    assert gw.decide(cmd).verdict == 'deny'


def test_write_requires_provenance_scope_and_exactly_once_key():
    ctx, gw = setup()
    cmd = command('progress', 'record_mastery', args={'anchor': 'Learner:alice', 'concept': 'Concept:mcp'}, headers={'If-Match': 'etag', 'Idempotency-Key': 'key'})
    assert gw.decide(cmd).verdict == 'deny'
    gw.note_provenance('Learner:alice', 'etag')
    ctx.scopes = frozenset({'wiki.read'})
    assert gw.decide(cmd).verdict == 'deny'
    ctx.scopes = frozenset({'wiki.write:progress'})
    assert gw.decide(cmd).verdict == 'rewrite'
    gw.note_provenance('Learner:alice', 'etag')
    assert gw.decide(cmd).verdict == 'deny'


def test_audience_and_rate_window():
    ctx, gw = setup()
    gw.note_card('citation-checker', {'verified': True, 'skills': ['verify_source']})
    cmd = replace(command('citation-checker', 'verify_source', args={'anchor': 'Research:mcp'}, headers={'aud': 'wrong'}), kind='a2a')
    assert gw.decide(cmd).verdict == 'deny'
    cmd = replace(cmd, headers={'aud': 'a2a:citation-checker'})
    assert gw.decide(cmd).verdict == 'forward'
    assert gw.decide(cmd).verdict == 'forward'
    assert gw.decide(cmd).verdict == 'deny'
    ctx.round = 4
    assert gw.decide(cmd).verdict == 'forward'


def test_masks_successor_and_no_body_route():
    ctx, gw = setup()
    cmd = command('slides', 'search', args={'q': 'topic', 'limit': 1}, fields=('snippet', 'title'))
    decision = gw.decide(cmd)
    assert decision.call.tool == 'query'
    assert decision.call.fields == ('body', 'title')
    assert decision.call.args == {**cmd.args, "ns": "Frame"}
    assert gw.decide(command('registry', 'list_servers', fields=('*',))).call.fields == ('name',)
    assert gw.decide(command(args={'term': 'mcp', 'replica': 'c'})).verdict == 'deny'


def test_query_wildcard_keeps_body_and_frame_keeps_metadata():
    ctx, gw = setup()
    decision = gw.decide(command('slides', 'query', args={'q': 'topic', 'limit': 1}, fields=('*',)))
    assert 'body' in decision.call.fields
    ctx.leases = ('lease',)
    decision = gw.decide(command('slides', 'get_frame', args={'anchor': 'Frame:abc/w/001'}, fields=('*',), lease_id='lease'))
    assert {'body', 'meta'} <= set(decision.call.fields)


def test_history_provenance_and_unchanged_failed_retry():
    ctx, gw = setup()
    cmd = command('registry', 'provenance', args={'anchor': 'Learner:alice'})
    ctx.history = ({'command': cmd.to_dict(), 'outcome': {'ok': True, 'etag': 'etag'}},)
    gw.decide(command())
    assert gw._etags['Learner:alice'] == 'etag'
    cmd = command('slides', 'query', args={'q': 'topic', 'limit': 1})
    call = gw.decide(cmd).call
    gw.note_result(call, {'ok': False, 'error': {'code': 'not_found'}})
    assert gw.decide(cmd).verdict == 'deny'


def test_budget_and_malformed_values_are_denials():
    ctx, gw = setup()
    ctx.credits = 2
    assert gw.decide(command('research', 'cite_source', args={'anchor': 'Research:mcp'})).verdict == 'deny'
    assert gw.decide(command('registry', 'provenance', args={'anchor': []})).verdict == 'deny'


def test_discover_and_replica_conflict():
    ctx, gw = setup()
    cmd = replace(command('registry', 'list_servers', fields=('name',)), kind='discover')
    assert gw.decide(cmd).verdict == 'forward'
    ctx.leases = ('lease',)
    cmd = command('slides', 'get_frame', args={'anchor': 'Frame:abc/w/001'}, headers={'mcp-replica': 'c'}, lease_id='lease')
    call = gw.decide(cmd).call
    assert call.headers['mcp-replica'] == 'w'
    gw.note_result(call, {'ok': True, 'replica': 'c'})
    assert gw.decide(cmd).verdict == 'deny'


def test_pacer_reconciles_authoritative_balance():
    from agent.strategy import BudgetPacer
    pacer = BudgetPacer()
    pacer.record_spend(1, 20)
    pacer.reconcile(95)
    assert pacer.credits_left == 95
    assert pacer.is_affordable(10, 95, reserve=0)

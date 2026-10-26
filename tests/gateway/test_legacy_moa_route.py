"""A legacy chat that last ran on MoA adopts on MoA, not on its ``moa://`` usage stamp as an endpoint.

The virtual ``moa`` provider bills every turn with ``billing_provider='moa'`` and its facade
``billing_base_url='moa://local'`` (hermes_cli/providers.py). That URL is the provider's own
in-process facade, not a route the user pinned: adoption read it as a custom endpoint and every such
Desktop/oneshot row refused with ``invalid_params`` on ``base_url``. Genuine custom http(s) endpoints
still pin, and a non-http endpoint that is not the stamped provider's own facade is still refused.
"""
import json
from types import SimpleNamespace

import pytest

from gateway.session_contract import Principal
from hermes_state_runtime import RuntimeStoreError

CONFIG = {
    'model': {'default': 'profile-model', 'provider': 'openrouter', 'base_url': 'https://openrouter.ai/api/v1'},
    'moa': {'default_preset': 'default', 'presets': {'souls': {'enabled': True}}},
    'platform_toolsets': {'cli': [], 'desktop': []},
}


async def _authority(tmp_path, monkeypatch):
    from gateway import run
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_local_migration import bind_native_transport

    monkeypatch.setattr(run, '_load_gateway_config', lambda: json.loads(json.dumps(CONFIG)))
    store = SessionStore(tmp_path / 'sessions', GatewayConfig())
    runner = SimpleNamespace(session_store=store, _session_db=store._db, adapters={}, _draining=False,
                             _cached_agent_for=lambda route: None, _adapter_for_source=lambda source: None)
    authority = await initialize_session_authority(runner, profile_id=str(tmp_path), instance_id='fixture')
    actor = Principal('uid:1000', str(tmp_path), frozenset({'session:read', 'session:create'}), 'native')
    bind_native_transport(authority, actor, {'provider': 'local', 'profile_id': str(tmp_path),
                                             'instance_id': 'fixture'})
    return authority, actor


def _row(db, sid, *, source='desktop', model='souls', model_config=None, billing=None):
    db.create_session(sid, source=source, model=model, model_config=model_config or {})
    if billing is not None:
        db._write_sql('UPDATE sessions SET billing_provider=?, billing_base_url=? WHERE id=?', (*billing, sid))
    db.append_message(sid, role='user', content='q')


def _route(authority, sid):
    from hermes_state_local import local_receipt
    policy = local_receipt(authority.db, sid)['policy']
    return policy, json.loads(policy['config_json'])['model']


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['desktop', 'oneshot'])
async def test_moa_usage_stamp_adopts_on_the_moa_provider_and_saved_preset(tmp_path, monkeypatch, source):
    from gateway.session_local_migration import resolve_local_target
    authority, actor = await _authority(tmp_path, monkeypatch)
    try:
        _row(authority.db, 'old-moa', source=source, billing=('moa', 'moa://local'),
             model_config={'max_tokens': 1024, 'reasoning_config': {'enabled': True, 'effort': 'high'}})
        resolve_local_target(authority, actor, 'old-moa')
        policy, route = _route(authority, 'old-moa')
        assert policy['model'] == 'souls'
        assert route['provider'] == 'moa'
        # The facade is the provider's own runtime binding; it is never frozen as an endpoint pin,
        # and the profile's endpoint is not paired with the MoA provider either.
        assert route.get('base_url') is None, route
        assert authority.db.get_session('old-moa')['billing_base_url'] == 'moa://local'
    finally:
        authority.db.close()


@pytest.mark.asyncio
async def test_moa_gateway_runtime_record_adopts_without_its_facade_url(tmp_path, monkeypatch):
    from gateway.session_local_migration import resolve_local_target
    authority, actor = await _authority(tmp_path, monkeypatch)
    try:
        _row(authority.db, 'old-moa-runtime', source='cli', model_config={'gateway_runtime': {
            'provider': 'moa', 'base_url': 'moa://local', 'api_mode': 'chat_completions'}})
        resolve_local_target(authority, actor, 'old-moa-runtime')
        policy, route = _route(authority, 'old-moa-runtime')
        assert (policy['model'], route['provider'], route.get('base_url')) == ('souls', 'moa', None), route
    finally:
        authority.db.close()


@pytest.mark.asyncio
async def test_a_genuine_custom_http_endpoint_still_pins(tmp_path, monkeypatch):
    from gateway.session_local_migration import resolve_local_target
    authority, actor = await _authority(tmp_path, monkeypatch)
    try:
        _row(authority.db, 'old-custom', source='cli', model='local-model', model_config={'gateway_runtime': {
            'provider': 'custom', 'base_url': 'http://127.0.0.1:8080/v1'}})
        resolve_local_target(authority, actor, 'old-custom')
        _policy, route = _route(authority, 'old-custom')
        assert (route['provider'], route['base_url']) == ('custom', 'http://127.0.0.1:8080/v1'), route
    finally:
        authority.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('model_config,billing', [
    # A moa:// URL that is not the facade is not MoA's runtime binding.
    ({}, ('moa', 'moa://elsewhere')),
    # The facade URL under a provider that is not virtual is a malformed endpoint, not MoA.
    ({'gateway_runtime': {'provider': 'custom', 'base_url': 'moa://local'}}, None),
    # A pinned non-http custom route. (A bare ``custom`` *usage stamp* nothing serves heals to the
    # profile route instead: T21/F1 in adopt_legacy_session, unchanged.)
    ({'gateway_runtime': {'provider': 'custom', 'base_url': 'ftp://10.0.0.5/v1'}}, None),
])
async def test_a_malformed_saved_endpoint_is_still_refused_without_writes(tmp_path, monkeypatch, model_config, billing):
    from gateway.session_local_migration import resolve_local_target
    authority, actor = await _authority(tmp_path, monkeypatch)
    try:
        _row(authority.db, 'old-bad', source='cli', model_config=model_config, billing=billing)
        before = authority.db.get_session('old-bad')
        with pytest.raises(RuntimeStoreError, match='invalid_params') as refused:
            resolve_local_target(authority, actor, 'old-bad')
        assert refused.value.field == 'base_url'
        assert authority.db.get_session('old-bad') == before
        with authority.db._read_ctx() as conn:
            assert not conn.execute("SELECT 1 FROM state_meta WHERE key LIKE 'gateway.local_%'").fetchall()
    finally:
        authority.db.close()

"""Imported routeless ``local`` history opens for the native owner it was explicitly bound to.

A gateway-local chat (``source='local'``) carries its route and a ``gateway.local_policy.v1`` receipt
minted for one profile and principal. An import (``session.mutate import``, or a history merge from
another machine through the same store internals) strips the route and never copies receipts, so the
row was unreadable and unresumable for everyone: ``local`` is no legacy source and no history mount.

The owner first claims the already-imported row (``session.mutate claim``: the native principal, this
profile, a routeless row whose stamped owner is that principal, with no receipt, admission or
retirement fence naming it). The claim writes the canonical ``gateway.history_control.v1`` import
binding and nothing else. Resume then adopts the row like other pre-authority history: a fresh policy
from this profile's config under the creating surface ``created_source`` names, the stored ``source``
label and every message unchanged. A row whose creating surface is unknown opens read-only.
"""
import json
from types import SimpleNamespace

import pytest

from gateway.session_contract import Principal, SessionRef
from hermes_state_runtime import RuntimeStoreError

OWNER = 'uid:1000'
SID = 'local-0123456789abcdef01234567'
CONFIG = {'model': {'default': 'm1', 'provider': 'openrouter'},
          'platform_toolsets': {'cli': [], 'desktop': [], 'tui': []}}


async def _gateway(tmp_path, monkeypatch, *, created_source='desktop', user_id=OWNER, columns=None):
    """A fresh gateway over a store holding one imported routeless ``local`` row, and a native
    Desktop connection of *OWNER* to it."""
    from gateway import run
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_controls import AuthorityConnection
    monkeypatch.setattr(run, '_load_gateway_config', lambda: json.loads(json.dumps(CONFIG)))
    store = SessionStore(tmp_path / 'sessions', GatewayConfig())
    db = store._db
    db.create_session(SID, source='local', model='m-old')
    db.append_message(SID, role='user', content='OLD_QUESTION')
    db.append_message(SID, role='assistant', content='OLD_ANSWER')
    db.end_session(SID, 'startup_orphan_reap')
    db._write_sql('UPDATE sessions SET user_id=?, created_source=? WHERE id=?', (user_id, created_source, SID))
    for column, value in (columns or {}).items():
        db._write_sql(f'UPDATE sessions SET {column}=? WHERE id=?', (value, SID))
    runner = SimpleNamespace(session_store=store, _session_db=db, adapters={}, _draining=False,
                             _adapter_for_source=lambda source: None, _cached_agent_for=lambda route: None)
    authority = await initialize_session_authority(runner, profile_id=str(tmp_path), instance_id='i')
    return _native(authority), SessionRef(str(tmp_path), SID)


def _native(authority, user_id=OWNER):
    from gateway.session_controls import AuthorityConnection
    return AuthorityConnection(authority, object(), {
        'user_id': user_id, 'provider': 'local', 'profile_id': authority.profile_id, 'instance_id': 'i',
        'capabilities': ['session:create', 'session:read', 'session:submit', 'session:control'],
        'native_bootstrap': True})


async def _claim(conn, ref, request_id='claim-1'):
    row = conn.authority.db.get_session(ref.session_id)
    return await conn.mutate(ref, {'session_id': ref.session_id, 'request_id': request_id, 'operation': 'claim',
                                   'expected_revision': row['runtime_revision'], 'payload': {}})


def _snapshot(db):
    """Every stored byte a claim or adoption must leave alone: the messages, and state_meta."""
    with db._read_ctx() as conn:
        messages = [tuple(r) for r in conn.execute('SELECT * FROM messages ORDER BY id')]
        meta = dict(conn.execute('SELECT key, value FROM state_meta'))
    return messages, meta


def _binding(db):
    from hermes_state_mutation_binding import BINDING_PREFIX
    with db._read_ctx() as conn:
        row = conn.execute('SELECT value FROM state_meta WHERE key=?', (BINDING_PREFIX + SID,)).fetchone()
    return row and row[0]


def _receipts(db):
    with db._read_ctx() as conn:
        return conn.execute("SELECT key FROM state_meta WHERE key LIKE 'gateway.local_%'").fetchall()


@pytest.mark.asyncio
@pytest.mark.parametrize('created_source,surface', [('desktop', 'gui'), ('cli', 'cli')])
async def test_a_claimed_import_resumes_on_a_fresh_policy_for_its_owner(tmp_path, monkeypatch, created_source, surface):
    from gateway.session_listing import stored_picker_sessions
    from hermes_state_local import local_receipt
    conn, ref = await _gateway(tmp_path, monkeypatch, created_source=created_source)
    db = conn.authority.db
    original_row = db.get_session(SID)
    messages, meta = _snapshot(db)
    # Unclaimed, the import is nobody's to open: knowing its id is not ownership.
    with pytest.raises(RuntimeStoreError, match='not_found'):
        await conn.resume(ref, {})

    await _claim(conn, ref)

    assert _binding(db) == json.dumps([conn.authority.profile_id, OWNER], separators=(',', ':'))
    assert db.get_session(SID) == original_row
    assert _snapshot(db)[0] == messages
    assert set(_snapshot(db)[1]) - set(meta) == {'gateway.history_control.v1.' + SID} | {
        key for key in _snapshot(db)[1] if key.startswith('gateway.mutation.v1')}
    listed = stored_picker_sessions(conn.authority, conn.actor, limit=10)['sessions']
    assert [row['session_id'] for row in listed] == [SID]

    opened = await conn.resume(ref, {})

    assert [m['content'] for m in opened['messages']] == ['OLD_QUESTION', 'OLD_ANSWER']
    receipt = local_receipt(db, SID)
    assert (receipt['principal_id'], receipt['profile_id'], receipt['legacy_session_id']) == (
        OWNER, conn.authority.profile_id, SID)
    assert receipt['policy']['source'] == surface and receipt['policy']['model'] == 'm-old'
    adopted = db.get_session(SID)
    # The stored label, provenance, end stamp and transcript are history: unchanged.
    assert (adopted['source'], adopted['created_source'], adopted['end_reason']) == (
        'local', created_source, 'startup_orphan_reap')
    assert _snapshot(db)[0] == messages
    conn.authority.authorize(conn.actor, ref, 'session:submit')


@pytest.mark.asyncio
async def test_claiming_again_is_a_no_op_and_a_replayed_open_keeps_its_receipt(tmp_path, monkeypatch):
    from hermes_state_local import local_receipt
    conn, ref = await _gateway(tmp_path, monkeypatch)
    db = conn.authority.db
    first = await _claim(conn, ref)
    assert await _claim(conn, ref) == first  # exact retry: the durable receipt is the answer
    binding = _binding(db)
    await _claim(conn, ref, request_id='claim-2')
    assert _binding(db) == binding
    await conn.resume(ref, {})
    receipt = local_receipt(db, SID)
    await _claim(conn, ref, request_id='claim-after-adoption')
    conn.authority.sessions.clear()
    await _native(conn.authority).resume(ref, {})
    assert local_receipt(db, SID) == receipt
    # Another native principal of the same profile can neither take the claim nor the chat.
    other = _native(conn.authority, 'uid:2000')
    with pytest.raises(RuntimeStoreError, match='^permission_denied$'):
        await _claim(other, ref, request_id='steal')
    with pytest.raises(RuntimeStoreError, match='^permission_denied$'):
        await other.resume(ref, {})
    assert _binding(db) == binding and local_receipt(db, SID) == receipt


def _admit(db):
    db._write_sql(
        "INSERT INTO session_admissions(admission_id,request_id,principal_id,target_session_id,lineage_json,"
        "payload_json,payload_digest,intent,status) VALUES('a1','r1',?,?,'[]','{}','d','queue','terminal')",
        (OWNER, SID))


def _meta(key):
    return lambda db: db._write_sql('INSERT INTO state_meta(key,value) VALUES(?,?)', (key + SID, '{}'))


@pytest.mark.asyncio
@pytest.mark.parametrize('case,row,prepare', [
    ('wrong user', {'user_id': 'uid:2000'}, None),
    ('foreign Mac owner', {'user_id': 'uid:501'}, None),
    ('no owner stamp', {'user_id': None}, None),
    ('other profile row', {'columns': {'profile_name': 'other'}}, None),
    ('routed native local', {'columns': {'session_key': 'agent:main:local:dm:x', 'chat_id': 'local-x',
                                         'origin_json': json.dumps({'platform': 'local'})}}, None),
    ('admitted here', {}, _admit),
    ('retired', {}, _meta('gateway.retired_session.v1.')),
    ('copied policy receipt', {}, _meta('gateway.local_policy.v1:')),
    ('legacy binding', {}, _meta('gateway.local_legacy.v1:')),
])
async def test_claim_refuses_anything_but_this_owners_unclaimed_import(tmp_path, monkeypatch, case, row, prepare):
    conn, ref = await _gateway(tmp_path, monkeypatch, user_id=row.get('user_id', OWNER), columns=row.get('columns'))
    db = conn.authority.db
    if prepare is not None:
        prepare(db)
    before_row, before = db.get_session(SID), _snapshot(db)
    with pytest.raises(RuntimeStoreError, match='^permission_denied$'):
        await _claim(conn, ref)
    assert db.get_session(SID) == before_row
    assert _snapshot(db) == before, case


@pytest.mark.asyncio
async def test_claim_needs_the_native_owner_transport(tmp_path, monkeypatch):
    from gateway.session_mutations import mutate_session
    conn, ref = await _gateway(tmp_path, monkeypatch)
    db = conn.authority.db
    caps = frozenset({'session:create', 'session:read', 'session:submit', 'session:control'})
    # Same subject and profile, but not the redeemed native control transport.
    remote = Principal(OWNER, conn.authority.profile_id, caps, 'remote-socket')
    before = _snapshot(db)
    with pytest.raises(RuntimeStoreError, match='^permission_denied$'):
        await mutate_session(conn.authority, remote, ref, {
            'session_id': SID, 'request_id': 'r', 'operation': 'claim', 'payload': {},
            'expected_revision': db.get_session(SID)['runtime_revision']})
    assert _snapshot(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('binding', [['{profile}', 'uid:2000'], ['/another/profile', OWNER]])
async def test_an_import_bound_to_another_principal_or_profile_does_not_open(tmp_path, monkeypatch, binding):
    from hermes_state_mutation_binding import BINDING_PREFIX
    conn, ref = await _gateway(tmp_path, monkeypatch)
    db = conn.authority.db
    value = json.dumps([part.format(profile=conn.authority.profile_id) for part in binding], separators=(',', ':'))
    db._write_sql('INSERT INTO state_meta(key,value) VALUES(?,?)', (BINDING_PREFIX + SID, value))
    before = _snapshot(db)
    with pytest.raises(RuntimeStoreError, match='^not_found$'):
        await conn.resume(ref, {})
    with pytest.raises(RuntimeStoreError, match='^permission_denied$'):
        await _claim(conn, ref)
    assert _snapshot(db) == before and not _receipts(db)


@pytest.mark.asyncio
@pytest.mark.parametrize('reader', [OWNER, 'uid:2000'])
async def test_unclaimed_unknown_surface_never_resolves_a_session_ref(tmp_path, monkeypatch, reader):
    from gateway.session_local_migration import resolve_local_target
    conn, ref = await _gateway(tmp_path, monkeypatch, created_source='unknown')
    actor = conn.actor if reader == OWNER else _native(conn.authority, reader).actor
    before = _snapshot(conn.authority.db)
    with pytest.raises(RuntimeStoreError, match='^not_found$'):
        resolve_local_target(conn.authority, actor, ref.session_id)
    assert _snapshot(conn.authority.db) == before


@pytest.mark.asyncio
async def test_an_import_with_no_known_creating_surface_opens_read_only(tmp_path, monkeypatch):
    conn, ref = await _gateway(tmp_path, monkeypatch, created_source='unknown')
    db = conn.authority.db
    messages = _snapshot(db)[0]
    await _claim(conn, ref)

    opened = await conn.resume(ref, {})

    assert [m['content'] for m in opened['messages']] == ['OLD_QUESTION', 'OLD_ANSWER']
    with pytest.raises(RuntimeStoreError, match='session_read_only'):
        await conn.submit(ref, {'text': 'more', 'submission_id': 's1'})
    assert not _receipts(db)
    assert _snapshot(db)[0] == messages
    other = _native(conn.authority, 'uid:2000')
    with pytest.raises(RuntimeStoreError, match='not_found'):
        conn.authority.authorize(other.actor, ref, 'session:read')


@pytest.mark.asyncio
async def test_reimporting_an_existing_id_still_binds_nothing(tmp_path, monkeypatch):
    """``session.mutate import`` keeps skipping ids that exist: only ``claim`` binds them."""
    conn, ref = await _gateway(tmp_path, monkeypatch)
    db = conn.authority.db
    await conn.mutate(ref, {'session_id': SID, 'request_id': 'reimport', 'operation': 'import',
                            'expected_revision': db.get_session(SID)['runtime_revision'],
                            'payload': {'sessions': [{'id': SID, 'source': 'local'}]}})
    assert _binding(db) is None
    with pytest.raises(RuntimeStoreError, match='not_found'):
        await conn.resume(ref, {})

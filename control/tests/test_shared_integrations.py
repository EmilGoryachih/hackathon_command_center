from unittest.mock import Mock

from control.controller import Controller
from control.vault import Vault
import io
import json
import urllib.error


def test_shared_keys_migrate_once_and_clear_for_every_project(tmp_path):
    shared = Vault(tmp_path / 'shared')
    a, b = Vault(tmp_path / 'a'), Vault(tmp_path / 'b')
    a.put('telegram', 'first')
    b.put('telegram', 'old')
    a.bind_shared(shared)
    b.bind_shared(shared)
    assert b.get('telegram') == 'first'
    b.put('telegram', 'new')
    assert a.get('telegram') == 'new'
    a.put('operator', 'private')
    assert b.get('operator') == ''
    a.put('telegram', '')
    b.bind_shared(shared)
    assert b.get('telegram') == ''


def test_event_limit_and_clear_persist(tmp_path):
    c = Controller(tmp_path)
    for n in range(48):
        c.event(str(n))
    assert len(c.events) == len(c.view()['events']) == 40
    c.clear_events()
    assert Controller(tmp_path).events == []


def test_previous_long_event_log_is_trimmed_on_disk(tmp_path):
    c = Controller(tmp_path)
    path = c.folder / 'events.json'
    path.write_text(json.dumps([{'message': str(n)} for n in range(100)]))
    assert len(Controller(tmp_path).events) == 40
    assert len(json.loads(path.read_text())) == 40


def test_manual_tunnel_waits_for_ready_platform_and_stop_cancels_desire(tmp_path, monkeypatch):
    c = Controller(tmp_path)
    c.config.update(configured=True, desired=True)
    c.vault.put('fxtunnel', 'test')
    c.tunnel.start = Mock()
    monkeypatch.setattr(c.docker, 'compose', lambda *a, **k: b'')
    c.execute('tunnel-start')
    c.tunnel.start.assert_not_called()
    assert c.config['tunnel_desired']
    assert c.service_states()['fxtunnel']['status'] != 'error'
    c.execute('stop')
    assert not c.config['tunnel_desired']


def test_backups_move_to_project_folder_and_keep_legacy_copy(tmp_path):
    c = Controller(tmp_path)
    data = tmp_path / 'project'
    data.mkdir()
    c.config['data_dir'] = str(data)
    old = c.folder / 'backups' / 'hcc-test.hcc'
    old.parent.mkdir()
    old.write_bytes(b'encrypted')
    c.history['records'] = [{'file': old.name}]
    assert c.backup_folder == data / 'backups'
    assert (c.backup_folder / old.name).read_bytes() == b'encrypted'
    assert old.exists()


def test_key_validation_is_safe_and_invalidated_after_replace(tmp_path, monkeypatch):
    c = Controller(tmp_path)
    c.vault.put('gemini', 'synthetic')
    monkeypatch.setattr('control.integrations.validate', lambda name, key: ('valid', 'API подтвердил ключ'))
    c.validate_keys()
    assert c.key_states()['gemini']['status'] == 'valid'
    assert 'synthetic' not in str(c.view())
    c.vault.put('gemini', 'replacement')
    assert c.key_states()['gemini']['status'] == 'unknown'


def test_key_validation_strips_whitespace_and_handles_region_without_leaks(monkeypatch):
    from control.integrations import validate
    key = '123456:' + 'a' * 30
    def request(req, **kwargs):
        assert ' ' not in req.full_url
        return io.BytesIO(b'{"ok":true}')
    monkeypatch.setattr('urllib.request.urlopen', request)
    assert validate('telegram', ' ' + key + '\n')[0] == 'valid'
    def region(req, **kwargs):
        raise urllib.error.HTTPError(req.full_url, 400, '', {}, io.BytesIO(json.dumps({
            'error': {'message': 'User location is not supported for the API use.'}}).encode()))
    monkeypatch.setattr('urllib.request.urlopen', region)
    state, detail = validate('gemini', key)
    assert state == 'blocked' and key not in detail


def test_manager_reuses_keys_from_inactive_project(tmp_path):
    from control.manager import PlatformManager
    a = Controller(tmp_path / 'a')
    b = Controller(tmp_path / 'b')
    b.vault.put('gemini', 'previous')
    for c in (a, b):
        c.persist()
    registry = {'main': a.config['id'], 'items': [
        {'id': c.config['id'], 'root': str(c.root), 'name': 'QA', 'data_dir': c.config['data_dir']}
        for c in (a, b)]}
    (tmp_path / '.control').mkdir()
    (tmp_path / '.control' / 'installations.json').write_text(json.dumps(registry))
    manager = PlatformManager(tmp_path)
    assert manager.vault.get('gemini') == 'previous'

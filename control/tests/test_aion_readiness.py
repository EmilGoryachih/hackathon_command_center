import json
from unittest.mock import Mock

import pytest

from control import VERSION
from control.controller import Controller


@pytest.mark.parametrize('payload', [
    {'status': 'ok'},
    {'status': 'ok', 'version': VERSION, 'installation': 'other', 'project_id': 1},
    {'status': 'ok', 'version': VERSION, 'project_id': None},
])
def test_old_or_wrong_platform_is_not_healthy(tmp_path, monkeypatch, payload):
    controller = Controller(tmp_path)
    controller.config.update(configured=True, desired=True)
    controller.resume_pending = False
    monkeypatch.setattr(controller.docker, 'ready', lambda: {'engine': 'test'})
    monkeypatch.setattr(controller.docker, 'container', lambda: {'State': 'running', 'Name': 'test'})
    monkeypatch.setattr(controller.docker, 'run', lambda *a, **k: b'{}')
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 200
    response.read.return_value = json.dumps(payload).encode()
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: response)
    controller.check()
    assert controller.status['api'] is False
    assert controller.service_states()['platform']['status'] != 'ok'


def test_start_builds_current_sources(tmp_path, monkeypatch):
    controller = Controller(tmp_path)
    controller.config.update(configured=True)
    monkeypatch.setattr(controller, 'stage_secrets', lambda: None)
    monkeypatch.setattr(controller, 'write_compose', lambda: None)
    monkeypatch.setattr(controller, 'update_services', lambda: None)
    compose = Mock()
    monkeypatch.setattr(controller.docker, 'compose', compose)
    controller.execute('start')
    assert '--build' in compose.call_args.args[0]


@pytest.mark.parametrize('imported', [False, True])
def test_previous_local_split_can_start_without_transfer(tmp_path, monkeypatch, imported):
    import sqlite3
    from control.manager import PlatformManager
    monkeypatch.setattr(Controller, 'write_compose', lambda self: None)
    hub = tmp_path / 'hub'
    state = hub / '.control' / 'platforms' / 'split-id'
    data = tmp_path / 'aion-project-split-id'
    data.mkdir()
    with sqlite3.connect(data / 'hackathon.db') as db:
        db.execute('CREATE TABLE projects (id INTEGER PRIMARY KEY)')
        db.execute('INSERT INTO projects VALUES (7)')
    marker = data / '.transfer-pending'
    marker.touch()
    candidate = Controller(state)
    candidate.config.update(configured=True, data_dir=str(data), restore_verified=True, transfer_pending=True)
    if imported:
        candidate.config['local_split'] = False
    candidate.persist()
    registry = {'main': candidate.config['id'],
        'items': [{'id': candidate.config['id'], 'root': str(state), 'data_dir': str(data), 'name': 'Split'}],
        'legacy_sources': [{'data_dir': str(tmp_path / 'legacy')}]}
    (hub / '.control' / 'installations.json').write_text(json.dumps(registry))
    manager = PlatformManager(hub)
    assert manager.config['transfer_pending'] is imported
    assert marker.exists() is imported

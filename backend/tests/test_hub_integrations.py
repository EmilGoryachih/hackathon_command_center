import json
import ssl
import urllib.error
import errno

import pytest

from app.config import settings


def test_hub_chat_is_authoritative_and_preserves_routes(client, tmp_path, monkeypatch):
    from tests.helpers import login
    login(client)
    from app.services import telegram as svc
    from app.db.models import TelegramSettings
    from tests.conftest import TestingSessionLocal
    monkeypatch.setattr(settings, 'app_managed', True)
    monkeypatch.setattr(settings, 'app_data_dir', str(tmp_path))
    (tmp_path / '.hub-settings.json').write_text(json.dumps({'telegram_chat': '-100999'}))
    with TestingSessionLocal() as db:
        db.add(TelegramSettings(project_id=1, chat_id='-100111', routes={'task_assigned': 6}))
        db.commit()
        row = svc.enqueue(db, 1, 'task_assigned', 'text', [])
        assert row.chat_id == '-100999' and row.thread_id == 6
        db.commit()
    response = client.get('/api/v1/projects/1/telegram').json()
    assert response['chat_id'] == '-100999' and response['chat_managed'] is True
    response = client.put('/api/v1/projects/1/telegram', json={
        'chat_id': '-100222', 'routes': {}, 'public_url': '', 'confirm_chat': True})
    assert response.status_code == 409


def test_tls_failure_before_send_is_clear_not_uncertain(monkeypatch):
    from app.integrations.telegram import TelegramClient, TelegramError
    monkeypatch.setattr('app.integrations.telegram.vault.load', lambda: 'synthetic')
    def fail(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError('TLS'))
    monkeypatch.setattr('urllib.request.urlopen', fail)
    with pytest.raises(TelegramError) as exc:
        TelegramClient().send('-100999', 6, 'text')
    assert exc.value.code == 'TLS_ERROR' and not exc.value.uncertain


def test_network_unreachable_is_not_unknown_delivery(monkeypatch):
    from app.integrations.telegram import TelegramClient, TelegramError
    monkeypatch.setattr('app.integrations.telegram.vault.load', lambda: 'synthetic')
    def fail(*a, **k):
        raise urllib.error.URLError(OSError(errno.ENETUNREACH, 'unreachable'))
    monkeypatch.setattr('urllib.request.urlopen', fail)
    with pytest.raises(TelegramError) as exc:
        TelegramClient().send('-100999', 6, 'text')
    assert exc.value.code == 'NETWORK_UNREACHABLE' and not exc.value.uncertain


@pytest.mark.parametrize(('details', 'expected'), [
    ({'error': {'details': [{'reason': 'API_KEY_INVALID'}]}}, 'PROVIDER_AUTH'),
    ({'error': {'message': 'User location is not supported for the API use.'}}, 'PROVIDER_REGION'),
    ({'error': {'message': 'Request contains an invalid argument'}}, 'PROVIDER_CONFIG'),
])
def test_gemini_400_distinguishes_key_region_and_request(details, expected):
    from app.services.advisor import provider_error_code
    assert provider_error_code(400, details) == expected

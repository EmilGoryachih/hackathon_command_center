"""Интеграции можно проверить без внешних запросов."""
from __future__ import annotations

from tests.helpers import login


def test_telegram_mock_journal(client):
    login(client)
    r = client.post('/api/v1/projects/1/incidents', json={'level': 'yellow', 'title': 'Тест Telegram'})
    assert r.status_code == 200
    messages = client.get('/api/v1/admin/sandbox/telegram?project_id=1')
    assert messages.status_code == 200
    message = messages.json()[0]
    assert message['project_id'] == 1
    assert message['event_type'] == 'incident_yellow_created'
    assert message['mode'] == 'mock'
    assert 'Тест Telegram' in message['text']
    assert message['created_at']


def test_sandbox_notifications_do_not_touch_working_project(client):
    login(client)
    client.post('/api/v1/projects/1/tasks', json={'title': 'Рабочая просрочка', 'deadline': '2020-01-01T00:00:00'})
    r = client.post('/api/v1/admin/sandbox/run', json={'scenario': 'mock_notifications'})
    assert r.status_code == 200 and r.json()['status'] == 'ok'
    rows = client.get('/api/v1/admin/sandbox/telegram').json()
    assert rows and all(m['project_id'] != 1 for m in rows)
    assert {'task_assigned', 'incident_yellow_created', 'task_overdue'} <= {m['event_type'] for m in rows}


def test_task_events_do_not_generate_retired_advice(client):
    login(client)
    client.post('/api/v1/projects/1/incidents', json={'level':'yellow','title':'Blocker'})
    from app.db.models import AiRecommendation, AdvisorJob
    from tests.conftest import TestingSessionLocal
    with TestingSessionLocal() as db:
        assert db.query(AiRecommendation).count() == db.query(AdvisorJob).count() == 0

"""Rules use the shared operational facts; lifecycle and outbox commit together."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from tests.helpers import login
from tests.test_planning import task, lane, place
from tests.conftest import TestingSessionLocal

NOW = datetime(2030, 1, 1, 8)
BASE = '/api/v1/projects/1/situations/settings'


def snapshot(client):
    response = client.get('/api/v1/projects/1/analytics')
    assert response.status_code == 200, response.text
    return response.json()['summary']['situations']


def check():
    from app.services.situations import check_project
    with TestingSessionLocal() as db:
        return check_project(db, 1)


def clock(monkeypatch, now=NOW):
    monkeypatch.setattr('app.services.operational.utcnow', lambda: now)
    monkeypatch.setattr('app.services.situations.utcnow', lambda: now)


def enable(client):
    response = client.put(BASE, json={'enabled': True})
    assert response.status_code == 200, response.text


def test_unassigned_requires_time_and_plan_late_has_coverage(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    a = task(client, 'No time')
    assert not [s for s in snapshot(client) if s['type'] == 'unassigned_due']
    b = task(client, 'Near start')
    place(client, b, lane(client), start='2030-01-01T08:30:00')
    client.patch('/api/v1/projects/1', json={'deadline_msk': '2030-01-01T09:00:00Z'})
    found = snapshot(client)
    due = next(s for s in found if s['type'] == 'unassigned_due')
    assert due['task_ids'] == [b['id']] and due['level'] == 'attention'
    late = next(s for s in found if s['type'] == 'plan_late')
    assert late['evidence']['delta_seconds'] == 1800
    assert late['limitations'] and late['evidence']['covered_tasks'] == 1
    assert a['id'] not in due['task_ids']
    client.patch('/api/v1/projects/1', json={'deadline_msk': None})
    assert not [s for s in snapshot(client) if s['type'] == 'plan_late']


def test_blocked_start_combines_incident_and_hard_but_not_soft(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import TaskDependency
    root, hard, soft = [task(client, n) for n in ('Root', 'Hard', 'Soft')]
    track = lane(client)
    for t in (root, hard, soft):
        place(client, t, track, start='2030-01-01T08:30:00')
    with TestingSessionLocal() as db:
        db.add_all([TaskDependency(task_id=hard['id'], predecessor_id=root['id'], link_type='blocked_by'),
                    TaskDependency(task_id=soft['id'], predecessor_id=root['id'], link_type='after')])
        db.commit()
    incident = client.post('/api/v1/projects/1/incidents', json={'title':'Issue', 'level':'yellow',
        'source_task_id': root['id'], 'cascade_depth':4, 'targets':[{'target_type':'task','target_id':root['id']}]}).json()
    found = snapshot(client)
    blocked = [s for s in found if s['type'] == 'blocked_start']
    assert {s['task_ids'][0] for s in blocked} == {root['id'], hard['id']}
    assert all(s['incident_ids'] == [incident['id']] for s in blocked)
    hard_situation = next(s for s in blocked if s['task_ids'][0] == hard['id'])
    assert root['id'] in hard_situation['task_ids']
    assert hard_situation['evidence']['blocking_task_ids'] == [root['id']]
    assert not any(s['type'] == 'unassigned_due' and s['task_ids'][0] in (root['id'], hard['id']) for s in found)
    impact = next(s for s in found if s['type'] == 'incident_impact')
    assert impact['evidence']['potential_task_ids'] == [soft['id']]
    clock(monkeypatch, NOW - timedelta(days=2))
    assert not [s for s in snapshot(client) if s['type'] == 'blocked_start']


def test_overlaps_exclude_done_and_add_deadlines(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    a, b = task(client, 'A'), task(client, 'B', deadline='2030-01-01T09:00:00Z')
    track = lane(client)
    for t in (a, b):
        place(client, t, track, start='2030-01-01T08:30:00')
        client.put(f"/api/v1/tasks/{t['id']}/assignees", json={'assignees':[{'user_id':1,'is_primary':True}]})
    overlap = next(s for s in snapshot(client) if s['type'] == 'participant_overlap')
    assert overlap['user_ids'] == [1] and overlap['evidence']['deadlines']
    version = client.get(f"/api/v1/tasks/{b['id']}").json()['version']
    assert client.post(f"/api/v1/tasks/{b['id']}/move", json={'column_key':'done','version':version}).status_code == 200
    assert not [s for s in snapshot(client) if s['type'] == 'participant_overlap']


def test_lifecycle_baseline_restart_reappear_and_reminder(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import SituationState, TelegramDelivery
    a = task(client, 'A', deadline='2030-01-01T08:30:00Z')
    client.put('/api/v1/projects/1/telegram', json={'chat_id':'-100123','confirm_chat':True,
        'routes':{f'situation_{event}':0 for event in ('appeared','changed','resolved','reappeared','reminder')}})
    enable(client)
    assert check() == 0  # activation already baselines, repeated checks stay silent
    with TestingSessionLocal() as db:
        assert db.query(SituationState).count() >= 1
        assert db.query(TelegramDelivery).count() == 0
    b = task(client, 'B', deadline='2030-01-01T08:30:00Z')
    assert check() == 1
    assert check() == 0
    client.put(f"/api/v1/tasks/{b['id']}/assignees", json={'assignees':[{'user_id':1,'is_primary':True}]})
    assert check() == 1
    client.put(f"/api/v1/tasks/{b['id']}/assignees", json={'assignees':[]})
    assert check() == 1
    clock(monkeypatch, NOW + timedelta(minutes=121))
    assert check() >= 1
    assert check() == 0
    clock(monkeypatch, NOW + timedelta(minutes=242))
    assert check() >= 1
    with TestingSessionLocal() as db:
        events = [r.event_type for r in db.query(TelegramDelivery).filter(TelegramDelivery.event_type.like('situation_%')).order_by(TelegramDelivery.id)]
        assert events[:3] == ['situation_appeared','situation_resolved','situation_reappeared']
        assert 'situation_reminder' in events
    assert check() == 0


def test_concurrent_checks_and_missing_route_are_diagnostic(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    enable(client)
    task(client, 'New', deadline='2030-01-01T08:30:00Z')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: check(), range(2)))
    assert sum(results) == 1
    from app.db.models import SituationState
    with TestingSessionLocal() as db:
        row = db.query(SituationState).filter_by(situation_type='unassigned_due').one()
        assert row.delivery_issue == 'CHAT_NOT_CONFIGURED'


def test_settings_rights_validation_and_ai_removed(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    assert client.put(BASE, json={'near_minutes':0}).status_code == 422
    assert client.put(BASE, json={'reminder_minutes':2}).status_code == 422
    assert client.get('/api/v1/projects/1/ai/settings').status_code == 404
    uid = client.post('/api/v1/admin/users', json={'login':'reader','password':'test','display_name':'Reader'}).json()['id']
    client.post('/api/v1/admin/roles', json={'user_id':uid,'role':'participant','project_id':1})
    other = client.post('/api/v1/projects', json={'name':'Other'}).json()['id']
    login(client, 'reader', 'test')
    assert client.put(BASE, json={'enabled':True}).status_code == 403
    assert client.get(f'/api/v1/projects/{other}/situations/settings').status_code == 403
    assert client.get(f'/api/v1/projects/{other}/analytics').status_code == 403


def test_incident_impact_changes_show_added_and_removed_sets(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import TaskDependency, TelegramDelivery
    root, hard, soft = [task(client, n) for n in ('Root','Hard','Soft')]
    incident = client.post('/api/v1/projects/1/incidents', json={'title':'Issue','level':'yellow',
        'source_task_id':root['id'],'cascade_depth':4,'targets':[{'target_type':'task','target_id':root['id']}]}).json()
    client.put('/api/v1/projects/1/telegram', json={'chat_id':'-100123','confirm_chat':True,
        'routes':{'situation_changed':24,'situation_resolved':24}})
    enable(client)
    with TestingSessionLocal() as db:
        db.add_all([TaskDependency(task_id=hard['id'],predecessor_id=root['id'],link_type='blocked_by'),
                    TaskDependency(task_id=soft['id'],predecessor_id=root['id'],link_type='after')])
        db.commit()
    assert check() == 1
    assert check() == 0
    with TestingSessionLocal() as db:
        delivery = db.query(TelegramDelivery).filter_by(event_type='situation_changed').one()
        assert delivery.thread_id == 24
        assert f'Жёсткое влияние: добавлены [{hard["id"]}]' in delivery.text
        assert f'Возможное влияние: добавлены [{soft["id"]}]' in delivery.text
    assert client.post(f'/api/v1/incidents/{incident["id"]}/resolve',json={'resolution':'Fixed'}).status_code == 200
    assert check() == 1
    history = client.get('/api/v1/projects/1/situations/history').json()
    assert any(s['id'] == f'incident_impact:{incident["id"]}' and s['status']=='resolved' for s in history)


def test_restore_disables_and_rebaseline_does_not_replay_old_events(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import SituationConfig, SituationState, TelegramDelivery
    from app.services.restore_fence import suspend_external_actions
    from tests.conftest import engine, _TMP
    from pathlib import Path
    enable(client)
    task(client, 'A', deadline='2030-01-01T08:30:00Z')
    assert check() == 1
    # The worker's restore fence handles both current and older schemas.
    suspend_external_actions(Path(_TMP), '2030-01-01T08:00:00Z', database=Path(engine.url.database))
    assert check() == 0
    login(client)
    task(client, 'B', deadline='2030-01-01T08:30:00Z')
    enable(client)
    assert check() == 0
    with TestingSessionLocal() as db:
        assert db.get(SituationConfig,1).initialized_at is not None
        assert db.query(SituationState).filter_by(status='active').count() == 2
        assert db.query(TelegramDelivery).count() == 0


def test_rule_negative_and_missing_data_boundaries(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import Project, Task, BoardColumn
    # Missing times never imply urgency. Fully future, unassigned work is also not near.
    a = task(client, 'No time', None)
    b = task(client, 'Distant', deadline='2031-01-01T00:00:00Z')
    assert not snapshot(client)
    place(client, b, lane(client), start='2031-01-01T08:00:00')
    assert not [s for s in snapshot(client) if s['type'] in ('blocked_start','unassigned_due','plan_late')]
    with TestingSessionLocal() as db:
        db.get(Task,b['id']).column_id = db.query(BoardColumn).filter_by(project_id=1, semantic='done').first().id
        db.get(Task,a['id']).column_id = db.query(BoardColumn).filter_by(project_id=1, semantic='trash').one().id
        db.commit()
    assert not snapshot(client)
    with TestingSessionLocal() as db:
        db.get(Project,1).state='completed'
        db.commit()
    assert not snapshot(client)


def test_outbox_retry_mentions_project_isolation_and_atomicity(client, monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import User, SituationState, TelegramDelivery
    from app.services import telegram, situations
    from app.integrations.telegram import TelegramError
    uid = client.post('/api/v1/admin/users',json={'login':'helper','password':'test','display_name':'Helper'}).json()['id']
    client.post('/api/v1/admin/roles',json={'user_id':uid,'role':'participant','project_id':1})
    other = client.post('/api/v1/projects',json={'name':'Other'}).json()['id']
    secret = client.post(f'/api/v1/projects/{other}/tasks',json={'title':'Secret','deadline':'2020-01-01T00:00:00Z'}).json()['id']
    with TestingSessionLocal() as db:
        db.get(User,1).telegram_username='@good_name'
        db.get(User,uid).telegram_username='bad!'
        db.commit()
    client.put('/api/v1/projects/1/telegram',json={'chat_id':'-100123','confirm_chat':True,'routes':{'situation_appeared':88},'public_url':'https://example.org'})
    enable(client)
    a = task(client,'A',deadline='2030-01-01T08:30:00Z')
    original = situations.emit
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('rollback test')
    monkeypatch.setattr(situations,'emit',fail)
    import pytest
    with pytest.raises(RuntimeError):
        check()
    with TestingSessionLocal() as db:
        assert db.query(SituationState).count() == db.query(TelegramDelivery).count() == 0
    monkeypatch.setattr(situations,'emit',original)
    assert check() == 1
    with TestingSessionLocal() as db:
        row=db.query(TelegramDelivery).one()
        assert row.thread_id==88 and '@good_name' in row.text
        assert f'&task={a["id"]}' in row.text and 'Secret' not in row.text
        assert secret not in db.query(SituationState).one().payload['task_ids']
    def limited(*args):
        raise TelegramError('RATE_LIMIT',retry_after=2)
    assert telegram.work_once(TestingSessionLocal,limited)
    assert check()==0
    with TestingSessionLocal() as db:
        row=db.query(TelegramDelivery).one()
        row.next_attempt_at = datetime(2000,1,1)
        db.commit()
    assert telegram.work_once(TestingSessionLocal,lambda *args:55)
    assert not telegram.work_once(TestingSessionLocal,lambda *args:66)
    with TestingSessionLocal() as db:
        assert db.query(TelegramDelivery).one().message_ids==[55]


def test_mention_settings_and_bad_username_do_not_break_delivery(client,monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import User, TaskDependency, TelegramDelivery
    uid=client.post('/api/v1/admin/users',json={'login':'helper','password':'test','display_name':'No username'}).json()['id']
    client.post('/api/v1/admin/roles',json={'user_id':uid,'role':'participant','project_id':1})
    with TestingSessionLocal() as db:
        db.get(User,1).telegram_username='@captain_valid'
        db.get(User,uid).telegram_username='invalid!'
        db.commit()
    client.put('/api/v1/projects/1/telegram',json={'chat_id':'-100123','confirm_chat':True,'routes':{'situation_appeared':0}})
    enable(client)
    root,a=task(client,'Root'),task(client,'Blocked')
    place(client,a,lane(client),start='2030-01-01T08:30:00')
    client.put(f'/api/v1/tasks/{a["id"]}/assignees',json={'assignees':[{'user_id':uid,'is_primary':True}]})
    with TestingSessionLocal() as db:
        db.add(TaskDependency(task_id=a['id'],predecessor_id=root['id'],link_type='blocked_by'))
        db.commit()
    assert check()==1
    with TestingSessionLocal() as db:
        row=db.query(TelegramDelivery).filter_by(event_type='situation_appeared').one()
        assert '@captain_valid' in row.text and 'Без Telegram username: No username' in row.text
        assert row.mentions==['captain_valid']


def test_missing_dates_do_not_falsely_resolve_a_saved_risk(client,monkeypatch):
    login(client)
    clock(monkeypatch)
    from app.db.models import Task, SituationState, TelegramDelivery
    a=task(client,'Unassigned',deadline='2030-01-01T08:30:00Z')
    enable(client)
    with TestingSessionLocal() as db:
        db.get(Task,a['id']).deadline=None
        db.commit()
    found=next(s for s in snapshot(client) if s['id']==f'unassigned_due:{a["id"]}')
    assert found['status']=='active' and found['level']=='check'
    assert found['evidence']['verification']=='insufficient_data'
    assert check()==1  # changed to uncertain, never a false resolution
    assert check()==0
    with TestingSessionLocal() as db:
        assert db.query(SituationState).one().status=='active'
        assert not db.query(TelegramDelivery).filter_by(event_type='situation_resolved').count()
    assert client.put(f'/api/v1/tasks/{a["id"]}/assignees',json={'assignees':[{'user_id':1,'is_primary':True}]}).status_code==200
    assert check()==1
    with TestingSessionLocal() as db:
        assert db.query(SituationState).one().status=='resolved'

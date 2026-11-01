"""Small deterministic rules over the shared operational snapshot, plus durable lifecycle."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Project, SituationConfig, SituationState, Notification
from app.situation_schemas import Situation, SituationSettings
from app.timeutil import utcnow

if TYPE_CHECKING:
    from app.operational_schemas import OperationalSummary

LEVELS = {'attention': 'Требует внимания', 'check': 'Стоит проверить'}
EVENTS = {'appeared':'Появление', 'changed':'Изменение', 'resolved':'Разрешение',
          'reappeared':'Повторное появление', 'reminder':'Напоминание'}


def config(db: Session, project_id: int) -> SituationSettings:
    row = db.get(SituationConfig, project_id)
    return SituationSettings.model_validate(row) if row else SituationSettings()


def evaluate(s: OperationalSummary, cfg: SituationSettings) -> list[Situation]:
    """No DB reads, independent deadline/graph calculation, or invented availability."""
    if s.project_state == 'completed':
        return []
    now = s.generated_at
    near = now + timedelta(minutes=cfg.near_minutes)
    tasks = {t.id:t for t in s.tasks if t.availability != 'done'}
    members = {p.id for p in s.participants}
    tracks = {t.id for t in s.tracks if t.id is not None}
    incidents = {i.id:i for i in s.incidents}
    result: list[Situation] = []

    def add(kind: str, key: str, title: str, text: str, *, tids: list[int] | None = None,
            iids: list[int] | None = None, uids: list[int] | None = None,
            grounds: list[str] | None = None, evidence: dict[str, Any] | None = None,
            limitations: list[str] | None = None, suggestion: str | None = None,
            urgent: bool = True) -> None:
        tids = [tid for tid in dict.fromkeys(tids or []) if tid in tasks]
        iids = sorted(set(iids or []) & incidents.keys())
        users = set(uids or []) | {a.user_id for tid in tids for a in tasks[tid].assignees}
        track_ids = {tasks[tid].module_id for tid in tids} | {tid for iid in iids for tid in incidents[iid].track_ids}
        result.append(Situation(id=f'{kind}:{key}', project_id=s.project_id, type=kind,
            level='attention' if urgent else 'check', title=title, text=text,
            task_ids=tids, incident_ids=iids, user_ids=sorted(users & members),
            track_ids=sorted(track_ids & tracks), grounds=grounds or [], evidence=evidence or {},
            limitations=list(dict.fromkeys(limitations or [])), suggestion=suggestion, as_of=now))

    for tid, t in tasks.items():
        near_start = t.planned_start is not None and t.planned_start <= near
        confirmed = [i.id for i in s.incidents if tid in i.direct_task_ids or tid in i.hard_task_ids]
        actual = [int(i['id']) for i in t.blocking_incidents if i['id'] in incidents]
        blocked = bool(t.waiting_reasons or actual or any(tid in i.hard_task_ids for i in s.incidents))
        # A started task no longer has an approaching start; its current blockers remain in task facts.
        if near_start and not t.actual_started_at and blocked:
            blocking_task_ids = sorted(p.task_id for p in t.predecessors
                                       if p.link_type == 'blocked_by' and p.task_id in tasks)
            add('blocked_start', str(tid), f'Заблокирован старт задачи #{tid}',
                f'«{t.title}»: плановый старт {t.planned_start.isoformat()} UTC; препятствие ещё действует.',
                tids=[tid, *blocking_task_ids], iids=sorted(set(confirmed + actual)),
                grounds=[*t.waiting_reasons, *[f"Прямая блокировка: инцидент #{i['number']}" for i in t.blocking_incidents],
                         *[f'Жёсткое влияние инцидента #{i.number}' for i in s.incidents if tid in i.hard_task_ids],
                         *(['Исполнитель не назначен'] if not t.assignees else [])],
                evidence={'start':t.planned_start.isoformat(), 'phase':'due' if t.planned_start <= now else 'near',
                          'blockers':t.waiting_reasons, 'incident_ids':sorted(set(confirmed + actual)),
                          'unassigned':not t.assignees, 'blocking_task_ids':blocking_task_ids},
                limitations=[l for i in s.incidents if i.id in confirmed for l in i.limitations],
                suggestion='Проверьте препятствия, состояние инцидента и порядок выполнения.')
            continue  # One task/start situation includes missing assignment.
        dates = {name:value for name,value in [('Плановый старт',t.planned_start),
                 ('Плановое окончание',t.planned_end), ('Срок задачи',t.deadline)] if value is not None}
        relevant = {name:value for name,value in dates.items() if value <= near or
                    (s.period.deadline is not None and value > s.period.deadline)}
        if not t.assignees and relevant:
            add('unassigned_due', str(tid), f'Задача #{tid} без исполнителя: близкий срок',
                f'«{t.title}»: исполнитель не назначен.', tids=[tid],
                grounds=[f'{name}: {date.isoformat()} UTC' + (' — срок прошёл' if date <= now else
                    ' — за дедлайном проекта' if s.period.deadline and date > s.period.deadline else ' — приближается')
                    for name,date in relevant.items()],
                evidence={'dates':{k:v.isoformat() for k,v in relevant.items()},
                          'phase':'due' if any(v <= now for v in relevant.values()) else 'near'},
                limitations=['Без размещения в плане известен только срок задачи.'] if t.planned_start is None else [],
                suggestion='Проверьте назначение исполнителя и актуальность срока.')
    if s.plan.finish and s.period.deadline and s.plan.deadline_delta_seconds is not None and s.plan.deadline_delta_seconds > 0:
        add('plan_late', 'project', 'Текущий план выходит за дедлайн',
            'Рассчитанное окончание текущего плана позже дедлайна проекта.',
            grounds=[f'Окончание: {s.plan.finish.isoformat()} UTC', f'Дедлайн: {s.period.deadline.isoformat()} UTC',
                     f'Разница: {s.plan.deadline_delta_seconds} секунд',
                     f'Охват плана: {s.plan.covered_tasks} из {s.plan.total_tasks} задач'],
            evidence={'finish':s.plan.finish.isoformat(), 'deadline':s.period.deadline.isoformat(),
                      'delta_seconds':s.plan.deadline_delta_seconds, 'covered_tasks':s.plan.covered_tasks,
                      'total_tasks':s.plan.total_tasks, 'incomplete':s.plan.incomplete},
            limitations=s.plan.limitations, suggestion='Проверьте текущий план и неразмещённые задачи. Это не гарантия фактического опоздания.')
    for p in s.participants:
        for pair in p.overlaps:
            ids = sorted(set(pair) & tasks.keys())
            if len(ids) != 2:
                continue
            deadlines = {str(tid):tasks[tid].deadline.isoformat() for tid in ids if tasks[tid].deadline}
            blockers = {str(tid):[*tasks[tid].waiting_reasons,
                *[f"Инцидент #{i['number']}" for i in tasks[tid].blocking_incidents]] for tid in ids}
            imminent = any(tasks[tid].planned_start is not None and tasks[tid].planned_start <= near for tid in ids)
            add('participant_overlap', f'{p.id}:{ids[0]}:{ids[1]}', f'Пересечение задач: {p.display_name}',
                'В текущем плане пересекаются незавершённые задачи одного участника.', tids=ids, uids=[p.id],
                grounds=[f'Задачи: #{ids[0]} и #{ids[1]}',
                         *[f'#{tid}: {tasks[tid].planned_start} — {tasks[tid].planned_end} UTC' for tid in ids],
                         *[f'Срок #{tid}: {date} UTC' for tid,date in deadlines.items()],
                         *[f'#{tid}: {reason}' for tid,reasons in blockers.items() for reason in reasons]],
                evidence={'intervals':{str(tid):[str(tasks[tid].planned_start), str(tasks[tid].planned_end)] for tid in ids},
                          'deadlines':deadlines,'blockers':blockers,'phase':'near' if imminent else 'later'},
                urgent=imminent, limitations=['План не моделирует смены, навыки и фактическую доступность участников.'],
                suggestion='Проверьте порядок работ или возможность помощи.')
    for i in s.incidents:
        direct = sorted(set(i.direct_task_ids) & tasks.keys())
        hard = sorted(set(i.hard_task_ids) & tasks.keys())
        potential = sorted(set(i.potential_task_ids) & tasks.keys())
        add('incident_impact', str(i.id), f'Влияние инцидента #{i.number}', i.title,
            tids=sorted(set(direct + hard + potential)), iids=[i.id],
            uids=[int(t['target_id']) for t in i.targets if t['target_type'] == 'user'] + ([i.owner_id] if i.owner_id else []),
            grounds=[f'Прямые цели: {direct}', f'Жёсткое влияние: {hard}', f'Возможное влияние: {potential}'],
            evidence={'direct_task_ids':direct, 'hard_task_ids':hard, 'potential_task_ids':potential,
                      'track_ids':i.track_ids, 'status':i.status, 'level':i.level},
            limitations=[*i.limitations, 'Возможное влияние не означает подтверждённую блокировку.'],
            urgent=bool(direct or hard), suggestion='Проверьте изменение состава затронутых задач и состояние инцидента.')
    # Keep existing useful signals in this same list, suppressing facts already explained above.
    covered = {tid for item in result for tid in item.task_ids}
    for a in s.attention:
        if a.code in {'incident', 'overlap', 'missing_plan'}:
            continue
        ids = sorted(set(a.task_ids) & tasks.keys())
        if not ids or set(ids) <= covered:
            continue
        add('task_check', f'{a.code}:{ids[0]}', a.reason, a.reason, tids=ids,
            grounds=[f'Задача #{tid}: {tasks[tid].title}' for tid in ids],
            evidence={'code':a.code}, urgent=a.code in {'overdue', 'exhausted', 'beyond_deadline'},
            limitations=['Недостаток данных не доказывает отсутствие риска.'] if a.code == 'missing_plan' else [])
    return result


def fingerprint(item: Situation) -> str:
    stable = item.model_dump(include={'level','task_ids','incident_ids','user_ids','track_ids','evidence','limitations'})
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def decorate(db: Session, summary: OperationalSummary, items: list[Situation]) -> list[Situation]:
    """Read-only metadata; current facts always take precedence over previous worker state."""
    rows = {r.situation_key:r for r in db.query(SituationState).filter_by(project_id=summary.project_id)}
    current = {i.id for i in items}
    tasks = {t.id:t for t in summary.tasks if t.availability != 'done'}
    for key,row in rows.items():
        if key in current or row.status != 'active' or summary.project_state == 'completed':
            continue
        old = Situation.model_validate(row.payload)
        own = [tasks[tid] for tid in old.task_ids if tid in tasks]
        unknown = False
        if old.type == 'plan_late':
            unknown = summary.plan.finish is None or summary.period.deadline is None
        elif old.type == 'unassigned_due' and own and not own[0].assignees:
            unknown = not any((own[0].planned_start, own[0].planned_end, own[0].deadline))
        elif old.type == 'blocked_start' and own and not own[0].actual_started_at:
            unknown = own[0].planned_start is None and bool(own[0].waiting_reasons or own[0].blocking_incidents)
        elif old.type == 'participant_overlap' and len(own) == len(old.task_ids):
            still_assigned = all(set(old.user_ids) <= {a.user_id for a in t.assignees} for t in own)
            unknown = still_assigned and any(t.planned_start is None or t.planned_end is None for t in own)
        if unknown:
            old.level = 'check'
            old.text = 'Ранее обнаруженная ситуация не может быть перепроверена: необходимые сроки больше не заданы.'
            old.evidence = {**old.evidence, 'verification':'insufficient_data',
                            'previous_as_of':old.evidence.get('previous_as_of', old.as_of.isoformat())}
            old.limitations = list(dict.fromkeys([*old.limitations,
                'Основания относятся к прежнему снимку. Недостаток данных не подтверждает разрешение ситуации.']))
            old.suggestion = 'Проверьте и восстановите необходимые сроки в плане.'
            old.as_of = summary.generated_at
            items.append(old)
    for item in items:
        row = rows.get(item.id)
        if row:
            item.first_seen_at, item.changed_at = row.first_seen_at, row.changed_at
            item.delivery_issue = row.delivery_issue
    return items


def emit(db: Session, row: SituationState, kind: str, cfg: SituationSettings, previous: dict[str, Any] | None) -> None:
    from app.services.notifications import captains
    from app.deps import project_member_ids
    from app.services import telegram
    item = Situation.model_validate(row.payload)
    recipients = set(captains(db, row.project_id) if cfg.mention_captains else [])
    if cfg.mention_participants:
        recipients.update(item.user_ids)
    recipients &= set(project_member_ids(db, row.project_id))
    payload = {**row.payload, 'title':f'{EVENTS[kind]}: {item.title}', 'event':kind,
               'task_id':next(iter(item.task_ids), None), 'incident_id':next(iter(item.incident_ids), None)}
    ntype = f'situation_{kind}'
    for uid in sorted(recipients):
        db.add(Notification(project_id=row.project_id, user_id=uid, type=ntype, payload=payload))
    lines = [f'{"✅" if kind == "resolved" else "🔎"} {EVENTS[kind]}: {item.title}',
             '', f'Проект: {db.get(Project, row.project_id).name}', LEVELS[item.level],
             'Состояние: ' + ('разрешена' if kind == 'resolved' else 'действует'), item.text,
             *item.grounds]
    if previous and kind == 'changed':
        for name,label in [('direct_task_ids','Прямые цели'), ('hard_task_ids','Жёсткое влияние'),
                           ('potential_task_ids','Возможное влияние')]:
            old = set(previous.get('evidence', {}).get(name, []))
            new = set(item.evidence.get(name, []))
            if old != new:
                lines.append(f'{label}: добавлены {sorted(new-old)}, исключены {sorted(old-new)}')
    if kind == 'resolved':
        lines.append('Условие правила больше не действует в текущем снимке. Прежние основания приведены для контекста.')
    elif item.suggestion:
        lines += ['Проверьте: ' + item.suggestion]
    lines += ['Ограничение: ' + value for value in item.limitations]
    names, missing = telegram.mentions(db, sorted(recipients))
    if names:
        lines += [' '.join('@' + name for name in names)]
    if missing:
        lines += ['Без Telegram username: ' + ', '.join(missing)]
    tg = telegram.project_config(db, row.project_id)
    from app.config import settings
    from app.services.portable import current_public_url
    url = current_public_url() if settings.app_managed else (tg.public_url if tg else '')
    if url:
        lines += [f'Открыть задачу #{tid}: {url}?project={row.project_id}&task={tid}' for tid in item.task_ids]
        lines += [f'Открыть инцидент: {url}?project={row.project_id}&incident={iid}' for iid in item.incident_ids]
        if not item.task_ids and not item.incident_ids:
            lines += [f'Открыть: {url}?project={row.project_id}']
    row.delivery_issue = ('CHAT_NOT_CONFIGURED' if not tg or not tg.chat_id else
                          'ROUTE_DISABLED' if tg.routes.get(ntype) is None else None)
    if row.delivery_issue is None:
        telegram.enqueue(db, row.project_id, ntype, '\n'.join(lines), names,
                         event_key=f'situation:{row.id}:{row.revision}')


def reconcile(db: Session, project_id: int, *, baseline: bool = False) -> int:
    """Caller holds a DB write lock before reading the snapshot; no commits within this function."""
    from app.services.operational import build_summary
    cfg_row = db.get(SituationConfig, project_id)
    if cfg_row is None:
        return 0
    cfg = SituationSettings.model_validate(cfg_row)
    s = build_summary(db, project_id)
    now = s.generated_at
    baseline = baseline or cfg_row.initialized_at is None
    current = {i.id:i for i in s.situations} if s.project_state != 'completed' else {}
    rows = {r.situation_key:r for r in db.query(SituationState).filter_by(project_id=project_id)}
    count = 0
    for key in sorted(current.keys() | rows.keys()):
        item, row = current.get(key), rows.get(key)
        kind, previous = None, row.payload if row else None
        if item:
            digest = fingerprint(item)
            if row is None:
                row = SituationState(project_id=project_id, situation_key=key, situation_type=item.type,
                    status='active', fingerprint=digest, payload=item.model_dump(mode='json'), revision=0,
                    first_seen_at=now, changed_at=now, last_seen_at=now, last_event_at=now)
                db.add(row)
                db.flush()
                kind = 'appeared'
            elif row.status == 'resolved':
                kind = 'reappeared'
            elif digest != row.fingerprint:
                kind = 'changed'
            elif now - row.last_event_at >= timedelta(minutes=cfg.reminder_minutes):
                kind = 'reminder'
            row.status, row.fingerprint, row.payload = 'active', digest, item.model_dump(mode='json')
            row.last_seen_at, row.resolved_at = now, None
        elif row.status == 'active':
            row.status, row.resolved_at = 'resolved', now
            row.payload = {**row.payload, 'status':'resolved', 'resolved_at':now.isoformat(), 'as_of':now.isoformat()}
            kind = 'resolved'
        if kind:
            row.changed_at = now if kind != 'reminder' else row.changed_at
            row.last_event_at = now
            row.revision += 1
            if not baseline:
                emit(db, row, kind, cfg, previous)
                count += 1
        if baseline:
            row.last_event_at = now
            row.delivery_issue = None
    cfg_row.initialized_at, cfg_row.checked_at = now, now
    db.flush()
    return count


def lock_project(db: Session, project_id: int) -> None:
    # SQLite serializes writers across processes; PostgreSQL takes a row lock.
    # This is the first SQL in worker sessions, before any snapshot reads.
    db.execute(update(Project).where(Project.id == project_id).values(id=Project.id))
    db.expire_all()


def check_project(db: Session, project_id: int) -> int:
    lock_project(db, project_id)
    row = db.get(SituationConfig, project_id)
    count = reconcile(db, project_id) if row and row.enabled else 0
    db.commit()
    return count


def run_all(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        ids = [r[0] for r in db.query(SituationConfig.project_id).filter_by(enabled=True)]
    for project_id in ids:
        with factory() as db:
            check_project(db, project_id)

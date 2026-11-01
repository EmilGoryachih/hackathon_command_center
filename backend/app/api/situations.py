from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import SituationConfig, SituationState, User
from app.deps import get_db, get_current_user, require_captain_or_admin
from app.situation_schemas import SituationSettings, Situation
from app.services import situations as svc
from app.services.audit import write_audit

router = APIRouter(tags=['situations'])


@router.get('/projects/{project_id}/situations/settings')
def settings(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> dict:
    row = db.get(SituationConfig, project_id)
    return {**svc.config(db, project_id).model_dump(), 'checked_at':row.checked_at if row else None,
            'initialized_at':row.initialized_at if row else None,
            'policy':'При включении текущие ситуации сохраняются без рассылки; далее — изменения и напоминания.'}


@router.put('/projects/{project_id}/situations/settings')
def save(project_id: int, body: SituationSettings, db: Session = Depends(get_db),
         user: User = Depends(require_captain_or_admin)) -> dict:
    svc.lock_project(db, project_id)
    row = db.get(SituationConfig, project_id)
    before = svc.config(db, project_id)
    if row is None:
        row = SituationConfig(project_id=project_id)
        db.add(row)
    for name, value in body.model_dump().items():
        setattr(row, name, value)
    db.flush()
    # Enabling or changing thresholds establishes a silent, current baseline.
    if body.enabled and (not before.enabled or before.near_minutes != body.near_minutes):
        svc.reconcile(db, project_id, baseline=True)
    write_audit(db, action='situations.configured', actor_id=user.id, project_id=project_id, data=body.model_dump())
    db.commit()
    return settings(project_id, db, user)


@router.get('/projects/{project_id}/situations/history', response_model=list[Situation])
def history(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> list[Situation]:
    rows = db.query(SituationState).filter_by(project_id=project_id, status='resolved').order_by(
        SituationState.changed_at.desc()).limit(30)
    return [Situation.model_validate({**r.payload, 'first_seen_at':r.first_seen_at, 'changed_at':r.changed_at,
                                     'resolved_at':r.resolved_at, 'delivery_issue':r.delivery_issue}) for r in rows]

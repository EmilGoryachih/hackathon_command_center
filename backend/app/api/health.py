"""Эндпоинт проверки работоспособности."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db
from app.config import settings
from app.db.models import BoardColumn, Project, Role, RoleAssignment, User
from app import VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    # 200 только если БД доступна и папка данных записываема.
    db.execute(text("SELECT 1"))
    if settings.app_managed:
        from app.services.portable import storage_ready
        if not storage_ready():
            return JSONResponse({"status": "degraded", "reason": "storage"}, status_code=503)
        workers = getattr(request.app.state, "workers", [])
        if any(not worker.is_alive() for worker in workers):
            return JSONResponse({"status": "degraded", "reason": "workers"}, status_code=503)
        projects = db.query(Project.id).all()
        if len(projects) != 1:
            return JSONResponse({"status": "degraded", "reason": "project"}, status_code=503)
        project_id = projects[0][0]
        has_board = db.query(BoardColumn.id).filter_by(project_id=project_id).first() is not None
        has_admin = db.query(User.id).join(RoleAssignment, RoleAssignment.user_id == User.id).filter(
            User.active.is_(True), RoleAssignment.role == Role.admin,
            RoleAssignment.project_id.is_(None), RoleAssignment.revoked_at.is_(None)).first() is not None
        if not has_board or not has_admin:
            return JSONResponse({"status": "degraded", "reason": "project"}, status_code=503)
        return {"status": "ok", "installation": settings.app_installation_id,
                "version": VERSION, "project_id": project_id}
    return {"status": "ok"}

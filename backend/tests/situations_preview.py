"""Disposable browser fixture. No credentials, workers or real external delivery."""
import os
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from uuid import uuid4

folder = Path(__file__).parent / '.tmp' / ('situations-ui-' + uuid4().hex[:8])
folder.mkdir(parents=True)
os.environ.update(DATABASE_URL=f'sqlite:///{(folder / "qa.db").resolve().as_posix()}',
    APP_DATA_DIR=str(folder.resolve()), APP_FIRST_ADMIN_LOGIN='qa',
    APP_FIRST_ADMIN_PASSWORD='qa-pass-123', APP_FIRST_ADMIN_NAME='QA Captain',
    APP_STATIC_DIR=str(Path(__file__).resolve().parents[2] / 'frontend' / 'dist'))

from fastapi.testclient import TestClient
from app.main import create_app, run_migrations
from app.db.session import SessionLocal
from app.services.bootstrap import bootstrap
from app.services import telegram_vault

run_migrations()
with SessionLocal() as db:
    bootstrap(db)


@asynccontextmanager
async def isolated_lifespan(app):
    yield


app = create_app()
app.router.lifespan_context = isolated_lifespan
telegram_vault.is_saved = lambda: True
telegram_vault.available = lambda: True

with TestClient(app) as c:
    assert c.post('/api/v1/auth/login',json={'login':'qa','password':'qa-pass-123'}).status_code==200
    c.patch('/api/v1/projects/1',json={'name':'QA · Анализатор ситуаций','deadline_msk':(datetime.utcnow()+timedelta(hours=1)).isoformat()+'Z'})
    tasks=[c.post('/api/v1/projects/1/tasks',json={'title':name,'estimate_seconds':7200}).json() for name in
        ('Подготовить сервер','Проверить демо','Мягкая связь','Назначить исполнителя')]
    state=c.get('/api/v1/projects/1/planning').json()
    state=c.post('/api/v1/projects/1/planning',json={'revision':state['revision'],'op':'lane_create','name':'Backend'}).json()
    lane=state['lanes'][0]['id']
    for t in tasks:
        state=c.post('/api/v1/projects/1/planning',json={'revision':state['revision'],'op':'place',
            'task_id':t['id'],'lane_id':lane,'start':(datetime.utcnow()+timedelta(minutes=30)).isoformat()}).json()
    for t in tasks[:2]:
        c.put(f'/api/v1/tasks/{t["id"]}/assignees',json={'assignees':[{'user_id':1,'is_primary':True}]})
    c.post('/api/v1/projects/1/incidents',json={'title':'Нет доступа к стенду','level':'yellow',
        'source_task_id':tasks[0]['id'],'cascade_depth':4,'targets':[{'target_type':'task','target_id':tasks[0]['id']}]})
    c.put('/api/v1/projects/1/telegram',json={'chat_id':'-100000001','confirm_chat':True,
        'routes':{'situation_appeared':10,'situation_changed':10,'situation_resolved':20}})

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=18000,log_level='warning')

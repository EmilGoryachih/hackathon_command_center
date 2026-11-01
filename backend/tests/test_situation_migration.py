from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_populated_upgrade_preserves_history_and_ordinary_queue(tmp_path,monkeypatch):
    from app.config import settings
    url=f'sqlite:///{(tmp_path/"upgrade.db").as_posix()}'
    monkeypatch.setattr(settings,'database_url',url)
    backend=Path(__file__).resolve().parents[1]
    cfg=Config(str(backend/'alembic.ini'))
    cfg.set_main_option('script_location',str(backend/'alembic'))
    command.upgrade(cfg,'20261029_telegram_accounts')
    engine=create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO projects (id,name,state,settings,incident_counter,created_at) VALUES (1,'Keep','active','{}',0,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO ai_recommendations (project_id,provider,trigger,summary,content,excluded,created_at) VALUES (1,'gemini','manual','Keep','History',0,CURRENT_TIMESTAMP)"))
        for event in ('ai_report','task_assigned'):
            db.execute(text("INSERT INTO telegram_deliveries (project_id,event_type,text,mentions,mode,state,created_at) VALUES (1,:event,'Keep','[]','live','pending',CURRENT_TIMESTAMP)"),{'event':event})
    command.upgrade(cfg,'head')
    command.upgrade(cfg,'head')
    with engine.connect() as db:
        assert db.execute(text('SELECT name FROM projects')).scalar()=='Keep'
        assert db.execute(text('SELECT summary,content FROM ai_recommendations')).one()==('Keep','History')
        assert dict(db.execute(text('SELECT event_type,state FROM telegram_deliveries')).all())=={'ai_report':'cancelled','task_assigned':'pending'}
        assert db.execute(text('SELECT count(*) FROM situation_states')).scalar()==0
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
    engine.dispose()


def test_fresh_install_has_situation_schema(tmp_path,monkeypatch):
    from app.config import settings
    url=f'sqlite:///{(tmp_path/"fresh.db").as_posix()}'
    monkeypatch.setattr(settings,'database_url',url)
    backend=Path(__file__).resolve().parents[1]
    cfg=Config(str(backend/'alembic.ini'))
    cfg.set_main_option('script_location',str(backend/'alembic'))
    command.upgrade(cfg,'head')
    engine=create_engine(url)
    with engine.connect() as db:
        assert db.execute(text('SELECT count(*) FROM situation_settings')).scalar()==0
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
    engine.dispose()

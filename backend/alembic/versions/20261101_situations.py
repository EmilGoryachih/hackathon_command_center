"""Situation lifecycle; retain AI history and stop all previously queued AI work."""
from alembic import op
import sqlalchemy as sa

revision = '20261101_situations'
down_revision = '20261029_telegram_accounts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('situation_settings',
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('near_minutes', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('reminder_minutes', sa.Integer(), nullable=False, server_default='120'),
        sa.Column('mention_captains', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('mention_participants', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('initialized_at', sa.DateTime()), sa.Column('checked_at', sa.DateTime()))
    op.create_table('situation_states',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('situation_key', sa.String(120), nullable=False),
        sa.Column('situation_type', sa.String(40), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        *[sa.Column(name, sa.DateTime(), nullable=False) for name in
          ('first_seen_at', 'changed_at', 'last_seen_at', 'last_event_at')],
        sa.Column('resolved_at', sa.DateTime()), sa.Column('delivery_issue', sa.String(64)),
        sa.UniqueConstraint('project_id', 'situation_key', name='uq_project_situation'))
    op.create_index('ix_situation_states_project_id', 'situation_states', ['project_id'])
    op.execute("UPDATE ai_settings SET enabled=0, auto_enabled=0, next_run_at=NULL")
    op.execute("UPDATE advisor_jobs SET state='failed', error_code='AI_RETIRED', lease_token=NULL, lease_until=NULL WHERE state IN ('queued','running','retry','waiting')")
    op.execute("UPDATE telegram_deliveries SET state='cancelled', error_code='AI_RETIRED', lease_token=NULL, lease_until=NULL WHERE event_type IN ('ai_report','ai_recommendation') AND state IN ('pending','sending','error','uncertain')")


def downgrade() -> None:
    op.drop_table('situation_states')
    op.drop_table('situation_settings')
    # Deliberately never reactivate retired external work.

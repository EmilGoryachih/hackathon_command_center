# Модель данных

## Источник истины

`backend/app/db/models.py` описывает текущую ORM-модель, `backend/alembic/versions/` — переходы схемы. Точные SQL-типы, nullable, defaults, FK, индексы и ограничения проверяйте в этих файлах. Справочник ниже перечисляет все отображаемые таблицы и атрибуты ORM; `alembic_version` хранит отметку миграции отдельно.

SQLite использует WAL, foreign_keys=ON и timeout 30 секунд. Одна managed-установка обслуживает один проект одним backend-процессом. Наличие project_id сохраняется для целостности и совместимости разделения старых баз.

## Таблицы

| ORM-модель | Таблица | Атрибуты |
| --- | --- | --- |
| `User` | `users` | id, login, password_hash, display_name, telegram_username, active, deleted_identity, avatar, created_at |
| `Project` | `projects` | id, name, incident_counter, deadline_msk, start_msk, state, settings, created_at |
| `RoleAssignment` | `role_assignments` | id, user_id, project_id, role, granted_by, granted_at, revoked_at |
| `Session` | `sessions` | id, token_hash, user_id, ip, user_agent, created_at, expires_at, revoked_at |
| `LoginEvent` | `login_events` | id, login, ip, user_id, success, reason, created_at |
| `IpRule` | `ip_rules` | id, ip, action, created_by, created_at |
| `AuditEntry` | `audit_entries` | id, project_id, actor_id, action, entity_type, entity_id, data, created_at |
| `AuditRevision` | `audit_revisions` | id, audit_entry_id, field, old_value, new_value, edited_by, edited_at |
| `BoardColumn` | `board_columns` | id, project_id, key, title, position, semantic, auto_start_timer, auto_stop_timer |
| `Module` | `modules` | id, project_id, name, position, description, traffic_status, created_at |
| `Task` | `tasks` | id, project_id, column_id, module_id, parent_id, title, description, priority, estimate_seconds, actual_started_at, actual_completed_at, deadline, tags, version, created_at, updated_at |
| `PlanningState` | `planning_states` | project_id, revision |
| `PlanningLane` | `planning_lanes` | id, project_id, name, position |
| `TaskPlacement` | `task_placements` | task_id, lane_id, start, pinned |
| `PlanningBaseline` | `planning_baselines` | id, project_id, created_at, actor_id, snapshot |
| `TaskAssignee` | `task_assignees` | id, task_id, user_id, is_primary |
| `TaskDependency` | `task_dependencies` | id, task_id, predecessor_id, link_type |
| `ChecklistItem` | `checklist_items` | id, task_id, text, done, position |
| `TaskTimer` | `task_timers` | id, task_id, state, accumulated_seconds, last_started_at, created_at, updated_at |
| `TimerSegment` | `timer_segments` | id, task_id, started_at, ended_at |
| `Incident` | `incidents` | id, number, project_id, level, status, title, description, impact, urgency, author_id, owner_id, resolution, created_at, confirmed_at, resolved_at |
| `IncidentTarget` | `incident_targets` | id, incident_id, target_type, target_id |
| `IncidentEvent` | `incident_events` | id, incident_id, actor_id, event_type, data, created_at |
| `Notification` | `notifications` | id, project_id, user_id, type, payload, read_at, created_at |
| `Document` | `documents` | id, project_id, path, author_id, checksum, trashed, created_at, updated_at |
| `DocumentLock` | `document_locks` | id, document_id, user_id, acquired_at, last_activity_at |
| `AiSettings` | `ai_settings` | id, project_id, enabled, priority_provider, prompt, interval_minutes, triggers, auto_enabled, next_run_at, created_at, updated_at |
| `AiRecommendation` | `ai_recommendations` | id, project_id, provider, trigger, summary, content, request_context, excluded, structured, status, status_by, status_at, comment, snapshot_at, snapshot_version, fingerprint, last_seen_at, created_at |
| `AdvisorProviderSettings` | `advisor_provider_settings` | id, model, rpm, rpd, tpm, max_attempts, max_input_tokens, lock_version |
| `AdvisorJob` | `advisor_jobs` | id, project_id, user_id, kind, trigger, priority, question, state, attempts, snapshot, snapshot_at, snapshot_version, answer, error_code, lease_until, lease_token, next_attempt_at, created_at, finished_at |
| `AdvisorAttempt` | `advisor_attempts` | id, job_id, reserved_tokens, actual_input, actual_output, actual_thinking, outcome, created_at |
| `TelegramDelivery` | `telegram_deliveries` | id, project_id, event_type, text, mentions, mode, chat_id, thread_id, state, attempts, next_attempt_at, attempted_at, sent_at, lease_token, lease_until, error_code, message_ids, event_key, created_at |
| `TelegramSettings` | `telegram_settings` | project_id, chat_id, routes, public_url |
| `SituationConfig` | `situation_settings` | project_id, enabled, near_minutes, reminder_minutes, mention_captains, mention_participants, initialized_at, checked_at |
| `SituationState` | `situation_states` | id, project_id, situation_key, situation_type, status, fingerprint, payload, revision, first_seen_at, changed_at, last_seen_at, last_event_at, resolved_at, delivery_issue |
| `CompletionVote` | `completion_votes` | id, project_id, user_id, action, created_at |
| `BackupRecord` | `backup_records` | id, path, checksum, size_bytes, kind, created_at |
| `SandboxRun` | `sandbox_runs` | id, scenario, status, logs, checks, duration_ms, run_by, created_at |

## Связи и инварианты

- Project объединяет колонки, треки, задачи, инциденты, уведомления, документы, настройки/состояния ситуаций и Telegram.
- RoleAssignment связывает пользователя с проектной ролью; admin глобален и имеет project_id=null. Активность назначения учитывает revoked_at и состояние пользователя.
- Task.column_id/module_id/parent_id и все переданные участники/зависимости должны принадлежать допустимому проекту. Эта принадлежность проверяется сервисами, а не только одиночными FK.
- TaskAssignee хранит участников и основного исполнителя. У TaskTimer один экземпляр на задачу, TimerSegment хранит фактические интервалы; ручные изменения плана их не заменяют.
- TaskDependency хранит направленную пару task_id/predecessor_id и link_type; уникальность пары обеспечена БД, а цикл и межпроектные связи проверяет сервис.
- Треки актуального плана используют Module (`modules`), хотя TaskPlacement сохраняет имя lane_id. Совместимую PlanningLane нельзя автоматически считать действующим справочником треков.
- PlanningState.revision и Task.version обеспечивают разные уровни optimistic concurrency. PlanningBaseline хранит снимки, хотя фиксация исходного плана не представлена отдельным UI-действием.
- Incident имеет уникальный номер внутри проекта. IncidentTarget допускает типизированные цели, поэтому принадлежность полиморфной цели проверяет сервер.
- Document хранит путь/checksum; файлы находятся под documents. DocumentLock уникален для документа и истекает без heartbeat.
- TelegramDelivery хранит исходное направление, event_key, lease и подтверждённые части. SituationState уникален по (project_id, situation_key), имеет fingerprint и revision.
- История аудита и ревизии правок отделены. Удаление аккаунта использует техническую deleted_identity для сохранения исторических FK; это не действующая учётная запись.

## Сохранённые совместимые данные

`ai_*`, `advisor_*`, прежние baseline/lane-структуры и записи preview могут присутствовать в базе. Внешний ИИ отключён: таблицы сохраняются для истории, миграций, восстановления и обезличивания. Не включайте их задания, не выдавайте наличие таблицы за работающий API и не удаляйте их произвольно.

## Изменение и восстановление

Добавляйте новую миграцию, проверяйте чистую и заполненную БД. Сверяйте nullable/server_default для новых обязательных полей. При добавлении project/user-связей обновляйте разделение базы, очистку тестовой среды, удаление аккаунта и restore fence.

Перед managed-миграцией известной старой схемы создаётся зашифрованная safety-копия. Неизвестная ревизия блокируется; `stamp head` не исправляет схему. Backup содержит всю БД, поэтому копирование только таблиц задач не является восстановлением проекта.

После restore внешние действия приостановлены, сессии отозваны, running-таймеры закрыты на snapshot_at. Сохранение файла hackathon.db без согласования WAL/документов не заменяет штатный снимок.

[Миграции и проверки](../docs/08-development-guide.md) · [Восстановление](../docs/17-portable-operations.md)

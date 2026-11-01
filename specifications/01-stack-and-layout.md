# Стек, процессы и конфигурация

## Стек и каталоги

Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite WAL/FK. Frontend: React 18, TypeScript, Vite, CSS без отдельного роутера и UI-фреймворка. Realtime — SSE. Внешняя модель, Google Drive, Autoheal и Uptime Kuma не используются.

`backend/app/api` отвечает за HTTP, `services` — бизнес-правила, `db` — ORM и соединения, `integrations` — Telegram; `backend/alembic` хранит миграции. React-приложение находится в `frontend/src`. Хостовый менеджер и его локальный UI находятся в `control`.

Зависимости Docker фиксирует `backend/requirements.lock`, панель — `control/requirements.lock`. Npm lock-файлы frontend и DOM-тестов панели независимы. Dockerfile использует Node 22 для сборки frontend и Python 3.12 для финального образа; базовые образы закреплены digest.

## Процессы

| Режим | Процессы и адреса |
| --- | --- |
| Управляемый | Ouroboros на хосте `127.0.0.1:8787`, один контейнер Aion с API/static frontend на `127.0.0.1:8000` |
| Разработка | Uvicorn на 8000, Vite на 5173 с proxy API; отдельная тестовая папка данных |
| Фоновые потоки Aion | Просрочки/locks, Argus, отправщик Telegram |
| Хост | Монитор Ouroboros, операции архивов, принадлежащий установке fxTunnel/WSL-клиент |

Docker запускает один uvicorn worker с `--no-proxy-headers`; read-only rootfs, tmpfs, cap_drop ALL, no-new-privileges, ограничение логов. Healthcheck не перезапускает контейнер сам: аварийный выход обслуживает restart policy, нездоровый работающий API — ограниченная политика Ouroboros.

## Конфигурация backend

`app.config.Settings` читает окружение и корневой `.env` при импорте.

| Переменные | Смысл |
| --- | --- |
| APP_DATA_DIR | Абсолютная папка данных; по умолчанию корневой data — для ручного запуска |
| DATABASE_URL | Явный URL БД, имеет приоритет над APP_DATA_DIR для выбора БД |
| APP_MANAGED | Включает защиту управляемой установки и локальные операции |
| APP_ENV | Метка окружения |
| APP_INSTALLATION_ID, APP_PROJECT_NAME | Идентификатор установки и имя начального проекта |
| APP_STATIC_DIR | Production frontend, смонтированный FastAPI после маршрутов API |
| APP_SECRETS_DIR | Read-only файлы operator, bootstrap_password, telegram |
| APP_FIRST_ADMIN_LOGIN, APP_FIRST_ADMIN_NAME | Данные начального администратора |
| APP_FIRST_ADMIN_PASSWORD | Пароль bootstrap только вне managed-режима |

Наличие поля настройки само по себе не означает интеграцию: оставшиеся совместимые поля Google Drive/fxTunnel в backend не заменяют хостовые настройки Ouroboros. `APP_HOST/APP_PORT` не меняют уже заданные CLI-аргументы uvicorn. Изменение конфигурации требует перезапуска.

## Хранилища и сборка

В управляемом режиме путь выбирает оператор вне checkout. Реестр и защищённое состояние хоста находятся в `.control`, данные проекта — в выбранной папке. БД, документы и архивы не входят в образ; runtime-секреты монтируются отдельно.

Корневой `docker-compose.yml` — ручной шаблон, требует защищённой папки HCC_RUNTIME_DIR. Предпочтителен генерируемый Ouroboros Compose установки: его настройки содержат идентичность выбранного проекта. Не запускайте шаблон поверх работающей базы.

[Управляемый запуск](../docs/17-portable-operations.md) · [Изолированная разработка](../docs/08-development-guide.md)

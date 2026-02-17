# Control Panel

Панель управления на FastAPI + SQLModel + Jinja2/HTMX/Alpine + Chart.js.

> Важно: используются только сгенерированные метрики и события, без реальных сетевых подключений.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Откройте: http://127.0.0.1:8000

## Страницы

- `/dashboard` — KPI + мини-графики трендов.
- `/agents` — таблица агентов, фильтры/поиск/сортировка, APPLY/STOP действия и последние telemetry по агенту.
- `/profiles` — каталог профилей с поиском и сортировкой.
- `/audit` — журнал действий с фильтрами.
- `/analytics` — расширенная аналитика: KPI, 5 графиков, последние события, CSV-экспорт telemetry.
- `/tests` — результаты тестовых прогонов и график % успешных прогонов по дням.

## API

- `GET /api/metrics/kpi?range=1h|24h|7d`
- `GET /api/metrics/traffic?range=1h|24h`
- `GET /api/metrics/latency?range=1h|24h`
- `GET /api/metrics/actions?range=24h`
- `GET /api/metrics/profile_distribution?range=7d`
- `GET /api/metrics/top_errors?range=24h`
- `GET /api/telemetry/export.csv?range=24h|1h|7d`

## Seed

При первом запуске создаются:
- 3 пользователя (`admin`, `operator`, `viewer`)
- 7 агентов
- 5 профилей
- telemetry за последние 60 минут
- audit/test-run история для непустых графиков


## Запуск в PyCharm

1. Откройте корень проекта в PyCharm.
2. Настройте интерпретатор и установите зависимости: `pip install -r requirements.txt`.
3. Запускайте файл `app/main.py` как обычный Python Script (Run).
4. После старта откройте `http://127.0.0.1:8000`.

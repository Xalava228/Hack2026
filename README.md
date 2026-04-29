# БПК-IT_ver.3.0

Сервис для автоматической генерации презентаций по текстовому запросу.
Продукт формирует структуру слайдов, тексты и иллюстрации с помощью API `ai.rt.ru`,
после чего экспортирует итог в **PPTX** и/или **PDF**.

## Ссылка на хостинг

- Продакшн/демо: https://render.com/ ( https://hack2026-a76j.onrender.com ) 

## Описание продукта

- Принимает промпт в духе «История развития ИИ от Тьюринга до GPT-5»
- Сам выбирает структуру презентации
- Параллельно генерирует AI-иллюстрации (Yandex ART или Stable Diffusion)
- Собирает файл в **PPTX** (через `python-pptx`) и/или **PDF** (через `reportlab`)
- Включает веб-интерфейс: форма → редактор слайдов → экспорт
- Никаких внешних зависимостей вроде Office/LibreOffice — PDF рендерится напрямую

## Стек

- **Frontend:** HTML, CSS, Vanilla JavaScript
- **Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic
- **AI/HTTP:** ai.rt.ru API, httpx
- **Документы и рендер:** python-pptx, ReportLab, Pillow, pypdf, python-docx
- **Инфраструктура:** локальный запуск через `run.py`, хранение артефактов в файловой системе

## Параметры в UI

- **Тема презентации** — текстовый промпт
- **Количество слайдов** — 3…20
- **Плотность текста** — минимум / баланс / подробно
- **Картинки** — с AI-иллюстрациями или без
- **Генератор картинок** — Yandex ART / Stable Diffusion
- **Формат файла** — PPTX, PDF или оба

## Инструкция по развертыванию в локальном контуре

```bash
python -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # Linux/Mac

pip install -r requirements.txt
```

## Настройка токена

Создайте файл `.env` рядом с `run.py` (или скопируйте из `.env.example`):

```
AI_TOKEN=<ваш токен>
AI_BASE_URL=https://ai.rt.ru/api/1.0
```

Если токен истёк — обновите его, перезапускать сервер не нужно для
последующих запросов (`.env` читается при старте).

## Запуск

```bash
python run.py
```

Откройте `http://127.0.0.1:8000` — это и есть UI.

## Архитектура приложения

```
frontend/                 — HTML/CSS/JS интерфейс (без фреймворков)
backend/
  main.py                 — FastAPI: /api/generate, /api/jobs/{id}, /api/jobs/{id}/file/{kind}
  ai_client.py            — Асинхронный клиент к ai.rt.ru (LLM + ART + SD + download)
  slide_planner.py        — Планировщик: промпт → JSON-структура слайдов
  pptx_builder.py         — Рендер PPTX через python-pptx
  pdf_builder.py          — Рендер PDF через reportlab (поддержка кириллицы)
  orchestrator.py         — Полный пайплайн + хранилище задач в памяти
  config.py               — Конфигурация и .env-loader
generated/                — Сюда складываются готовые файлы (создаётся автоматически)
```

## Поток генерации

1. Пользователь жмёт «Сгенерировать» → `POST /api/generate` создаёт job
2. Бэкенд асинхронно:
   - Запрашивает у Qwen JSON-план (заголовок, палитра, слайды, image-prompts)
   - Параллельно через `asyncio.Semaphore(3)` генерирует картинки в Yandex ART
   - Собирает PPTX и/или PDF
3. Фронтенд опрашивает `GET /api/jobs/{id}` каждые ~1.2 сек,
   показывает шаги и прогресс-бар
4. По готовности — кнопки скачивания файлов из `/api/jobs/{id}/file/{pptx|pdf}`

## API (минимальный пример)

```bash
curl -X POST http://127.0.0.1:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Влияние ИИ на образование",
    "n_slides": 8,
    "text_density": "balanced",
    "images_mode": "with-images",
    "image_backend": "yandex-art",
    "output_format": "both"
  }'
# -> { "job_id": "abc123..." }

curl http://127.0.0.1:8000/api/jobs/abc123...
# -> {... "status": "done", "result": {...} }

# скачать
curl -OJ http://127.0.0.1:8000/api/jobs/abc123.../file/pptx
```

## Замечания

- Токен в `.env.example` — тот, который выдан на хакатоне. У него ограниченный
  срок действия. При ошибке 401/403 обновите токен.
- Если LLM вернула невалидный JSON, выполняется один автоматический ретрай.
- Если изображение ещё не готово, `download` опрашивается до 30 раз с интервалом
  2 секунды.
- Все задачи хранятся в памяти процесса — при рестарте теряются (для хакатона
  достаточно; в проде стоит вынести в Redis).

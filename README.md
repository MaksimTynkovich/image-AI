## Telegram бот‑агрегатор ИИ (aiogram + Kie.ai nano-banana-pro)

Этот проект — заготовка для бота‑агрегатора разных ИИ моделей (текст, фото, видео и т.д.).
На первом этапе реализована **генерация изображений** через Kie.ai и модель `nano-banana-pro`.

### Установка

1. Создай и активируй виртуальное окружение (опционально, но желательно):

```bash
python -m venv .venv
source .venv/bin/activate  # macOS / Linux
# .venv\Scripts\activate   # Windows PowerShell
```

2. Установи зависимости:

```bash
pip install -r requirements.txt
```

### Настройка окружения

1. Создай файл `.env` на основе примера:

```bash
cp .env.example .env
```

2. Заполни переменные:

- **TELEGRAM_BOT_TOKEN** — токен бота от [BotFather](https://t.me/BotFather).
- **KIE_API_KEY** — API‑ключ Kie.ai (раздел Nano Banana Pro, см. [документацию](https://kie.ai/nano-banana-pro)).
- **KIE_CALLBACK_URL** — при необходимости собственный callback‑URL (может быть пустым, если не используешь колбэки).

### Запуск бота

```bash
python bot.py
```

После запуска:

- Найди бота в Telegram по его username.
- Отправь любую текстовую фразу — бот воспримет её как промпт и сгенерирует изображение.
- Либо используй команду:

```bash
/imagine банан‑супергерой в стиле комикса
```

### Где править интеграцию с Kie.ai

- Основная логика запроса к Kie.ai и разбор ответа — в файле `kie_client.py`.
- Эндпоинт использует пример из официальной документации: `POST https://api.kie.ai/api/v1/jobs/createTask`.
- Если структура ответа у твоего аккаунта отличается (например, другой путь до `image_url`), открой
  [страницу Nano Banana Pro](https://kie.ai/nano-banana-pro) и адаптируй разбор JSON в методе
  `KieClient.generate_image`.


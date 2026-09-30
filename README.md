# YouTube Downloader Bot

Telegram-бот на aiogram 3 и yt-dlp: пришлите ссылку на YouTube, выберите качество кнопкой и получите видео или MP3 прямо в чат. Бот показывает только те форматы, которые пролезают в лимит Telegram.

[![License](https://img.shields.io/github/license/tgKishikaisei/youtube_downloader_video)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/tgKishikaisei/youtube_downloader_video/ci.yml?branch=main&label=CI)](https://github.com/tgKishikaisei/youtube_downloader_video/actions/workflows/ci.yml)

## Что умеет

- Показывает название, автора и длительность ролика, а под ними кнопки с разрешениями и примерным размером файла.
- Отдаёт видео с правильными пропорциями или только звук в MP3.
- Отбрасывает форматы больше 49 МБ (предел Bot API) и ролики длиннее `MAX_DURATION_MIN` минут, плейлисты не качает.
- Качает в отдельных потоках: пока один пользователь ждёт файл, бот отвечает остальным. Одновременно идёт не больше `MAX_PARALLEL_DOWNLOADS` загрузок, у одного человека одна.
- Каждая загрузка получает свою временную папку, которая удаляется даже при ошибке.

Ссылка проходит строгую проверку в `safe_url.py`: принимается только http(s) с хостом YouTube из белого списка.

## Стек

Python 3.12, aiogram 3, yt-dlp, ffmpeg.

## Запуск

Нужен **ffmpeg** в PATH: yt-dlp склеивает им видео со звуком и делает MP3.

```bash
git clone https://github.com/tgKishikaisei/youtube_downloader_video.git
cd youtube_downloader_video
python -m venv venv
venv\Scripts\activate                # Linux и macOS: source venv/bin/activate
pip install --require-hashes -r requirements.txt
cp .env.example .env                  # впишите TELEGRAM_BOT_TOKEN
python bot.py
```

Если на сервере YouTube отвечает «Sign in to confirm you're not a bot», выгрузите cookies браузера в формате Netscape и укажите путь в `YTDLP_COOKIES_FILE`. Файл cookies уже в `.gitignore`.

## Тесты

```bash
pip install --require-hashes -r requirements-dev.txt
python -m pytest -q
```

## Демо

Скриншотов нет: бот работает в Telegram, запустите его со своим токеном от @BotFather.

## Лицензия

[MIT](LICENSE) © 2025-2026 Behruz Avezmatov

"""YouTube Downloader — Telegram-бот (aiogram 3 + yt-dlp).

Запуск: python bot.py  (TELEGRAM_BOT_TOKEN в .env)

Как устроено:
- скачивание и запросы к YouTube выполняются в отдельных потоках (asyncio.to_thread),
  поэтому бот отвечает всем, пока кто-то качает видео;
- не больше MAX_PARALLEL_DOWNLOADS загрузок одновременно и одна активная загрузка на пользователя;
- у каждой загрузки своя временная папка: файлы разных пользователей не пересекаются
  и удаляются даже при ошибке;
- лимиты: размер ≤ 49 МБ (ограничение Bot API), длительность ≤ MAX_DURATION_MIN, без плейлистов;
- формат выбирается только из предложенных кнопок, строка из callback в yt-dlp не попадает;
"""
import asyncio
import html
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from safe_url import is_youtube_url

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("yt-bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_UPLOAD_BYTES = 49 * 1024 * 1024  # Bot API не отправляет файлы больше 50 МБ
MAX_DURATION_MIN = int(os.getenv("MAX_DURATION_MIN", "60"))
MAX_PARALLEL_DOWNLOADS = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "2"))
SESSION_TTL = 15 * 60  # сколько секунд помним выбор пользователя
DOWNLOAD_ROOT = Path(os.getenv("DOWNLOAD_DIR", Path(__file__).with_name("downloads")))
HEIGHTS = (144, 240, 360, 480, 720, 1080)

router = Router()
download_slots = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)
active_users: set[int] = set()


@dataclass
class VideoSession:
    url: str
    title: str
    uploader: str
    duration: int
    heights: list[int]
    created: float = field(default_factory=time.monotonic)


sessions: dict[int, VideoSession] = {}


# ---------------------------------------------------------------- yt-dlp -----

def _base_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
    # С серверных IP YouTube часто требует «Sign in to confirm you're not a bot».
    # Тогда нужен экспорт cookies (формат Netscape) — путь в YTDLP_COOKIES_FILE.
    cookies = os.getenv("YTDLP_COOKIES_FILE")
    if cookies and Path(cookies).is_file():
        opts["cookiefile"] = cookies
    return opts


def fetch_info(url: str) -> tuple[VideoSession, str | None]:
    """Метаданные без скачивания (выполняется в отдельном потоке)."""
    with YoutubeDL(_base_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    heights = sorted({
        f["height"] for f in info.get("formats", [])
        if f.get("vcodec") not in (None, "none") and f.get("height") in HEIGHTS
    })
    return VideoSession(
        url=url,
        title=info.get("title") or "Без названия",
        uploader=info.get("uploader") or "Неизвестно",
        duration=int(info.get("duration") or 0),
        heights=heights,
    ), info.get("thumbnail")


def download(url: str, target_dir: str, height: int | None) -> Path:
    """Скачивает видео (height) или только аудио (height=None) в target_dir и возвращает путь к файлу."""
    opts = {
        **_base_opts(),
        "outtmpl": os.path.join(target_dir, "media.%(ext)s"),
        "max_filesize": MAX_UPLOAD_BYTES,
    }
    if height is None:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio"
    else:
        # mp4 + m4a склеиваются без перекодирования; запасной вариант — лучший поток до нужной высоты.
        opts["format"] = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best[height<={height}]"
        )
        opts["merge_output_format"] = "mp4"
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
    files = [p for p in Path(target_dir).iterdir() if p.is_file() and not p.name.endswith(".part")]
    if not files:
        raise FileNotFoundError("yt-dlp не создал файл (возможно, превышен лимит размера)")
    return max(files, key=lambda p: p.stat().st_size)


# ---------------------------------------------------------------- Хендлеры ---

def _caption(s: VideoSession, extra: str) -> str:
    minutes, seconds = divmod(s.duration, 60)
    return (
        f"<b>{html.escape(s.title)}</b>\n"
        f"👤 {html.escape(s.uploader)}\n"
        f"⏳ {minutes}:{seconds:02d}\n\n{extra}"
    )


def _keyboard(s: VideoSession) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🎧 Только аудио", callback_data="dl|audio")]]
    rows += [[InlineKeyboardButton(text=f"🎬 {h}p", callback_data=f"dl|{h}")] for h in s.heights]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! Пришлите ссылку на видео YouTube — предложу качество для скачивания.")


@router.message(F.text)
async def handle_link(message: types.Message):
    url = message.text.strip()
    if not is_youtube_url(url):
        await message.answer("Пришлите, пожалуйста, ссылку на YouTube (youtube.com или youtu.be).")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        session, thumbnail = await asyncio.to_thread(fetch_info, url)
    except DownloadError as e:
        log.warning("extract_info failed: %s", e)
        if "confirm you" in str(e) and "not a bot" in str(e):
            await message.answer("YouTube временно ограничил доступ боту. Администратору: задайте YTDLP_COOKIES_FILE.")
        else:
            await message.answer("Не удалось получить информацию о видео. Проверьте ссылку.")
        return

    if session.duration > MAX_DURATION_MIN * 60:
        await message.answer(f"Видео длиннее {MAX_DURATION_MIN} минут — такое бот не скачивает.")
        return

    sessions[message.from_user.id] = session
    text = _caption(session, "Выберите качество или скачайте только аудио.\n"
                             "Файлы больше 49 МБ Telegram не пропустит — берите качество пониже.")
    try:
        if thumbnail:
            await message.answer_photo(thumbnail, caption=text, reply_markup=_keyboard(session))
            return
    except TelegramBadRequest:
        log.info("thumbnail rejected by Telegram, sending text")
    await message.answer(text, reply_markup=_keyboard(session))


@router.callback_query(F.data.startswith("dl|"))
async def handle_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = sessions.get(user_id)
    if not session or time.monotonic() - session.created > SESSION_TTL:
        await callback.answer("Ссылка устарела — пришлите её заново.", show_alert=True)
        return

    choice = callback.data.split("|", 1)[1]
    if choice == "audio":
        height = None
    elif choice.isdigit() and int(choice) in session.heights:
        height = int(choice)
    else:
        await callback.answer("Неизвестный формат.", show_alert=True)
        return

    if user_id in active_users:
        await callback.answer("Дождитесь окончания предыдущей загрузки.", show_alert=True)
        return

    await callback.answer()
    active_users.add(user_id)
    status = await callback.message.answer("⏬ Скачиваю… Если бот занят, загрузка начнётся по очереди.")
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        async with download_slots:
            with tempfile.TemporaryDirectory(dir=DOWNLOAD_ROOT) as tmp:
                try:
                    path = await asyncio.to_thread(download, session.url, tmp, height)
                except (DownloadError, FileNotFoundError):
                    log.exception("download failed")
                    await callback.message.answer(
                        "Не удалось скачать: файл больше 49 МБ или видео недоступно. Попробуйте качество ниже."
                    )
                    return
                if path.stat().st_size > MAX_UPLOAD_BYTES:
                    await callback.message.answer("Файл больше 49 МБ — выберите качество ниже или аудио.")
                    return
                caption = _caption(session, "✅ Готово")
                media = types.FSInputFile(path, filename=f"{session.title[:60]}{path.suffix}")
                if height is None:
                    await callback.message.answer_audio(media, caption=caption, title=session.title[:60],
                                                        performer=session.uploader[:60], request_timeout=120)
                else:
                    await callback.message.answer_video(media, caption=caption, supports_streaming=True,
                                                        request_timeout=120)
    finally:
        active_users.discard(user_id)
        sessions.pop(user_id, None)
        try:
            await status.delete()
        except TelegramBadRequest:
            pass


async def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан (.env)")
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

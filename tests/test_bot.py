"""Тесты bot.py без сети: yt-dlp и Telegram подменяются."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST-TOKEN-NOT-REAL")

import bot  # noqa: E402
from safe_url import is_youtube_url  # noqa: E402


@pytest.mark.parametrize("url,ok", [
    ("https://www.youtube.com/watch?v=abc", True),
    ("https://youtu.be/abc", True),
    ("https://m.youtube.com/watch?v=abc", True),
    ("https://evil.com/?youtube.com", False),
    ("https://youtube.com.evil.com/x", False),
    ("--exec=calc youtube.com", False),
    ("ftp://youtube.com/x", False),
])
def test_is_youtube_url(url, ok):
    assert is_youtube_url(url) is ok


def _session(**kw):
    base = dict(url="https://youtu.be/x", title="<b>Title</b> & co", uploader="<i>me</i>", duration=125, heights=[360, 720])
    return bot.VideoSession(**{**base, **kw})


def test_caption_escapes_html():
    text = bot._caption(_session(), "ok")
    assert "&lt;b&gt;Title&lt;/b&gt; &amp; co" in text
    assert "&lt;i&gt;me&lt;/i&gt;" in text
    assert "2:05" in text


def test_keyboard_offers_only_known_heights():
    data = [b.callback_data for row in bot._keyboard(_session()).inline_keyboard for b in row]
    assert data == ["dl|audio", "dl|360", "dl|720"]


def test_download_picks_final_file_and_ignores_parts(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            assert self.opts["max_filesize"] == bot.MAX_UPLOAD_BYTES
            assert self.opts["noplaylist"] is True
            (tmp_path / "media.mp4").write_bytes(b"x" * 10)
            (tmp_path / "media.f137.mp4.part").write_bytes(b"x" * 100)

    monkeypatch.setattr(bot, "YoutubeDL", FakeYDL)
    path = bot.download("https://youtu.be/x", str(tmp_path), 720)
    assert path.name == "media.mp4"


def test_download_without_output_raises(tmp_path, monkeypatch):
    class TooBig:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def download(self, urls): pass  # yt-dlp пропускает файл > max_filesize и ничего не пишет

    monkeypatch.setattr(bot, "YoutubeDL", TooBig)
    with pytest.raises(FileNotFoundError):
        bot.download("https://youtu.be/x", str(tmp_path), None)


def _callback(user_id, data):
    message = SimpleNamespace(answer=AsyncMock(return_value=SimpleNamespace(delete=AsyncMock())),
                              answer_video=AsyncMock(), answer_audio=AsyncMock())
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id), data=data, message=message, answer=AsyncMock())


@pytest.mark.asyncio
async def test_unknown_format_is_rejected(monkeypatch):
    """Строка формата из callback не уходит в yt-dlp как есть."""
    bot.sessions[1] = _session()
    called = AsyncMock()
    monkeypatch.setattr(bot, "download", called)
    cb = _callback(1, "dl|bestvideo[height<=4320]")
    await bot.handle_choice(cb)
    cb.answer.assert_awaited_with("Неизвестный формат.", show_alert=True)
    called.assert_not_called()


@pytest.mark.asyncio
async def test_successful_download_sends_video_and_cleans_temp(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "DOWNLOAD_ROOT", tmp_path)

    def fake_download(url, target_dir, height):
        p = Path(target_dir) / "media.mp4"
        p.write_bytes(b"video")
        assert height == 720
        return p

    monkeypatch.setattr(bot, "download", fake_download)
    bot.sessions[2] = _session()
    cb = _callback(2, "dl|720")
    await bot.handle_choice(cb)
    cb.message.answer_video.assert_awaited_once()
    assert list(tmp_path.iterdir()) == []  # временная папка удалена
    assert 2 not in bot.sessions and 2 not in bot.active_users


@pytest.mark.asyncio
async def test_one_active_download_per_user():
    bot.sessions[3] = _session()
    bot.active_users.add(3)
    try:
        cb = _callback(3, "dl|360")
        await bot.handle_choice(cb)
        cb.answer.assert_awaited_with("Дождитесь окончания предыдущей загрузки.", show_alert=True)
    finally:
        bot.active_users.discard(3)


@pytest.mark.asyncio
async def test_long_video_refused(monkeypatch):
    monkeypatch.setattr(bot, "fetch_info", lambda url: (_session(duration=bot.MAX_DURATION_MIN * 60 + 1), None))
    message = SimpleNamespace(text="https://youtu.be/x", from_user=SimpleNamespace(id=4), chat=SimpleNamespace(id=4),
                              bot=SimpleNamespace(send_chat_action=AsyncMock()), answer=AsyncMock(),
                              answer_photo=AsyncMock())
    await bot.handle_link(message)
    assert "длиннее" in message.answer.await_args.args[0]
    assert 4 not in bot.sessions


def test_download_runs_in_thread_not_event_loop():
    """Проверка по исходнику: тяжёлые вызовы идут через asyncio.to_thread."""
    src = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert "asyncio.to_thread(fetch_info" in src and "asyncio.to_thread(download" in src
    assert asyncio.iscoroutinefunction(bot.handle_choice)

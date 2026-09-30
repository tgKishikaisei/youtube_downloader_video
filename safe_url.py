"""Проверка ссылок на YouTube.

Принимается только http(s)-ссылка с хостом YouTube. Проверка подстроки
`"youtube.com" in url` пропустила бы `https://evil.com/?youtube.com` и строки
вида `--exec=... youtube.com`, которые yt-dlp принял бы за опции.
"""
from urllib.parse import urlparse

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be",
}


def is_youtube_url(url: str) -> bool:
    if not url or len(url) > 300 or any(ch.isspace() for ch in url):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in YOUTUBE_HOSTS

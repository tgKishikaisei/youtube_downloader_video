# YouTube Downloader Bot for Telegram
- This is a Telegram bot that enables users to download videos and audio from YouTube. It provides the following features:

- Fetches video information, including title, author, and duration.
- Displays available video and audio formats with resolutions and approximate file sizes.
- Automatically handles files larger than 50 MB by offering smaller resolutions.
- Sends videos in the correct aspect ratio (16:9), ensuring compatibility with Telegram's media viewer.
- Provides audio-only downloads with customizable quality.

---

## Features:
- Download Options:

- Users can download videos in various resolutions.
- Audio-only downloads are supported (MP3 format).

## Smart File Management:

- Automatically selects smaller file sizes if the video exceeds Telegram's 50 MB limit.
- Removes duplicate formats and excludes those with unknown sizes.

## User-Friendly:

- Inline buttons for selecting resolutions.
- Sends files with informative captions, including video title, author, and duration.

## Technology Stack:

- Python 3
- aiogram for Telegram bot interaction.
- yt-dlp for extracting and downloading YouTube videos.
- ffmpeg for audio conversion.

---

# How to Use:

### Clone the repository:
    
    git clone https://github.com/your-username/telegram-youtube-downloader.git

### Install dependencies:
    
    pip install -r requirements.txt

### Set up your .env file with your Telegram bot token:
- makefile
- TELEGRAM_BOT_TOKEN=your-telegram-bot-token

### Run the bot:
    python bot.py



# Future improvements:

- I will add support for downloading videos from other platforms (for example, Vimeo, Facebook).
- I am integrating notifications about the download progress.
- I will enable cloud storage options (e.g. Google Drive, Dropbox) for larger files.
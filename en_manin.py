import os
import asyncio
import re
import requests
import uuid
from aiogram import Bot, Dispatcher, types, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

# -------------------
# YOUR TELEGRAM BOT TOKEN
# -------------------
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")

# Initialize the bot and dispatcher
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

# Temporary storage for user data
user_data = {}

@router.message(Command(commands=["start"]))
async def start(message: types.Message):
    """
    Command /start.
    Displays a welcome message and asks the user to send a YouTube link.
    """
    await message.answer(
        "Hello! Send me a YouTube video link, and I'll show you the available download formats."
    )

@router.message()
async def handle_youtube_link(message: types.Message):
    """
    Handles user messages. If the message contains a YouTube link,
    the bot retrieves video information, generates buttons to select quality,
    and provides an option to download audio only.
    """
    url = message.text.strip()

    # Check if the message contains a valid YouTube link
    if "youtube.com" not in url and "youtu.be" not in url:
        await message.answer("Please send a valid YouTube link.")
        return

    try:
        # Notify the user that the bot is typing
        await bot.send_chat_action(message.chat.id, "typing")

        # Retrieve video information
        video_info = get_video_info(url)
        title = video_info['title']
        author = video_info['uploader']
        duration = video_info['duration']
        thumbnail = video_info['thumbnail']
        formats = video_info['formats']

        # Store necessary data
        user_data[message.from_user.id] = {
            "url": url,
            "formats": formats
        }

        # Download the video thumbnail
        thumbnail_path = f"temp/{uuid.uuid4()}.jpg"
        os.makedirs("temp", exist_ok=True)
        download_thumbnail(thumbnail, thumbnail_path)

        # Generate description text
        duration_min = duration // 60
        duration_sec = duration % 60
        description = (
            f"<b>{title}</b>\n"
            f"🎥 <a href='{url}'>Video Link</a>\n"
            f"👤 Author: {author}\n"
            f"⏳ Duration: {duration_min}:{duration_sec:02d}\n\n"
            "Select a quality to download or choose audio-only:"
        )

        # Generate buttons
        buttons = []
        # Button to download audio-only
        buttons.append([
            InlineKeyboardButton(
                text="🎧 Audio Only",
                callback_data="audio_only"
            )
        ])

        # Buttons for video formats, removing duplicates
        unique_formats = {}
        for fmt in formats:
            res = fmt["resolution"]
            size = fmt.get("size")
            if not size or res in unique_formats:  # Skip formats with unknown size or duplicates
                continue
            unique_formats[res] = size
            text_button = f"{res} / ~{size} MB"
            buttons.append([
                InlineKeyboardButton(
                    text=text_button,
                    callback_data=f"format|{fmt['format_id']}"
                )
            ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        # Determine the size of the downloaded thumbnail and decide how to send it
        thumbnail_size = os.path.getsize(thumbnail_path)
        # 10 MB = 10 * 1024 * 1024 = 10485760
        # If the thumbnail exceeds 10MB, send it as a document
        if thumbnail_size > 10 * 1024 * 1024:
            file = types.FSInputFile(thumbnail_path, chunk_size=65536)
            await bot.send_document(
                chat_id=message.chat.id,
                document=file,
                caption=description,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            photo = types.FSInputFile(thumbnail_path, chunk_size=65536)
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=description,
                parse_mode="HTML",
                reply_markup=keyboard
            )

        # Remove the temporary thumbnail file
        os.remove(thumbnail_path)

    except Exception as e:
        await message.answer(f"Error processing video: {e}")

@router.callback_query(lambda c: c.data.startswith("format|") or c.data == "audio_only")
async def handle_format(callback_query: types.CallbackQuery):
    """
    Handles format selection and sends the requested video or audio file with description.
    If the user selects "audio_only," only audio is downloaded.
    If the video size exceeds 50 MB, sends the next available smaller resolution.
    Adjusts video to match ideal YouTube-like preview proportions.
    """
    user_id = callback_query.from_user.id
    if user_id not in user_data:
        await callback_query.message.answer("Video information not found. Please resend the link.")
        return

    video_url = user_data[user_id]["url"]

    await bot.send_chat_action(callback_query.message.chat.id, "typing")

    # Delete the previous message with buttons
    try:
        await callback_query.message.delete()
    except Exception as e:
        print(f"Error deleting message: {e}")

    # Notify user about download status
    status_message = await callback_query.message.answer("Downloading... Please wait.")

    audio_only = (callback_query.data == "audio_only")

    try:
        if audio_only:
            # Download audio-only
            file_path = download_audio(video_url, "audio")
        else:
            # Download video
            format_id = callback_query.data.split("|")[1]
            file_path = download_video(video_url, format_id, "video")

            # If the file size exceeds 50 MB, download a smaller resolution
            while os.path.getsize(file_path) > 50 * 1024 * 1024:
                os.remove(file_path)  # Remove the oversized file
                smaller_format = get_smaller_format(format_id, user_data[user_id]["formats"])
                if not smaller_format:
                    raise Exception("No smaller resolution available.")
                format_id = smaller_format["format_id"]
                file_path = download_video(video_url, format_id, "video")

        if file_path and os.path.exists(file_path):
            # Check the size of the downloaded file
            file_size_bytes = os.path.getsize(file_path)

            # Generate description text
            video_info = get_video_info(video_url)
            title = video_info['title']
            author = video_info['uploader']
            duration = video_info['duration']
            duration_min = duration // 60
            duration_sec = duration % 60
            description = (
                f"<b>{title}</b>\n"
                f"🎥 <a href='{video_url}'>Video Link</a>\n"
                f"👤 Author: {author}\n"
                f"⏳ Duration: {duration_min}:{duration_sec:02d}\n"
            )

            # Send the file ensuring the ideal aspect ratio (YouTube-style preview)
            if audio_only:
                await bot.send_audio(
                    chat_id=callback_query.message.chat.id,
                    audio=types.FSInputFile(file_path, chunk_size=65536),
                    caption=description,
                    parse_mode="HTML"
                )
            else:
                await bot.send_video(
                    chat_id=callback_query.message.chat.id,
                    video=types.FSInputFile(file_path, chunk_size=65536),
                    caption=description,
                    parse_mode="HTML",
                    supports_streaming=True,
                    width=1920,
                    height=1080  # Ideal aspect ratio for YouTube previews
                )

            os.remove(file_path)
        else:
            await callback_query.message.answer("Failed to download the file.")

    except Exception as e:
        await callback_query.message.answer(f"Download error: {e}")

    finally:
        try:
            await status_message.delete()
        except Exception as e:
            print(f"Failed to delete download status message: {e}")

        if user_id in user_data:
            del user_data[user_id]

def get_video_info(url: str):
    with YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = []
    for fmt in info["formats"]:
        if fmt.get("vcodec") != "none":
            resolution = fmt.get("resolution", "video")
            size_mb = round(fmt["filesize"] / (1024 * 1024), 1) if fmt.get("filesize") else None
            formats.append({
                "format_id": f"{fmt['format_id']}+bestaudio",
                "resolution": resolution,
                "size": size_mb
            })

    return {
        "title": info.get("title", "Untitled"),
        "uploader": info.get("uploader", "Unknown"),
        "duration": info.get("duration", 0),
        "thumbnail": info.get("thumbnail"),
        "formats": formats
    }

def get_smaller_format(current_format_id, formats):
    """
    Finds the next smaller format based on resolution or size.
    """
    current_index = next((i for i, fmt in enumerate(formats) if fmt["format_id"] == current_format_id), None)
    if current_index is None or current_index + 1 >= len(formats):
        return None
    return formats[current_index + 1]

def download_video(url: str, format_id: str, title: str):
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)
    safe_title = sanitize_filename(title)
    output_path = os.path.join(output_dir, f"{safe_title}.mp4")

    try:
        ydl_opts = {
            "format": format_id,
            "merge_output_format": "mp4",
            "outtmpl": output_path,
            "quiet": True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(output_path):
            raise FileNotFoundError("The file was not created.")

        return output_path

    except Exception as e:
        print(f"Video download error: {e}")
        return None

def download_audio(url: str, title: str):
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)
    safe_title = sanitize_filename(title)
    output_path_template = os.path.join(output_dir, f"{safe_title}.%(ext)s")

    try:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_path_template,
            "quiet": False,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192"
                }
            ],
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        final_path = os.path.join(output_dir, f"{safe_title}.mp3")

        if not os.path.exists(final_path):
            raise FileNotFoundError("Audio file was not created. Make sure ffmpeg is installed.")

        return final_path

    except Exception as e:
        print(f"Audio download error: {e}")
        return None

def download_thumbnail(url: str, output_path: str):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
    else:
        raise Exception("Failed to download thumbnail.")

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', filename)

async def main():
    dp.include_router(router)
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())


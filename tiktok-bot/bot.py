import os
import traceback
import glob as globmod
import telebot
from telebot import types
import yt_dlp
from database import init_db, add_user, increment_downloads, get_user, get_stats

TOKEN = os.environ.get('TOKEN')
bot = telebot.TeleBot(TOKEN)

init_db()

DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'geo_bypass': True,
    'nocheckcertificate': True,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 Chrome/96.0.4664.45 Mobile Safari/537.36',
    },
    'extractor_args': {
        'youtube': {'player_client': ['android']},
        'tiktok': {'api_hostname': 'api22-normal-c-useast2a.tiktokv.com'},
    },
}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    add_user(user.id, user.username, user.first_name)
    bot.reply_to(
        message,
        "Привет! Я мощный бот-загрузчик.\n\n"
        "Отправь мне ссылку на TikTok (видео или фото-галерею), YouTube или Shorts, "
        "и я скачаю контент для тебя!"
    )

@bot.message_handler(commands=['stats'])
def send_stats(message):
    stats = get_stats()
    user = get_user(message.from_user.id)
    user_downloads = user["download_count"] if user else 0
    bot.reply_to(
        message,
        f"Статистика бота:\n"
        f"Пользователей: {stats['total_users']}\n"
        f"Всего скачиваний: {stats['total_downloads']}\n"
        f"Твои скачивания: {user_downloads}"
    )

def find_downloaded_file(video_id):
    pattern = os.path.join(DOWNLOAD_DIR, f"{video_id}.*")
    matches = globmod.glob(pattern)
    matches = [f for f in matches if not f.endswith('.part')]
    return matches[0] if matches else None

@bot.message_handler(func=lambda message: True)
def handle_link(message):
    user = message.from_user
    add_user(user.id, user.username, user.first_name)
    url = message.text.strip()

    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "Пожалуйста, отправь корректную ссылку.")
        return

    status_msg = bot.reply_to(message, "Обрабатываю ссылку, подожди немного...")

    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'best[ext=mp4]/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'merge_output_format': 'mp4',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get('id', '')
            filename = find_downloaded_file(video_id)

            if filename:
                bot.edit_message_text(
                    "Отправляю видео в Telegram...",
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id
                )

                encoded_url = url.replace('_', '-_-')
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton(
                    text="Скачать аудио (MP3)",
                    callback_data=f"audio|{encoded_url}"
                ))

                with open(filename, 'rb') as video:
                    bot.send_video(
                        message.chat.id,
                        video,
                        reply_markup=keyboard,
                        caption="Вот твое видео без водяного знака!"
                    )

                increment_downloads(message.from_user.id)
                bot.delete_message(status_msg.chat.id, status_msg.message_id)
                os.remove(filename)
                return

            images = info.get('images', [])
            if not images and 'entries' in info:
                for entry in info.get('entries', []):
                    if entry and entry.get('images'):
                        images = entry['images']
                        break

            if images:
                bot.edit_message_text(
                    "Обнаружена фото-галерея! Скачиваю фотографии...",
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id
                )
                media_group = [types.InputMediaPhoto(img_url) for img_url in images[:9]]
                if media_group:
                    bot.send_media_group(message.chat.id, media_group)
                bot.delete_message(status_msg.chat.id, status_msg.message_id)
                return

    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_DIR}/audio_%(id)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }


@bot.callback_query_handler(func=lambda call: call.data.startswith('audio|'))
def handle_audio_callback(call):
    encoded_url = call.data.split('|', 1)[1]
    original_url = encoded_url.replace('-_-', '_')

    bot.answer_callback_query(call.id, "Извлекаю аудиодорожку...")

    ydl_opts = {
            **BASE_YDL_OPTS,
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_DIR}/audio_%(id)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(original_url, download=True)
            video_id = info.get('id', 'unknown')
            mp3_files = globmod.glob(f"{DOWNLOAD_DIR}/*.mp3")
            audio_filename = mp3_files[0] if mp3_files else None

            if audio_filename and os.path.exists(audio_filename):
                with open(audio_filename, 'rb') as audio:
                    bot.send_audio(call.message.chat.id, audio, caption="Вот твоя аудиодорожка!")
                increment_downloads(call.from_user.id)
                os.remove(audio_filename)
            else:
                bot.send_message(call.message.chat.id, "Не удалось найти или извлечь аудиофайл.")
    except Exception as e:
        print(f"Ошибка аудио: {e}")
        print(traceback.format_exc())
        bot.send_message(call.message.chat.id, "Ошибка при конвертации в MP3. Попробуйте другую ссылку.")

if __name__ == '__main__':
    bot.polling(none_stop=True)

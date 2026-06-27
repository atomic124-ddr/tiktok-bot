import os
import traceback
import glob as globmod
import telebot
from telebot import types
import yt_dlp

TOKEN = os.environ.get('TOKEN')
bot = telebot.TeleBot(TOKEN)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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
    bot.reply_to(message, "Привет! Отправь ссылку на TikTok, Instagram или YouTube Shorts — скачаю видео!")

@bot.message_handler(func=lambda message: True)
def handle_link(message):
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "Отправь корректную ссылку.")
        return

    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку...")

    for f in globmod.glob(f'{DOWNLOAD_DIR}/*'):
        try:
            os.remove(f)
        except:
            pass

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

            files = globmod.glob(f'{DOWNLOAD_DIR}/{video_id}.*')
            files = [f for f in files if not f.endswith('.part')]
            filename = files[0] if files else None

            if filename and os.path.exists(filename):
                encoded_url = url.replace('_', '-_-')
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton(
                    text="🎵 Скачать аудио (MP3)",
                    callback_data=f"audio|{encoded_url}"
                ))
                with open(filename, 'rb') as video:
                    bot.send_video(
                        message.chat.id,
                        video,
                        reply_markup=keyboard,
                        caption="Вот твоё видео!"
                    )
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
                media_group = [types.InputMediaPhoto(img_url) for img_url in images[:9]]
                if media_group:
                    bot.send_media_group(message.chat.id, media_group)
                    bot.delete_message(status_msg.chat.id, status_msg.message_id)
                    return

            bot.edit_message_text("❌ Не удалось скачать.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)

    except Exception as e:
        print(traceback.format_exc())
        try:
            bot.edit_message_text("❌ Ошибка. Возможно контент приватный.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('audio|'))
def handle_audio_callback(call):
    encoded_url = call.data.split('|', 1)[1]
    original_url = encoded_url.replace('-_-', '_')
    bot.answer_callback_query(call.id, "⏳ Извлекаю аудио...")

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
            ydl.extract_info(original_url, download=True)
            mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/*.mp3')
            if mp3_files:
                with open(mp3_files[0], 'rb') as audio:
                    bot.send_audio(call.message.chat.id, audio, caption="🎵 Вот твоя аудиодорожка!")
                os.remove(mp3_files[0])
            else:
                bot.send_message(call.message.chat.id, "❌ Не удалось найти MP3 файл.")
    except Exception as e:
        print(traceback.format_exc())
        bot.send_message(call.message.chat.id, "❌ Ошибка при конвертации в MP3.")

if __name__ == '__main__':
    bot.polling(none_stop=True)

import os
import re
import json
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

URL_CACHE_FILE = f'{DOWNLOAD_DIR}/url_cache.json'

def cleanup_dir():
    for f in globmod.glob(f'{DOWNLOAD_DIR}/*'):
        try:
            os.remove(f)
        except:
            pass

def load_url_cache():
    if os.path.exists(URL_CACHE_FILE):
        try:
            with open(URL_CACHE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}

def save_url_cache(cache):
    with open(URL_CACHE_FILE, 'w') as f:
        json.dump(cache, f)

def cache_url(short_id, url):
    cache = load_url_cache()
    cache[short_id] = url
    if len(cache) > 100:
        keys = list(cache.keys())
        for k in keys[:50]:
            del cache[k]
    save_url_cache(cache)

def get_cached_url(short_id):
    return load_url_cache().get(short_id)

def is_valid_url(url):
    return re.match(r'^https?://\S+$', url) is not None

def is_instagram(url):
    return 'instagram.com' in url

def get_ig_cookies_opts():
    ig_cookies = os.environ.get('INSTAGRAM_COOKIES')
    if ig_cookies:
        cookies_path = '/tmp/ig_cookies.txt'
        if not os.path.exists(cookies_path):
            with open(cookies_path, 'w') as f:
                f.write(ig_cookies)
        return {'cookiefile': cookies_path}
    return {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Отправь ссылку на TikTok, Instagram или YouTube Shorts — скачаю видео!")

@bot.message_handler(func=lambda message: True)
def handle_link(message):
    url = message.text.strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Отправь корректную ссылку.")
        return

    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку...")
    cleanup_dir()

    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'best[ext=mp4]/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'merge_output_format': 'mp4',
    }
    ydl_opts.update(get_ig_cookies_opts())

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

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

            ydl.download([url])

        video_id = info.get('id', '')
        files = globmod.glob(f'{DOWNLOAD_DIR}/{video_id}.*')
        files = [f for f in files if not f.endswith('.part')]
        filename = files[0] if files else None

        if not filename or not os.path.exists(filename):
            all_files = [f for f in globmod.glob(f'{DOWNLOAD_DIR}/*') if not f.endswith('.part') and not f.endswith('.json') and f != URL_CACHE_FILE]
            if all_files:
                filename = max(all_files, key=os.path.getmtime)

        if filename and os.path.exists(filename):
            short_id = video_id[:20]
            cache_url(short_id, url)

            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton(
                text="🎵 Скачать аудио (MP3)",
                callback_data=f"audio|{short_id}"
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

        bot.edit_message_text("❌ Не удалось скачать.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)

    except Exception as e:
        print(traceback.format_exc())
        try:
            bot.edit_message_text("❌ Ошибка. Возможно контент приватный.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('audio|'))
def handle_audio_callback(call):
    short_id = call.data.split('|', 1)[1]
    original_url = get_cached_url(short_id)

    if not original_url or not is_valid_url(original_url):
        bot.answer_callback_query(call.id, "❌ Ссылка устарела. Отправь заново.")
        return

    bot.answer_callback_query(call.id, "⏳ Извлекаю аудио...")
    cleanup_dir()

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
    ydl_opts.update(get_ig_cookies_opts())

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(original_url, download=True)

        audio_id = info.get('id', '')
        mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/audio_{audio_id}.*')
        if not mp3_files:
            mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/*.mp3')

        if mp3_files:
            with open(mp3_files[0], 'rb') as audio:
                bot.send_audio(call.message.chat.id, audio, caption="🎵 Вот твоя аудиодорожка!")
            os.remove(mp3_files[0])
        else:
            bot.send_message(call.message.chat.id, "❌ Не удалось найти MP3.")
    except Exception as e:
        print(traceback.format_exc())
        bot.send_message(call.message.chat.id, "❌ Ошибка при конвертации в MP3.")

if __name__ == '__main__':
    bot.polling(none_stop=True)

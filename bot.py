import os
import re
import json
import time
import traceback
import glob as globmod
import requests as http_requests
import telebot
from telebot import types
import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

TOKEN = os.environ.get('TOKEN')
PROXY_URL = os.environ.get('PROXY_URL', '')
bot = telebot.TeleBot(TOKEN)

DOWNLOAD_DIR = "downloads"
COOKIES_DIR = "cookies"
URL_CACHE_FILE = f'{DOWNLOAD_DIR}/url_cache.json'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(COOKIES_DIR, exist_ok=True)

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'geo_bypass': True,
    'nocheckcertificate': True,
    'socket_timeout': 30,
    'retries': 3,
    'fragment_retries': 3,
}

if PROXY_URL:
    BASE_YDL_OPTS['proxy'] = PROXY_URL

def cleanup_dir():
    for f in globmod.glob(f'{DOWNLOAD_DIR}/*'):
        if os.path.basename(f) == 'url_cache.json':
            continue
        try:
            os.remove(f)
        except:
            pass

def save_url_cache(video_id, url):
    cache = {}
    if os.path.exists(URL_CACHE_FILE):
        try:
            with open(URL_CACHE_FILE) as f:
                cache = json.load(f)
        except:
            pass
    cache[video_id] = url
    with open(URL_CACHE_FILE, 'w') as f:
        json.dump(cache, f)

def get_cached_url(video_id):
    if os.path.exists(URL_CACHE_FILE):
        try:
            with open(URL_CACHE_FILE) as f:
                return json.load(f).get(video_id)
        except:
            pass
    return None

def is_valid_url(url):
    return re.match(r'^https?://\S+$', url) is not None

def is_instagram(url):
    return 'instagram.com' in url

def is_tiktok(url):
    return 'tiktok.com' in url

def is_youtube(url):
    return 'youtube.com' in url or 'youtu.be' in url

def get_cookies_file(platform):
    pattern = os.path.join(COOKIES_DIR, f'{platform}*.txt')
    files = sorted(globmod.glob(pattern))
    return files[0] if files else None

def _sc_to_pk(sc):
    A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    pk = 0
    for c in sc:
        pk = pk * 64 + A.index(c)
    return pk

def _get_ig_session():
    cookies_file = get_cookies_file('instagram')
    if not cookies_file:
        return None
    ig_cookies = {}
    with open(cookies_file) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.strip().split('\t')
            if len(parts) >= 7:
                ig_cookies[parts[5]] = parts[6]
    s = http_requests.Session()
    for k, v in ig_cookies.items():
        s.cookies.set(k, v, domain='.instagram.com')
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
    s.headers.update({
        'User-Agent': ua,
        'X-IG-App-ID': '936619743392459',
        'X-ASBD-ID': '198387',
        'X-IG-WWW-Claim': '0',
        'Origin': 'https://www.instagram.com',
        'Accept': '*/*',
    })
    r = s.get('https://www.instagram.com/', timeout=15)
    csrf = s.cookies.get('csrftoken', '')
    s.headers['X-CSRFToken'] = csrf
    s.headers['X-Requested-With'] = 'XMLHttpRequest'
    return s

def download_ig_direct(url):
    match = re.search(r'instagram\.com/(?:reel|p)/([A-Za-z0-9_-]+)', url)
    if not match:
        print(f"[DEBUG] IG: Invalid URL format: {url}")
        return None, None, "Invalid Instagram URL"
    shortcode = match.group(1)
    print(f"[DEBUG] IG: shortcode={shortcode}")
    pk = _sc_to_pk(shortcode)
    s = _get_ig_session()
    if not s:
        return None, None, "No Instagram cookies found"
    time.sleep(2)
    print(f"[DEBUG] IG: Calling API media/{pk}/info/")
    r = s.get(f'https://www.instagram.com/api/v1/media/{pk}/info/', timeout=15)
    print(f"[DEBUG] IG: status={r.status_code} content-type={r.headers.get('content-type','?')}")
    if r.status_code != 200:
        return None, None, f"Instagram API error {r.status_code}"
    data = r.json()
    items = data.get('items', [])
    if not items:
        print(f"[DEBUG] IG: No items in response")
        return None, None, "Post not found or private"
    item = items[0]
    if item.get('video_versions'):
        v = item['video_versions'][0]
        vr = s.get(v['url'], timeout=30)
        if vr.status_code == 200:
            filename = f'{DOWNLOAD_DIR}/{shortcode}.mp4'
            with open(filename, 'wb') as f:
                f.write(vr.content)
            return filename, shortcode, None
        return None, None, f"Video download failed {vr.status_code}"
    images = item.get('image_versions2', {}).get('candidates', [])
    if images:
        return None, images[0]['url'], None
    return None, None, "Unsupported media type"

def get_ydl_opts_for_url(url, audio_only=False):
    opts = {**BASE_YDL_OPTS}

    if is_instagram(url):
        cookies = get_cookies_file('instagram')
        if cookies:
            opts['cookiefile'] = cookies
        opts['impersonate'] = ImpersonateTarget(client='chrome', os='windows', os_version='10')
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }
        if audio_only:
            opts['format'] = 'bestaudio/best'
        else:
            opts['format'] = 'best[height<=720][ext=mp4]/best[ext=mp4]/best[height<=720]/best'

    elif is_tiktok(url):
        cookies = get_cookies_file('tiktok')
        if cookies:
            opts['cookiefile'] = cookies
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }
        opts['extractor_args'] = {
            'tiktok': {'api_hostname': 'api22-normal-c-useast2a.tiktokv.com'},
        }
        if audio_only:
            opts['format'] = 'bestaudio/best'
        else:
            opts['format'] = 'best[ext=mp4]/best'

    elif is_youtube(url):
        cookies = get_cookies_file('youtube')
        if cookies:
            opts['cookiefile'] = cookies
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }
        opts['js_runtimes'] = {'node': {}}
        if audio_only:
            opts['format'] = 'bestaudio/best'
        else:
            opts['format'] = 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[ext=mp4]/best'

    else:
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 Chrome/96.0.4664.45 Mobile Safari/537.36',
        }
        if audio_only:
            opts['format'] = 'bestaudio/best'
        else:
            opts['format'] = 'best[ext=mp4]/best'

    if audio_only:
        opts['outtmpl'] = f'{DOWNLOAD_DIR}/audio_%(id)s.%(ext)s'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        opts['outtmpl'] = f'{DOWNLOAD_DIR}/%(id)s.%(ext)s'
        opts['merge_output_format'] = 'mp4'

    return opts

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Отправь ссылку на TikTok, Instagram или YouTube — скачаю видео!")

@bot.message_handler(func=lambda message: True)
def handle_link(message):
    url = message.text.strip()
    print(f"[DEBUG] handle_link called with: {url}")
    print(f"[DEBUG] is_instagram={is_instagram(url)} is_tiktok={is_tiktok(url)} is_youtube={is_youtube(url)}")
    if not is_valid_url(url):
        bot.reply_to(message, "Отправь корректную ссылку.")
        return

    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку...")
    cleanup_dir()

    ydl_opts = get_ydl_opts_for_url(url, audio_only=False)
    print(f"[DEBUG] ydl_opts: {ydl_opts}")

    try:
        print(f"[DEBUG] Starting yt-dlp download...")
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
            print(f"[DEBUG] Download complete")

        video_id = info.get('id', '')
        files = globmod.glob(f'{DOWNLOAD_DIR}/{video_id}.*')
        files = [f for f in files if not f.endswith('.part')]
        filename = files[0] if files else None
        print(f"[DEBUG] video_id={video_id} files={files} filename={filename}")

        if not filename or not os.path.exists(filename):
            all_files = [f for f in globmod.glob(f'{DOWNLOAD_DIR}/*')
                        if not f.endswith('.part') and not f.endswith('.json')
                        and os.path.basename(f) != 'url_cache.json']
            if all_files:
                filename = max(all_files, key=os.path.getmtime)

        if filename and os.path.exists(filename):
            save_url_cache(video_id, url)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton(
                text="🎵 Скачать аудио (MP3)",
                callback_data=f"audio|{video_id}"
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
        print(f"[DEBUG] yt-dlp error: {e}")
        traceback.print_exc()

    if is_youtube(url):
        print(f"[DEBUG] Retrying YouTube with android fallback...")
        try:
            retry_opts = get_ydl_opts_for_url(url, audio_only=False)
            retry_opts['extractor_args'] = {
                'youtube': {'player_client': ['android']},
            }
            retry_opts['format'] = 'best[ext=mp4]/best'
            with yt_dlp.YoutubeDL(retry_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info.get('id', '')
                files = globmod.glob(f'{DOWNLOAD_DIR}/{video_id}.*')
                files = [f for f in files if not f.endswith('.part')]
                filename = files[0] if files else None

                if not filename or not os.path.exists(filename):
                    all_files = [f for f in globmod.glob(f'{DOWNLOAD_DIR}/*')
                                if not f.endswith('.part') and not f.endswith('.json')
                                and os.path.basename(f) != 'url_cache.json']
                    if all_files:
                        filename = max(all_files, key=os.path.getmtime)

                if filename and os.path.exists(filename):
                    save_url_cache(video_id, url)
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.add(types.InlineKeyboardButton(
                        text="🎵 Скачать аудио (MP3)",
                        callback_data=f"audio|{video_id}"
                    ))
                    with open(filename, 'rb') as video:
                        bot.send_video(message.chat.id, video, reply_markup=keyboard, caption="Вот твоё видео!")
                    bot.delete_message(status_msg.chat.id, status_msg.message_id)
                    os.remove(filename)
                    return
        except Exception as e2:
            print(f"[DEBUG] YouTube retry error: {e2}")
            traceback.print_exc()

    if is_instagram(url):
        print(f"[DEBUG] Trying Instagram direct API...")
        try:
            bot.edit_message_text("🔄 Пробую альтернативный способ...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            filename, image_url, error = download_ig_direct(url)
            if filename and os.path.exists(filename):
                video_id = os.path.basename(filename).replace('.mp4', '')
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton(
                    text="🎵 Скачать аудио (MP3)",
                    callback_data=f"audio|{video_id}"
                ))
                with open(filename, 'rb') as video:
                    bot.send_video(message.chat.id, video, reply_markup=keyboard, caption="Вот твоё видео!")
                bot.delete_message(status_msg.chat.id, status_msg.message_id)
                os.remove(filename)
                return
            if image_url:
                bot.send_photo(message.chat.id, image_url)
                bot.delete_message(status_msg.chat.id, status_msg.message_id)
                return
            bot.edit_message_text(f"❌ {error or 'Не удалось скачать.'}", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        except Exception as e2:
            print(traceback.format_exc())
            try:
                bot.edit_message_text("❌ Ошибка. Возможно контент приватный.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            except:
                pass
    else:
        try:
            bot.edit_message_text("❌ Ошибка. Возможно контент приватный.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('audio|'))
def handle_audio_callback(call):
    video_id = call.data.split('|', 1)[1]

    if not video_id or len(video_id) < 3:
        bot.answer_callback_query(call.id, "❌ Некорректный ID.")
        return

    bot.answer_callback_query(call.id, "⏳ Извлекаю аудио...")
    cleanup_dir()

    # Get original URL from cache
    original_url = get_cached_url(video_id)

    # Try YouTube first
    try:
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = get_ydl_opts_for_url(yt_url, audio_only=True)
        ydl_opts['outtmpl'] = f'{DOWNLOAD_DIR}/audio_{video_id}.%(ext)s'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(yt_url, download=True)

        mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/audio_{video_id}.*')
        if not mp3_files:
            mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/*.mp3')

        if mp3_files:
            with open(mp3_files[0], 'rb') as audio:
                bot.send_audio(call.message.chat.id, audio, caption="🎵 Вот твоя аудиодорожка!")
            os.remove(mp3_files[0])
            return
    except Exception:
        pass

    # Try cached original URL
    if original_url:
        try:
            ydl_opts = get_ydl_opts_for_url(original_url, audio_only=True)
            ydl_opts['outtmpl'] = f'{DOWNLOAD_DIR}/audio_{video_id}.%(ext)s'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(original_url, download=True)

            mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/audio_{video_id}.*')
            if not mp3_files:
                mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/*.mp3')

            if mp3_files:
                with open(mp3_files[0], 'rb') as audio:
                    bot.send_audio(call.message.chat.id, audio, caption="🎵 Вот твоя аудиодорожка!")
                os.remove(mp3_files[0])
                return
        except Exception:
            pass

    # Try TikTok fallback
    try:
        tiktok_url = f"https://www.tiktok.com/video/{video_id}"
        ydl_opts = get_ydl_opts_for_url(tiktok_url, audio_only=True)
        ydl_opts['outtmpl'] = f'{DOWNLOAD_DIR}/audio_{video_id}.%(ext)s'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(tiktok_url, download=True)

        mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/audio_{video_id}.*')
        if not mp3_files:
            mp3_files = globmod.glob(f'{DOWNLOAD_DIR}/*.mp3')

        if mp3_files:
            with open(mp3_files[0], 'rb') as audio:
                bot.send_audio(call.message.chat.id, audio, caption="🎵 Вот твоя аудиодорожка!")
            os.remove(mp3_files[0])
            return
    except Exception:
        pass

    # Try Instagram direct API
    try:
        filename, image_url, error = download_ig_direct(f'https://www.instagram.com/reel/{video_id}/')
        if filename and os.path.exists(filename):
            import subprocess
            mp3_path = f'{DOWNLOAD_DIR}/audio_{video_id}.mp3'
            subprocess.run([
                'ffmpeg', '-i', filename, '-vn', '-acodec', 'libmp3lame',
                '-q:a', '2', '-y', mp3_path
            ], capture_output=True, timeout=30)

            if os.path.exists(mp3_path):
                with open(mp3_path, 'rb') as audio:
                    bot.send_audio(call.message.chat.id, audio, caption="🎵 Вот твоя аудиодорожка!")
                os.remove(mp3_path)
                os.remove(filename)
                return
            else:
                os.remove(filename)
    except Exception:
        pass

    bot.send_message(call.message.chat.id, "❌ Ошибка при конвертации в MP3.")

if __name__ == '__main__':
    print("[BOT] Starting bot...")
    print(f"[BOT] Python: {__import__('sys').version}")
    print(f"[BOT] yt-dlp: {__import__('yt_dlp').version.__version__}")
    bot.polling(none_stop=True)

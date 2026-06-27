import os
import uuid
import random
import telebot
import yt_dlp
from config import TOKEN

bot = telebot.TeleBot(TOKEN)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Хранилище: message_id -> путь к видеофайлу
video_files = {}

# Кэш прокси
_proxy_cache = []


def fetch_proxies() -> list[str]:
    global _proxy_cache
    if _proxy_cache:
        return _proxy_cache

    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt",
    ]
    proxies = []
    for url in urls:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = resp.read().decode("utf-8", errors="ignore")
            for line in data.strip().splitlines():
                line = line.strip()
                if line and ":" in line:
                    proxies.append(f"http://{line}")
        except Exception:
            continue

    random.shuffle(proxies)
    _proxy_cache = proxies[:80]
    return _proxy_cache


def download_with_retry(url: str, base_opts: dict) -> str:
    filename = str(uuid.uuid4())
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    # Сначала пробуем без прокси
    opts = {**base_opts, "outtmpl": filepath, "format": "best"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(filename):
                return os.path.join(DOWNLOAD_DIR, f)
    except yt_dlp.utils.DownloadError as e:
        if "blocked" not in str(e).lower() and "proxy" not in str(e).lower():
            raise

    # Если заблокировано — перебираем прокси
    proxies = fetch_proxies()
    for proxy in proxies[:20]:
        opts = {**base_opts, "outtmpl": filepath, "format": "best", "proxy": proxy}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(filename):
                    return os.path.join(DOWNLOAD_DIR, f)
        except Exception:
            continue

    return None


def extract_audio_with_retry(video_path: str, base_opts: dict) -> str:
    audio_path = video_path.rsplit(".", 1)[0] + ".mp3"
    opts = {**base_opts, "outtmpl": audio_path, "format": "bestaudio/best"}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([video_path])
    except yt_dlp.utils.DownloadError as e:
        if "blocked" not in str(e).lower() and "proxy" not in str(e).lower():
            raise
        proxies = fetch_proxies()
        for proxy in proxies[:10]:
            opts_retry = {**opts, "proxy": proxy}
            try:
                with yt_dlp.YoutubeDL(opts_retry) as ydl:
                    ydl.download([video_path])
                break
            except Exception:
                continue

    for f in os.listdir(DOWNLOAD_DIR):
        if f.endswith(".mp3") and f.startswith(os.path.basename(video_path).rsplit(".", 1)[0]):
            return os.path.join(DOWNLOAD_DIR, f)
    if os.path.exists(audio_path):
        return audio_path
    return None


def is_tiktok_url(url: str) -> bool:
    return "tiktok.com" in url


def is_instagram_url(url: str) -> bool:
    return "instagram.com" in url


def download_video(url: str) -> str:
    return download_with_retry(url, {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
    })


def extract_audio(video_path: str) -> str:
    return extract_audio_with_retry(video_path, {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
    })


def extract_audio_from_url(url: str) -> str:
    filename = str(uuid.uuid4())
    audio_path = os.path.join(DOWNLOAD_DIR, filename + ".mp3")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
        "outtmpl": audio_path,
        "format": "bestaudio/best",
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        if "blocked" not in str(e).lower() and "proxy" not in str(e).lower():
            raise
        proxies = fetch_proxies()
        for proxy in proxies[:10]:
            opts_retry = {**opts, "proxy": proxy}
            try:
                with yt_dlp.YoutubeDL(opts_retry) as ydl:
                    ydl.download([url])
                break
            except Exception:
                continue

    for f in os.listdir(DOWNLOAD_DIR):
        if f.endswith(".mp3") and f.startswith(filename):
            return os.path.join(DOWNLOAD_DIR, f)
    return None


@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Отправь мне ссылку на TikTok или Instagram Reel, и я скачаю его."
    )


@bot.message_handler(func=lambda m: is_tiktok_url(m.text or ""))
def handle_tiktok_url(message):
    url = message.text.strip()
    msg = bot.reply_to(message, "⏳ Скачиваю видео...")
    try:
        filepath = download_video(url)
        if not filepath or not os.path.exists(filepath):
            bot.edit_message_text("Не удалось скачать видео.", chat_id=message.chat.id, message_id=msg.message_id)
            return

        with open(filepath, "rb") as f:
            sent = bot.send_video(message.chat.id, f, caption="Вот ваше видео без водяного знака!")

        keyboard = telebot.types.InlineKeyboardMarkup()
        keyboard.add(telebot.types.InlineKeyboardButton(
            "Скачать аудио (MP3)", callback_data=f"audio:{sent.message_id}"
        ))
        bot.edit_message_reply_markup(message.chat.id, sent.message_id, reply_markup=keyboard)

        video_files[sent.message_id] = filepath
        bot.delete_message(message.chat.id, msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"Ошибка: {e}", chat_id=message.chat.id, message_id=msg.message_id)


@bot.message_handler(func=lambda m: is_instagram_url(m.text or ""))
def handle_instagram_url(message):
    url = message.text.strip()
    msg = bot.reply_to(message, "⏳ Скачиваю Instagram Reel...")
    try:
        filepath = download_video(url)
        if not filepath or not os.path.exists(filepath):
            bot.edit_message_text("Не удалось скачать видео.", chat_id=message.chat.id, message_id=msg.message_id)
            return

        with open(filepath, "rb") as f:
            bot.send_video(message.chat.id, f, caption="🎬 Instagram Reel")

        bot.delete_message(message.chat.id, msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"Ошибка: {e}", chat_id=message.chat.id, message_id=msg.message_id)


@bot.message_handler(func=lambda m: True)
def handle_unknown(message):
    bot.reply_to(message, "Это не ссылка на TikTok или Instagram. Попробуйте ещё раз.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("audio:"))
def handle_audio_button(call):
    msg_id = int(call.data.split(":")[1])
    filepath = video_files.get(msg_id)

    bot.answer_callback_query(call.id, "⏳ Извлекаю аудио...")

    try:
        if filepath and os.path.exists(filepath):
            audio_path = extract_audio(filepath)
        else:
            # Если видео удалено — скачиваем заново из сообщения
            bot.edit_message_text("⏳ Видео уже удалено. Скачиваю заново...", call.message.chat.id, call.message.message_id)
            message = bot.forward_message(call.message.chat.id, call.message.chat.id, msg_id)
            # Получаем оригинальную ссылку из caption не получится, удаляем forwarded
            bot.delete_message(call.message.chat.id, message.message_id)
            bot.edit_message_text("Файл видео был удалён. Отправьте ссылку заново.", call.message.chat.id, call.message.message_id)
            return

        if not audio_path or not os.path.exists(audio_path):
            bot.edit_message_text("Не удалось извлечь аудио.", call.message.chat.id, call.message.message_id)
            return

        with open(audio_path, "rb") as f:
            bot.send_audio(call.message.chat.id, f, caption="Аудио из TikTok")

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        os.remove(filepath)
        os.remove(audio_path)
        video_files.pop(msg_id, None)

    except Exception as e:
        bot.edit_message_text(f"Ошибка: {e}", call.message.chat.id, call.message.message_id)


if __name__ == "__main__":
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        def log_message(self, format, *args):
            pass

    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(), daemon=True).start()

    print("Бот запущен...")
    bot.infinity_polling()

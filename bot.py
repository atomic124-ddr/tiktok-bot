import os
import io
import time
import traceback
import subprocess
import tempfile
import cv2
import numpy as np
from PIL import Image
import telebot
from telebot import types

from config import TELEGRAM_TOKEN

bot = telebot.TeleBot(TELEGRAM_TOKEN)

IMAGES_DIR = "images"
os.makedirs(IMAGES_DIR, exist_ok=True)

user_states = {}

VIDEO_RESOLS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4K": (3840, 2160),
}
VIDEO_FPS = {"30 fps": 30, "60 fps": 60, "120 fps": 120}
PHOTO_RESOLS = {
    "1080p": (1920, 1080),
    "2K": (2560, 1440),
    "4K": (3840, 2160),
}


def upscale_image(image_bytes, target_w, target_h):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise Exception("Не удалось открыть изображение")
    h, w = img.shape[:2]
    interp = cv2.INTER_LANCZOS4 if (target_w * target_h) > (w * h * 4) else cv2.INTER_CUBIC
    resized = cv2.resize(img, (target_w, target_h), interpolation=interp)
    _, buf = cv2.imencode(".png", resized)
    return buf.tobytes()


def process_video(input_path, output_path, target_w, target_h, target_fps):
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
        "-r", str(target_fps),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise Exception(f"FFmpeg error: {result.stderr[:500]}")
    return output_path


def get_file_from_telegram(bot_instance, file_id):
    file_info = bot_instance.get_file(file_id)
    downloaded = bot_instance.download_file(file_info.file_path)
    return downloaded, file_info.file_path


@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_states.pop(message.chat.id, None)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Фото", callback_data="mode_photo"),
        types.InlineKeyboardButton("Видео", callback_data="mode_video"),
    )
    bot.send_message(
        message.chat.id,
        "Привет! Я бот для улучшения качества медиа.\n\n"
        "Выбери, что хочешь улучшить:",
        reply_markup=markup,
    )


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.send_message(
        message.chat.id,
        "Как пользоваться:\n\n"
        "1. Нажми /start\n"
        "2. Выбери Фото или Видео\n"
        "3. Выбери целевое качество\n"
        "4. Отправь медиафайл\n\n"
        "Видео: до 4K, до 120fps\n"
        "Фото: до 4K",
    )


@bot.callback_query_handler(func=lambda c: c.data == "mode_photo")
def callback_photo(call):
    chat_id = call.message.chat.id
    user_states[chat_id] = {"mode": "photo"}
    markup = types.InlineKeyboardMarkup(row_width=2)
    for label, (w, h) in PHOTO_RESOLS.items():
        markup.add(types.InlineKeyboardButton(f"{label} ({w}x{h})", callback_data=f"photo_{label}"))
    bot.edit_message_text("Выбери целевое разрешение для фото:", chat_id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "mode_video")
def callback_video_res(call):
    chat_id = call.message.chat.id
    user_states[chat_id] = {"mode": "video"}
    markup = types.InlineKeyboardMarkup(row_width=2)
    for label, (w, h) in VIDEO_RESOLS.items():
        markup.add(types.InlineKeyboardButton(f"{label} ({w}x{h})", callback_data=f"video_res_{label}"))
    bot.edit_message_text("Выбери целевое разрешение для видео:", chat_id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("photo_"))
def callback_photo_res(call):
    chat_id = call.message.chat.id
    res_label = call.data.replace("photo_", "")
    w, h = PHOTO_RESOLS[res_label]
    user_states[chat_id] = {"mode": "photo", "resolution": res_label, "size": (w, h)}
    bot.edit_message_text(
        f"Разрешение: {res_label} ({w}x{h})\n\nОтправь фото, которое нужно улучшить.",
        chat_id, call.message.message_id,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("video_res_"))
def callback_video_res_pick(call):
    chat_id = call.message.chat.id
    res_label = call.data.replace("video_res_", "")
    w, h = VIDEO_RESOLS[res_label]
    user_states[chat_id] = {"mode": "video", "resolution": res_label, "size": (w, h)}
    markup = types.InlineKeyboardMarkup(row_width=2)
    for fps_label, fps_val in VIDEO_FPS.items():
        markup.add(types.InlineKeyboardButton(fps_label, callback_data=f"video_fps_{fps_label}"))
    bot.edit_message_text(
        f"Разрешение: {res_label} ({w}x{h})\n\nТеперь выбери FPS:",
        chat_id, call.message.message_id, reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("video_fps_"))
def callback_video_fps(call):
    chat_id = call.message.chat.id
    fps_label = call.data.replace("video_fps_", "")
    fps_val = VIDEO_FPS[fps_label]
    state = user_states.get(chat_id, {})
    state["fps"] = fps_val
    state["fps_label"] = fps_label
    user_states[chat_id] = state
    res = state.get("resolution", "?")
    bot.edit_message_text(
        f"Настройки: {res}, {fps_label}\n\nОтправь видео, которое нужно улучшить.",
        chat_id, call.message.message_id,
    )


def handle_media_processing(message, file_bytes, is_video=False):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    if not state:
        bot.reply_to(message, "Сначала нажми /start и выбери режим.")
        return

    mode = state.get("mode")
    status_msg = bot.reply_to(message, "Обрабатываю, подожди...")

    try:
        if mode == "photo":
            w, h = state.get("size", (1920, 1080))
            res_label = state.get("resolution", "1080p")
            result = upscale_image(file_bytes, w, h)
            bot.delete_message(status_msg.chat.id, status_msg.message_id)
            bot.send_photo(chat_id, result, caption=f"Улучшено до {res_label} ({w}x{h})")

        elif mode == "video":
            w, h = state.get("size", (1920, 1080))
            fps = state.get("fps", 30)
            res_label = state.get("resolution", "1080p")
            fps_label = state.get("fps_label", "30 fps")

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
                tmp_in.write(file_bytes)
                tmp_in_path = tmp_in.name

            tmp_out_path = tmp_in_path.replace(".mp4", "_out.mp4")
            try:
                process_video(tmp_in_path, tmp_out_path, w, h, fps)
                with open(tmp_out_path, "rb") as f:
                    result = f.read()
                bot.delete_message(status_msg.chat.id, status_msg.message_id)
                if len(result) <= 50 * 1024 * 1024:
                    bot.send_video(chat_id, result, caption=f"Улучшено до {res_label} {fps_label}")
                else:
                    with open(tmp_out_path, "rb") as f:
                        bot.send_document(chat_id, f, caption=f"Улучшено до {res_label} {fps_label}")
            finally:
                if os.path.exists(tmp_in_path):
                    os.unlink(tmp_in_path)
                if os.path.exists(tmp_out_path):
                    os.unlink(tmp_out_path)

    except Exception as e:
        print(f"[ERROR] {traceback.format_exc()}")
        try:
            bot.edit_message_text(f"Ошибка: {str(e)[:300]}", status_msg.chat.id, status_msg.message_id)
        except:
            bot.send_message(chat_id, f"Ошибка: {str(e)[:300]}")


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    state = user_states.get(message.chat.id)
    if not state or state.get("mode") != "photo":
        if message.photo:
            bot.reply_to(message, "Сначала нажми /start и выбери режим обработки.")
        return

    file_id = message.photo[-1].file_id
    file_bytes, _ = get_file_from_telegram(bot, file_id)
    handle_media_processing(message, file_bytes, is_video=False)


@bot.message_handler(content_types=["video"])
def handle_video(message):
    state = user_states.get(message.chat.id)
    if not state or state.get("mode") != "video":
        bot.reply_to(message, "Сначала нажми /start и выбери режим обработки.")
        return

    file_id = message.video.file_id
    file_bytes, _ = get_file_from_telegram(bot, file_id)
    handle_media_processing(message, file_bytes, is_video=True)


@bot.message_handler(content_types=["document"])
def handle_document(message):
    if not message.document or not message.document.mime_type:
        return
    mime = message.document.mime_type
    is_video = mime.startswith("video/")
    is_image = mime.startswith("image/")

    if not is_video and not is_image:
        return

    state = user_states.get(message.chat.id)
    if not state or state.get("mode") is None:
        bot.reply_to(message, "Сначала нажми /start и выбери режим обработки.")
        return

    if state["mode"] == "photo" and not is_image:
        bot.reply_to(message, "Ты выбрал режим фото, но отправил видео. Нажми /start заново.")
        return
    if state["mode"] == "video" and not is_video:
        bot.reply_to(message, "Ты выбрал режим видео, но отправил фото. Нажми /start заново.")
        return

    file_id = message.document.file_id
    file_bytes, _ = get_file_from_telegram(bot, file_id)
    handle_media_processing(message, file_bytes, is_video=is_video)


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    bot.reply_to(message, "Отправь фото или видео для обработки.\nНажми /start чтобы начать.")


if __name__ == "__main__":
    import sys
    print("[QUALITY-BOT] Starting...", flush=True)
    while True:
        try:
            bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"[ERROR] {e}, restarting in 5s...", flush=True)
            time.sleep(5)

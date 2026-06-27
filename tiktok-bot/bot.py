import os
import telebot
from telebot import types
import yt_dlp

# Загружаем токен из переменных Railway
TOKEN = os.environ.get('TOKEN')
bot = telebot.TeleBot(TOKEN)

# Папка для временных файлов
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "Привет! Я мощный бот-загрузчик.\n\n"
        "🎬 Отправь мне ссылку на **TikTok** (видео или фото-галерею), **YouTube** или **Shorts**, "
        "и я скачаю контент для тебя!"
    )

@bot.message_handler(func=lambda message: True)
def handle_link(message):
    url = message.text.strip()
    
    # Проверяем, что это ссылка
    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "Пожалуйста, отправь корректную ссылку.")
        return

    status_msg = bot.reply_to(message, "⏳ Обрабатываю ссылку, подожди немного...")

    # Настройки для yt-dlp
    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Извлекаем информацию о ссылке
            info = ydl.extract_info(url, download=False)
            
            # --- СЦЕНАРИЙ 1: ЭТО ФОТО-ГАЛЕРЕЯ TIKTOK ---
            if 'entries' in info or (info.get('extractor') == 'tiktok' and not info.get('video_bytes') and info.get('images')):
                bot.edit_message_text("📸 Обнаружена фото-галерея! Скачиваю фотографии...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
                
                images = info.get('images', [])
                if not images and 'entries' in info:
                    # Если ссылки внутри списка
                    entry = info['entries'][0]
                    images = entry.get('images', [])

                if images:
                    media_group = []
                    for idx, img_url in enumerate(images[:9]): # Ограничение Telegram на 10 медиа в ряд
                        media_group.append(types.InputMediaPhoto(img_url))
                    
                    bot.send_media_group(message.chat.id, media_group)
                    bot.delete_message(status_msg.chat.id, status_msg.message_id)
                    return
                else:
                    raise Exception("Не удалось извлечь фотографии.")

            # --- СЦЕНАРИЙ 2: ЭТО ОБЫЧНОЕ ВИДЕО (TikTok, YouTube, Shorts) ---
            bot.edit_message_text("📥 Скачиваю видео на сервер...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            
            # Скачиваем файл на диск Railway
            file_info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(file_info)
            
            # Если yt-dlp изменил расширение при сборке (например, в mp4)
            if not os.path.exists(filename):
                base, _ = os.path.splitext(filename)
                filename = base + ".mp4"

            bot.edit_message_text("🚀 Отправляю видео в Telegram...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            
            # Создаем инлайн-кнопку для скачивания аудио
            keyboard = types.InlineKeyboardMarkup()
            callback_button = types.InlineKeyboardButton(text="🎵 Скачать аудио (MP3)", callback_data=f"audio_{file_info['id']}")
            keyboard.add(callback_button)

            # Отправляем видео пользователю
            with open(filename, 'rb') as video:
                bot.send_video(
                    message.chat.id, 
                    video, 
                    reply_markup=keyboard, 
                    caption="Вот твое видео без водяного знака!"
                )
            
            # Удаляем статус-сообщение и временный файл видео
            bot.delete_message(status_msg.chat.id, status_msg.message_id)
            os.remove(filename)

    except Exception as e:
        print(f"Ошибка: {e}")
        bot.edit_message_text(f"❌ Ошибка при обработке ссылки. Возможно, контент приватный или формат не поддерживается.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)

# Обработчик нажатия на кнопку "Скачать аудио (MP3)"
@bot.callback_query_handler(func=lambda call: call.data.startswith('audio_'))
def handle_audio_callback(call):
    video_id = call.data.replace('audio_', '')
    bot.answer_callback_query(call.id, "⏳ Извлекаю аудиодорожку...")
    
    # Ищем видео заново по ID и качаем только звук
    url = f"https://www.youtube.com/watch?v={video_id}" if len(video_id) == 11 else f"https://v.tiktok.com/{video_id}"
    # Если это был прямой ID, проще использовать универсальный поиск yt-dlp по ID
    url = f"ytsearch:{video_id}" if not url.startswith("http") else url

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_DIR}/audio_{video_id}.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}" if len(video_id)==11 else video_id, download=True)
            # Из-за особенностей постпроцессора имя файла будет .mp3
            audio_filename = f"{DOWNLOAD_DIR}/audio_{video_id}.mp3"
            
            if os.path.exists(audio_filename):
                with open(audio_filename, 'rb') as audio:
                    bot.send_audio(call.message.chat.id, audio, caption="Вот твоя аудиодорожка!")
                os.remove(audio_filename)
            else:
                bot.send_message(call.message.chat.id, "❌ Не удалось найти или извлечь аудиофайл.")
    except Exception as e:
        bot.send_message(call.message.chat.id, "❌ Ошибка при конвертации в MP3. Попробуйте другую ссылку.")

if __name__ == '__main__':
    bot.polling(none_stop=True)

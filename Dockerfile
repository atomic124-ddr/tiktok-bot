FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir pyTelegramBotAPI yt-dlp
COPY . .
CMD ["python", "bot.py"]

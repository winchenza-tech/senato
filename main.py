import asyncio
import nest_asyncio
import datetime
import os
import random
import io
import re
import requests
from collections import deque
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from google import genai
from google.genai import types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# --- 1. WEB SUNUCUSU ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Zenithar 7/24 Görev Başında!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- 2. AYARLAR VE HAFIZA ---
nest_asyncio.apply()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

AUTHORIZED_GROUP_ID = -1001506019626
BOT_NAME = "Zenithar"

ADMIN_ID = 7094870780
SPECIAL_USER_ID = 8161908351
ALLOWED_USERS = [ADMIN_ID, SPECIAL_USER_ID]

UNAUTHORIZED_IMAGE_URL = "https://i.ibb.co/bgq1t0kp/MG-8928.jpg"

client = genai.Client(api_key=GOOGLE_API_KEY)

group_history = deque(maxlen=250)
message_id_cache = {}
last_usage = {}
COOLDOWN_MINUTES = 10
pending_replies = {}

ZODIAC_EMOJIS = {
    "koç": "♈", "boğa": "♉", "ikizler": "♊", "yengeç": "♋", "aslan": "♌", 
    "başak": "♍", "terazi": "♎", "akrep": "♏", "yay": "♐", "oğlak": "♑", 
    "kova": "♒", "balık": "♓"
}

# --- 3. BOT FONKSİYONLARI ---

async def record_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private' and user_id == ADMIN_ID:
        if user_id in pending_replies:
            target_id = pending_replies.pop(user_id)
            if update.message.text: await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=update.message.text, reply_to_message_id=target_id)
            return
    if update.effective_chat.id == AUTHORIZED_GROUP_ID and update.message and update.message.text:
        u_name = update.effective_user.first_name
        group_history.append(f"{u_name}: {update.message.text}")
        message_id_cache[update.message.message_id] = {"name": u_name, "text": update.message.text}

# --- GÜNCEL BURÇ MOTORU (GÜVENLİ VE PM DESTEKLİ) ---
async def burcyorumla_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Yetki Kontrolü: Doğru grup VEYA Admin Özel Mesajı
    is_admin_pm = update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID
    if update.effective_chat.id != AUTHORIZED_GROUP_ID and not is_admin_pm:
        return

    metin = update.message.text.lower()
    temiz_args = re.sub(r'^/burcyorumla(?:@[a-zA-Z0-9_]+)?\s*', '', metin).strip().split()
    if not temiz_args:
        await update.message.reply_text("❗ Örnek: /burcyorumla akrep")
        return
    
    burc_input = temiz_args[0]
    emoji = ZODIAC_EMOJIS.get(burc_input, "✨")
    
    status_msg = await update.message.reply_text(f"🛰️ {burc_input.capitalize()} için yıldız haritası oluşturuluyor...")
    
    tz = pytz.timezone("Europe/Istanbul")
    date_str = datetime.datetime.now(tz).strftime("%d %B %Y")

    prompt = (f"Bugünün tarihi: {date_str}. Sen usta bir astrologsun. {burc_input} burcu için "
              "günlük yorum yap. Karakterin: Dobra, zeki, iğneleyici ve gerçekçi. "
              "Zenithar dünyasına uygun derinlikte ve iğneleyici konuş. Maks 100 kelime. Yıldız (*) kullanma.")

    try:
        # Sansürleri Kaldıran Güvenlik Ayarları
        safety_settings = [
            types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
        ]

        def call_gemini():
            return client.models.generate_content(
                model='gemini-2.0-flash', 
                contents=prompt,
                config=types.GenerateContentConfig(safety_settings=safety_settings)
            )

        res = await asyncio.to_thread(call_gemini)
        
        if not res.text:
            raise Exception("Boş yanıt alındı.")

        await status_msg.edit_text(f"{emoji} {burc_input.upper()} YORUMU ({date_str}):\n\n{res.text}")
    except Exception as e:
        print(f"Hata detayı: {e}")
        await status_msg.edit_text("❌ Yıldızlar şu an çok yoğun, frekans ayarlanamadı. Tekrar dene!")

# Diğer komutları (tarot, özet, fal) buraya aynı mantıkla ekleyebilirsin.

async def main():
    keep_alive()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("burcyorumla", burcyorumla_command))
    application.add_handler(MessageHandler((filters.TEXT) & (~filters.COMMAND), record_message))

    await application.initialize(); await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception as e: print(f"Hata: {e}")

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
ADMIN_ID = 7094870780
ALLOWED_USERS = [ADMIN_ID, 8161908351]

client = genai.Client(api_key=GOOGLE_API_KEY)

ZODIAC_EMOJIS = {
    "koç": "♈", "boğa": "♉", "ikizler": "♊", "yengeç": "♋", "aslan": "♌", 
    "başak": "♍", "terazi": "♎", "akrep": "♏", "yay": "♐", "oğlak": "♑", 
    "kova": "♒", "balık": "♓"
}

# --- 3. BURÇ YORUMLAMA MOTORU ---
async def burcyorumla_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Yetki: Grup VEYA Admin PM
    is_pm = update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID
    if update.effective_chat.id != AUTHORIZED_GROUP_ID and not is_pm:
        return

    metin = update.message.text.lower()
    temiz_args = re.sub(r'^/burcyorumla(?:@[a-zA-Z0-9_]+)?\s*', '', metin).strip().split()
    
    if not temiz_args:
        await update.message.reply_text("❗ Örnek: /burcyorumla akrep")
        return
    
    burc_input = temiz_args[0]
    emoji = ZODIAC_EMOJIS.get(burc_input, "✨")
    
    status_msg = await update.message.reply_text(f"🛰️ {burc_input.capitalize()} için kozmik bağlantı kuruluyor...")
    
    # Tarih bilgisi
    tz = pytz.timezone("Europe/Istanbul")
    date_str = datetime.datetime.now(tz).strftime("%d %B %Y")

    # PROMPT: Güvenlik filtrelerine takılmayacak ama karakteri koruyacak şekilde optimize edildi
    prompt = (f"Bugünün tarihi: {date_str}. Sen usta ve biraz da gizemli bir astrologsun. "
              f"{burc_input} burcu için bugüne özel derin bir günlük yorum yaz. "
              "Üslubun: Karakteristik, gerçekçi, lafını sakınmayan ve hafif iğneleyici olsun. "
              "Klişe pembe tablolardan kaçın, insanın yüzüne gerçekleri çarpan bir tarz kullan. "
              "Maksimum 90 kelime. Asla yıldız (*) işareti kullanma.")

    try:
        # GÜVENLİK AYARLARI: Tüm bariyerleri kaldırıyoruz
        safety_settings = [
            types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
        ]

        def generate():
            return client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=types.GenerateContentConfig(safety_settings=safety_settings)
            )

        res = await asyncio.to_thread(generate)
        
        if res.text:
            await status_msg.edit_text(f"{emoji} {burc_input.upper()} ({date_str}):\n\n{res.text}")
        else:
            await status_msg.edit_text("❌ Yıldızlar şu an konuşmak istemiyor, birazdan tekrar dene.")

    except Exception as e:
        print(f"Hata: {e}")
        await status_msg.edit_text("⚠️ Kozmik bir fırtına çıktı, bağlantı koptu. Tekrar dener misin?")

# --- 4. ANA ÇALIŞTIRICI ---
async def main():
    keep_alive()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("burcyorumla", burcyorumla_command))
    
    # Diğer mesajları kaydetmek için (opsiyonel)
    async def log_msg(u, c): pass
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), log_msg))

    print("Zenithar Burç Motoru Yayında!")
    await application.initialize(); await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass

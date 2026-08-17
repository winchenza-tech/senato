import asyncio
import nest_asyncio
import datetime
import os
import random
import io
import re
import time
import json
import html
from collections import deque
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters, PollAnswerHandler
from google import genai
from google.genai import types

# YENİ EKLENEN KÜTÜPHANELER
import yt_dlp
from pyrogram import Client as PyroClient
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream

# --- 1. WEB SUNUCUSU ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot 7/24 Görev Başında! (Quiz Aktif)"

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

MODEL_NAME = "gemini-2.5-flash"

AUTHORIZED_GROUP_ID = -1001506019626
BOT_NAME = "Zenithar"

ADMIN_ID = 7094870780
SPECIAL_USER_ID = 8161908351
ALLOWED_USERS = [ADMIN_ID, SPECIAL_USER_ID]

STICKER_ADMINS = [652932220, 7094870780]
blocked_stickers_list = []

UNAUTHORIZED_IMAGE_URL = "https://i.ibb.co/bgq1t0kp/MG-8928.jpg"

client = genai.Client(api_key=GOOGLE_API_KEY)

group_history = deque(maxlen=250)
message_id_cache = {}
last_usage = {}
COOLDOWN_MINUTES = 10
pending_replies = {}

# --- SESLİ SOHBET (VC) AYARLARI ---
API_ID = int(os.environ.get("API_ID", 6))
API_HASH = os.environ.get("API_HASH", "eb06d4abfb49dc3eeb1aeb98ae0f581e")
pyro_app = PyroClient("vc_bot", api_id=API_ID, api_hash=API_HASH, bot_token=TELEGRAM_TOKEN)
call_py = PyTgCalls(pyro_app)

# --- QUİZ OYUN DURUMU ---
QUIZ_STATE = {"active": False, "polls": {}, "scores": {}}

# --- TAROT KARTLARI ---
TAROT_CARDS = [
    "Deli", "Büyücü", "Azize", "İmparatoriçe", "İmparator", "Aziz",
    "Aşıklar", "Savaş Arabası", "Güç", "Ermiş", "Kader Çarkı", "Adalet",
    "Asılan Adam", "Ölüm", "Denge", "Şeytan", "Yıkılan Kule", "Yıldız",
    "Ay", "Güneş", "Mahkeme", "Dünya"
]

# --- YARDIMCI FONKSİYONLAR ---

async def safe_generate(contents, config=None, retries=5):
    for attempt in range(retries):
        try:
            res = await client.aio.models.generate_content(model=MODEL_NAME, contents=contents, config=config)
            _ = res.text 
            return res
        except Exception as e:
            if attempt == retries - 1: raise e 
            await asyncio.sleep(5) 

# --- BOT FONKSİYONLARI ---

async def reject_private(update, context):
    try: await update.effective_message.reply_photo(photo=UNAUTHORIZED_IMAGE_URL, caption="⛔ Yalnızca Senato grubunda çalışacağını söylemiştim.")
    except: await update.effective_message.reply_text("⛔ Yalnızca Senato grubunda çalışacağını söylemiştim.")

async def reject_unauthorized_group(update, context):
    try: await update.effective_message.reply_photo(photo=UNAUTHORIZED_IMAGE_URL, caption="⛔ Yalnızca Senato grubunda çalışacağını söylemiştim. Burası yetkisiz bölge.")
    except: await update.effective_message.reply_text("⛔ Yalnızca Senato grubunda çalışacağını söylemiştim. Burası yetkisiz bölge.")

async def record_message(update, context):
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private' and user_id in ALLOWED_USERS and user_id in pending_replies:
        target_id = pending_replies.pop(user_id)
        if update.message.text: await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=update.message.text, reply_to_message_id=target_id)
        return
    if update.effective_chat.id == AUTHORIZED_GROUP_ID and update.message:
        text = update.message.text or update.message.caption
        if text:
            u_name = update.effective_user.first_name
            group_history.append(f"{u_name}: {text}")
            message_id_cache[update.message.message_id] = {"name": u_name, "text": text}

# --- KOMUTLAR ---

async def oynat_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID or not context.args: return
    url = context.args[0]
    status_msg = await update.message.reply_text("⏳...")
    try:
        ydl_opts = {'format': 'best[height<=480]/best', 'quiet': True, 'noplaylist': True}
        info = await asyncio.get_event_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))
        stream_url = info.get('url') or info.get('entries', [{}])[0].get('url')
        
        # Modern py-tgcalls API
        await call_py.play(update.effective_chat.id, MediaStream(stream_url))
        
        await status_msg.edit_text(f"▶️ Oynatıtyor: {html.escape(info.get('title', 'Medya'))}")
    except Exception as e: await status_msg.edit_text(f"opss beceremedim: {e}")

async def durdur_command(update, context):
    try:
        # Modern py-tgcalls API
        await call_py.leave_call(update.effective_chat.id)
        await update.message.reply_text("⏹️ Durdurul.")
    except: pass

# --- DİĞER KOMUTLAR (Aynı Şekilde Kalıyor) ---
async def announce_command(update, context):
    if update.effective_user.id in ALLOWED_USERS and context.args: await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=f"📢 {' '.join(context.args)}")

async def comment_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID or not update.message.reply_to_message: return
    target = update.message.reply_to_message
    t_name = target.from_user.first_name
    if t_name.lower() == BOT_NAME.lower(): await update.message.reply_text("İhanet edemem.")
    else:
        target_text = target.text or target.caption or ""
        prompt = f"HEDEF: {t_name}, MESAJI: {target_text}. Sivri dilli, küfürlü bir şekilde aşağıla, max 25 kelime, yıldız (*) kullanma."
        res = await safe_generate(contents=prompt)
        await target.reply_text(f"💀 {res.text}")

# Sticker kontrol fonksiyonu eksikti, basit bir placeholder eklendi
async def check_sticker(update, context):
    # Buraya kendi sticker engelleme mantığını yazabilirsin
    pass

# --- ANA DÖNGÜ ---
async def main():
    keep_alive()
    await pyro_app.start()
    await call_py.start()
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("oynat", oynat_command))
    application.add_handler(CommandHandler("durdur", durdur_command))
    application.add_handler(CommandHandler("start", reject_private, filters=filters.ChatType.PRIVATE & (~filters.User(ALLOWED_USERS))))
    application.add_handler(CommandHandler("duyuru", announce_command))
    application.add_handler(CommandHandler("yorumla", comment_command))
    
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.User(ALLOWED_USERS)), reject_private))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & (~filters.Chat(chat_id=AUTHORIZED_GROUP_ID)), reject_unauthorized_group))
    application.add_handler(MessageHandler(filters.Sticker.ALL, check_sticker))
    application.add_handler(MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO) & (~filters.COMMAND), record_message))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Kritik Hata: {e}")
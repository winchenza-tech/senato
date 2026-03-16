import asyncio
import nest_asyncio
import datetime
import os
import random
import io
import re  # EKLENDİ
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
    return "Bot 7/24 Görev Başında!"

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
fashion_sessions = {} 

# --- BURÇ VE TAROT VERİLERİ ---
ZODIAC_EMOJIS = {
    "koç": "♈", "boğa": "♉", "ikizler": "♊", "yengeç": "♋", "aslan": "♌", 
    "başak": "♍", "terazi": "♎", "akrep": "♏", "yay": "♐", "oğlak": "♑", 
    "kova": "♒", "balık": "♓"
}

TAROT_CARDS = [
    "Deli", "Büyücü", "Azize", "İmparatoriçe", "İmparator", "Aziz",
    "Aşıklar", "Savaş Arabası", "Güç", "Ermiş", "Kader Çarkı", "Adalet",
    "Asılan Adam", "Ölüm", "Denge", "Şeytan", "Yıkılan Kule", "Yıldız",
    "Ay", "Güneş", "Mahkeme", "Dünya"
]

# --- 3. BOT FONKSİYONLARI ---

async def reject_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    # Admin özelden komut yazıyorsa engelleme (Deneme yapabilmen için)
    if update.effective_user.id == ADMIN_ID: return 
    
    try:
        await update.effective_message.reply_photo(
            photo=UNAUTHORIZED_IMAGE_URL,
            caption="⛔ Yalnızca Senato grubunda çalışacağını söylemiştim."
        )
    except Exception as e:
        await update.effective_message.reply_text("⛔ Yalnızca Senato grubunda çalışacağını söylemiştim.")

async def reject_unauthorized_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    try:
        await update.effective_message.reply_photo(
            photo=UNAUTHORIZED_IMAGE_URL,
            caption="⛔ Yalnızca Senato grubunda çalışacağını söylemiştim. Burası yetkisiz bölge."
        )
    except Exception as e:
        await update.effective_message.reply_text("⛔ Yalnızca Senato grubunda çalışacağını söylemiştim. Burası yetkisiz bölge.")

async def record_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private' and user_id in fashion_sessions:
        if update.message.text and not update.message.text.startswith('/'):
            await handle_fashion_chat(update, context)
            return

    if update.effective_chat.type == 'private' and user_id == ADMIN_ID:
        if user_id in pending_replies:
            target_id = pending_replies.pop(user_id)
            if update.message.text: 
                await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=update.message.text, reply_to_message_id=target_id)
            elif update.message.voice: 
                await context.bot.send_voice(chat_id=AUTHORIZED_GROUP_ID, voice=update.message.voice.file_id, reply_to_message_id=target_id)
            elif update.message.audio: 
                await context.bot.send_audio(chat_id=AUTHORIZED_GROUP_ID, audio=update.message.audio.file_id, reply_to_message_id=target_id)
            return

    if update.effective_chat.id == AUTHORIZED_GROUP_ID and update.message and update.message.text:
        u_name = update.effective_user.first_name
        group_history.append(f"{u_name}: {update.message.text}")
        message_id_cache[update.message.message_id] = {"name": u_name, "text": update.message.text}
        if len(message_id_cache) > 50: 
            del message_id_cache[next(iter(message_id_cache))]

# --- ✨ GÜNCEL BURÇ MOTORU (EKLENDİ) ---

async def burcyorumla_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # YETKİ KONTROLÜ: Sadece izinli grup veya ADMIN'in özel mesajı
    if chat_id != AUTHORIZED_GROUP_ID and not (update.effective_chat.type == 'private' and user_id == ADMIN_ID):
        return

    if not context.args:
        await update.message.reply_text("❗ Örnek: /burcyorumla akrep")
        return

    burc_input = context.args[0].lower()
    emoji = ZODIAC_EMOJIS.get(burc_input, "✨")
    
    status_msg = await update.message.reply_text(f"{emoji} {burc_input.capitalize()} için yıldız haritası çekiliyor...")

    try:
        tz = pytz.timezone("Europe/Istanbul")
        date_str = datetime.datetime.now(tz).strftime("%d-%m-%Y")
        
        prompt = (f"Sen profesyonel bir astrolog samimi bir teyzesin. Bugünün tarihi: {date_str}. "
                  f"Lütfen {burc_input} burcu için günlük burç yorumu yap. "
                  "Aşk, para, sağlık ve kariyer konularına değin. Samimi, biraz gizemli biraz da sivri dilli ol "
                  "iki paragraf halinde yaz. Maks 120 kelime. * sembolü kullanma.")

        res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=prompt)
        await status_msg.edit_text(f"{emoji} {burc_input.upper()} YORUMU ({date_str}):\n\n{res.text}")
    except Exception as e:
        await status_msg.edit_text("❌ Yıldızlarla bağlantı kurulamadı.")

# --- DİĞER KOMUTLAR ---

async def kombinle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS: return
    target = update.message.reply_to_message
    if not target or not target.photo:
        await update.message.reply_text("📸 Lütfen kombin tavsiyesi almak istediğin bir kıyafet fotoğrafını yanıtla!")
        return
    status = await update.message.reply_text("🧐 Ivanarya stili inceliyor, bekleyin...")
    try:
        photo_file = await target.photo[-1].get_file()
        f = io.BytesIO(); await photo_file.download_to_memory(f); f.seek(0)
        image_bytes = f.read()
        prompt = "Sen bir moda ikonusun. Bu görseldeki kıyafeti analiz et ve buna uygun harika bir kombin önerisi yap. Kısa ve etkileyici olsun."
        res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=[types.Content(parts=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")])])
        fashion_sessions[user_id] = {"count": 1}
        await status.edit_text(f"✨ EZDERYA STYLE:\n\n{res.text}\n\n*(Bu kombin hakkında 2 soru daha sorabilirsin)")
    except: await status.edit_text("❌ Analiz başarısız.")

async def handle_fashion_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = fashion_sessions[user_id]["count"]
    if count < 3:
        fashion_sessions[user_id]["count"] += 1
        remaining = 3 - fashion_sessions[user_id]["count"]
        prompt = f"Kullanıcı şunu sordu: '{update.message.text}'. Nazik ve uzman bir dille cevapla. Maks 40 kelime."
        try:
            res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=prompt)
            suffix = f"\n\n*(Kalan hak: {remaining})*" if remaining > 0 else "\n\n*(Soru hakkın doldu)*"
            await update.message.reply_text(f"👔 {res.text}{suffix}")
            if remaining == 0: del fashion_sessions[user_id]
        except: pass
    else: del fashion_sessions[user_id]

async def announce_command(update, context):
    if update.effective_user.id == ADMIN_ID and context.args:
        await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=f"📢 {' '.join(context.args)}")

async def comment_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID or not update.message.reply_to_message: return
    target = update.message.reply_to_message
    t_name = target.from_user.first_name
    if t_name.lower() == BOT_NAME.lower():
        await update.message.reply_text(f"{BOT_NAME}'a ihanet edemem.")
        return
    target_text = target.text or target.caption or ""
    roast_prompt = f"(Acımasız, alaycısın). HEDEF: {t_name} MESAJI: {target_text}. İnce espriyle aşağıla. Maks 20 kelime."
    try:
        res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=roast_prompt)
        await target.reply_text(f"💀 {res.text}")
    except: pass

async def summarize_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID: return
    chat_id = update.effective_chat.id
    now = datetime.datetime.now()
    if chat_id in last_usage and (now - last_usage[chat_id]).total_seconds() < COOLDOWN_MINUTES * 60:
        await update.message.reply_text("🛑 Henüz hazır değilim!")
        return
    if len(group_history) < 10:
        await update.message.reply_text("❌ Yeterli mesaj yok.")
        return
    status_msg = await update.message.reply_text("⏳ Zenithar mantığıyla dolduruluyor...")
    full_text = "\n".join(list(group_history)[-200:])
    prompt = f"Konuşmaları esprili, iğneleyici bir dille 5 paragrafta özetle. Maks 140 kelime. * kullanma. \nKONUŞMALAR:\n{full_text}"
    try:
        res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=prompt)
        await status_msg.delete(); await update.message.reply_text(f"📝 CHAT ÖZETİ:\n{res.text}")
        last_usage[chat_id] = now
    except: pass

async def tarot_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID: return
    secilenler = random.sample(TAROT_CARDS, 3)
    status = await update.message.reply_text(f"🃏Kartlar karıştırılıyor...\n1. {secilenler[0]}\n2. {secilenler[1]}\n3. {secilenler[2]}")
    prompt = f"Tarot: {', '.join(secilenler)} mistik ve samimi dille 3 paragrafta yorumla. Maks 100 kelime. * kullanma."
    try:
        res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=prompt)
        await status.edit_text(f"🔮TAROT FALI:\n\n🃏 Kartlar: {', '.join(secilenler)}\n\n📜 Yorum:\n{res.text}")
    except: await status.edit_text("Bağlantı koptu.")

async def quote_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID or not context.args: return
    keyword = " ".join(context.args)
    prompt = f"'{keyword}' ile ilgili filozof sözü getir. Sadece söz ve kişi."
    try:
        res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=prompt)
        await update.message.reply_text(f"🖋 {res.text}")
    except: pass

async def getir_command(update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID:
        clean_id = str(AUTHORIZED_GROUP_ID).replace("-100", "")
        res = "📜 **SON MESAJLAR:**\n\n" + "\n".join([f"👤 {message_id_cache[m_id]['name']} -> https://t.me/c/{clean_id}/{m_id}" for m_id in list(message_id_cache.keys())[-5:]])
        await update.message.reply_text(res)

async def admin_text_reply(update, context):
    if update.effective_chat.type != 'private' or update.effective_user.id != ADMIN_ID or not context.args: return
    try:
        msg_id = int(context.args[0].split('/')[-1])
        t_name = message_id_cache[msg_id]["name"] if msg_id in message_id_cache else "Biri"
        t_text = message_id_cache[msg_id]["text"] if msg_id in message_id_cache else ""
        prompt = f"HEDEF: {t_name} MESAJI: {t_text} GÖREV: Ağır konuş, maks 15 kelime."
        res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=prompt)
        await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=f"💀 {res.text}", reply_to_message_id=msg_id)
    except: pass

async def kendin_yanitla_command(update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID and context.args:
        pending_replies[update.effective_user.id] = int(context.args[0].split('/')[-1])
        await update.message.reply_text("🎯 Hedef kilitlendi. Cevabı gönder.")

# --- MAIN ---

async def main():
    keep_alive()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Istanbul"))
    scheduler.start()

    # Önemli: Komutları reject handler'dan önce ekliyoruz
    application.add_handler(CommandHandler("burcyorumla", burcyorumla_command))
    application.add_handler(CommandHandler("tarotbak", tarot_command))
    application.add_handler(CommandHandler("yorumla", comment_command))
    application.add_handler(CommandHandler("quote", quote_command))
    application.add_handler(CommandHandler("kombinle", kombinle_command))
    application.add_handler(CommandHandler("duyuru", announce_command))
    
    # Admin Özel Komutlar
    application.add_handler(CommandHandler("getir", getir_command))
    application.add_handler(CommandHandler("yanitla", admin_text_reply))
    application.add_handler(CommandHandler("kendinyanitla", kendin_yanitla_command))

    # Reject Handlers
    application.add_handler(CommandHandler("start", reject_private, filters=filters.ChatType.PRIVATE & (~filters.User(ALLOWED_USERS))))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.User(ALLOWED_USERS)), reject_private))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & (~filters.Chat(chat_id=AUTHORIZED_GROUP_ID)), reject_unauthorized_group))

    # General Handlers
    application.add_handler(MessageHandler(filters.Regex(r'(?i)^/son(100|200)'), summarize_command))
    application.add_handler(MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO) & (~filters.COMMAND), record_message))

    print("Zenithar Services Aktif (Burç Motoru Dahil)...")
    await application.initialize(); await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception as e: print(f"Hata: {e}")

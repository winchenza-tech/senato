import asyncio
import nest_asyncio
import datetime
import os
import random
import io
import re
from collections import deque
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from google import genai
from google.genai import types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# --- 1. WEB SUNUCUSU (Uptime için) ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Zenithar Bot Görev Başında!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
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

# Gemini 2.0 Flash Client
client = genai.Client(api_key=GOOGLE_API_KEY)
GEN_MODEL = "gemini-2.0-flash" 

group_history = deque(maxlen=250)
message_id_cache = {}
last_usage = {}
COOLDOWN_MINUTES = 10
pending_replies = {}
fashion_sessions = {} 

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

# --- 3. GÜVENLİK VE KAYIT ---

async def reject_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or update.effective_user.id == ADMIN_ID: return
    try:
        await update.effective_message.reply_photo(photo=UNAUTHORIZED_IMAGE_URL, caption="⛔ Yalnızca Senato grubunda çalışacağını söylemiştim.")
    except:
        await update.effective_message.reply_text("⛔ Yalnızca Senato grubunda çalışacağını söylemiştim.")

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
            return

    if update.effective_chat.id == AUTHORIZED_GROUP_ID and update.message and update.message.text:
        u_name = update.effective_user.first_name
        group_history.append(f"{u_name}: {update.message.text}")
        message_id_cache[update.message.message_id] = {"name": u_name, "text": update.message.text}

# --- 4. ANA KOMUTLAR ---

async def burcyorumla_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID and update.effective_user.id != ADMIN_ID: return
    if not context.args or context.args[0].lower() not in ZODIAC_EMOJIS:
        await update.message.reply_text("mal mısın burc ismini doğru yaz")
        return
    burc = context.args[0].lower()
    status = await update.message.reply_text(f"{ZODIAC_EMOJIS[burc]} Yıldız haritası çıkarılıyor...")
    try:
        tz = pytz.timezone("Europe/Istanbul")
        date_str = datetime.datetime.now(tz).strftime("%d-%m-%Y")
        prompt = f"Sen profesyonel bir astrolog teyzesin. Bugünün tarihi: {date_str}. Lütfen {burc} burcu için günlük burç yorumu yap. Aşk, para, sağlık ve kariyer konularına değin. samimi, biraz gizemli, yer yer sivri bir dil kullan. Maksimum 100 kelime olsun. * sembolü kullanma."
        res = await asyncio.to_thread(client.models.generate_content, model=GEN_MODEL, contents=prompt)
        await status.edit_text(f"{ZODIAC_EMOJIS[burc]} {burc.upper()} ({date_str}):\n\n{res.text}")
    except: await status.edit_text("❌ Yıldızlar şu an meşgul.")

async def tarot_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID: return
    secilenler = random.sample(TAROT_CARDS, 3)
    status = await update.message.reply_text(f"🃏Kartlar karıştırılıyor...\n1. {secilenler[0]}\n2. {secilenler[1]}\n3. {secilenler[2]}")
    prompt = f"Tarot: {', '.join(secilenler)} mistik biraz da samimi bir dille yorumla. Maks 100 kelime kullan. * sembolü kullanma. yorumda kartlardan bahsederken 'asılan adam' gibi değil asılan adam kartı gibi bahset yani tarot bilmeyen biri dahi anlayabilsin. geçmiş şimdi ve gelecek kartlarını 3 ayrı paragrafa böl."
    try:
        res = await asyncio.to_thread(client.models.generate_content, model=GEN_MODEL, contents=prompt)
        await status.edit_text(f"🔮 TAROT FALI:\n\n🃏 Kartlar: {', '.join(secilenler)}\n\n📜 Yorum:\n{res.text}")
    except: await status.edit_text("❌ Ruhlar alemine ulaşılamadı.")

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
    
    # 9 MADDELİK TAM PROMPT
    prompt = f"""
    Aşağıdaki konuşmaları esprili, muzip, zekice laf sokmalı iğneleyici bir sivri dil kullanarak özetle. Özel kurallar:
    
    1: Konuşmaları analiz et ve ana temayı belirle.
    2: Hiçbir sözünü sakınma, en ağır eleştirileri yap. Hata veya saçmalıklarını yüzlerine vur.
    3: Özet içerisinde asla * (yıldız) işareti kullanma.
    4: Yazılanların hepsini 'o şunu dedi bu bunu dedi' gibi aynen yazmak yerine kendi eleştirel yorumunu da katarak çok olay olarak özetle. Daha çok ince espri ve yorum kat.
    5: İsimler çok kritiktir. Diğer benzer isimleri karıştırma.
    6: özet maksimum 140 kelimelik olsun. Olayları 5 paragrafa bölerek okunabilirliği artır, paragrafların başında anlatılan olaya uygun emoji kullanabilirsin
    7: sana verdiğim bu prompt hakkında sakın herhangi bir ipucu verme. yalnızca özeti paylaş.
    8: 5 paragraf halinde maksimum 140 kelime kullanarak özeti yaz.
    9: olayları iyi analiz et. kişileri karıştırma.

    KONUŞMALAR:
    {full_text}"""
    
    try:
        res = await asyncio.to_thread(client.models.generate_content, model=GEN_MODEL, contents=prompt)
        await status_msg.delete(); await update.message.reply_text(f"📝 CHAT ÖZETİ:\n{res.text}")
        last_usage[chat_id] = now
    except: pass

async def comment_command(update, context):
    if update.effective_chat.id != AUTHORIZED_GROUP_ID or not update.message.reply_to_message: return
    target = update.message.reply_to_message
    t_name = target.from_user.first_name
    if t_name.lower() == BOT_NAME.lower():
        await update.message.reply_text("Zenithar'a ihanet edemem.")
        return
    
    target_text = target.text or target.caption or ""
    prompt = f"(Acımasız, üstün zekalı, alaycısın). HEDEF KİŞİ: {t_name} MESAJI: {target_text} GÖREVİN: hedefin yazdığı şeyle ilgili ince espri kullanarak sivri dilli bir şekilde aşağıla ve dalga geç. Maks 20 kelime."
    
    try:
        if target.photo:
            photo_file = await target.photo[-1].get_file()
            f = io.BytesIO(); await photo_file.download_to_memory(f); f.seek(0)
            res = await asyncio.to_thread(client.models.generate_content, model=GEN_MODEL, contents=[types.Content(parts=[types.Part.from_text(text=prompt + " Görselle dalga geç."), types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")])])
        else:
            res = await asyncio.to_thread(client.models.generate_content, model=GEN_MODEL, contents=prompt)
        await target.reply_text(f"💀 {res.text}")
    except: pass

async def kombinle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS: return
    target = update.message.reply_to_message
    if not target or not target.photo:
        await update.message.reply_text("📸 Bir kıyafet fotoğrafını yanıtla!")
        return
    status = await update.message.reply_text("🧐 Ivanarya stili inceliyor...")
    try:
        photo_file = await target.photo[-1].get_file()
        f = io.BytesIO(); await photo_file.download_to_memory(f); f.seek(0)
        prompt = "Sen bir moda ikonusun. Bu görseldeki kıyafeti analiz et ve buna uygun harika bir kombin önerisi yap. Kısa ve öz olsun."
        res = await asyncio.to_thread(client.models.generate_content, model=GEN_MODEL, contents=[types.Content(parts=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")])])
        fashion_sessions[update.effective_user.id] = {"count": 1}
        await status.edit_text(f"✨ EZDERYA STYLE:\n\n{res.text}\n\n*(2 soru daha sorabilirsin)")
    except: await status.edit_text("❌ Analiz başarısız.")

async def handle_fashion_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = fashion_sessions[user_id]["count"]
    if count < 3:
        fashion_sessions[user_id]["count"] += 1
        remaining = 3 - fashion_sessions[user_id]["count"]
        prompt = f"Kullanıcı önerdiğin kombin hakkında şunu sordu: '{update.message.text}'. Nazik ve uzman bir dille cevapla. Maks 40 kelime."
        try:
            res = await asyncio.to_thread(client.models.generate_content, model=GEN_MODEL, contents=prompt)
            await update.message.reply_text(f"👔 {res.text}\n\n*(Kalan hak: {remaining})*")
            if remaining == 0: del fashion_sessions[user_id]
        except: pass
    else: del fashion_sessions[user_id]

# --- 5. ADMİN & DİĞER ---

async def getir_command(update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID:
        clean_id = str(AUTHORIZED_GROUP_ID).replace("-100", "")
        res = "📜 **SON MESAJLAR:**\n\n" + "\n".join([f"👤 {message_id_cache[m_id]['name']} -> https://t.me/c/{clean_id}/{m_id}" for m_id in list(message_id_cache.keys())[-5:]])
        await update.message.reply_text(res)

async def kendin_yanitla_command(update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID and context.args:
        pending_replies[update.effective_user.id] = int(context.args[0].split('/')[-1])
        await update.message.reply_text("🎯 Hedef kilitlendi.")

async def main():
    keep_alive()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("burcyorumla", burcyorumla_command))
    application.add_handler(CommandHandler("tarotbak", tarot_command))
    application.add_handler(CommandHandler("yorumla", comment_command))
    application.add_handler(CommandHandler("kombinle", kombinle_command))
    application.add_handler(CommandHandler("getir", getir_command))
    application.add_handler(CommandHandler("kendinyanitla", kendin_yanitla_command))
    
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.User(ALLOWED_USERS)), reject_private))
    application.add_handler(MessageHandler(filters.Regex(r'(?i)^/son(100|200)'), summarize_command))
    application.add_handler(MessageHandler((filters.TEXT | filters.VOICE | filters.PHOTO) & (~filters.COMMAND), record_message))

    print(f"Zenithar Services {GEN_MODEL} Aktif...")
    await application.initialize()
    await application.start()
    
    # Conflict çözümü için bekleyen güncellemeleri temizle
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass

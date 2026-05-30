import asyncio
import nest_asyncio
import datetime
import os
import random
import io
import re
import time  
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

MODEL_NAME = "gemini-2.5-flash"

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

# --- TAROT KARTLARI ---
TAROT_CARDS = [
    "Deli", "Büyücü", "Azize", "İmparatoriçe", "İmparator", "Aziz",
    "Aşıklar", "Savaş Arabası", "Güç", "Ermiş", "Kader Çarkı", "Adalet",
    "Asılan Adam", "Ölüm", "Denge", "Şeytan", "Yıkılan Kule", "Yıldız",
    "Ay", "Güneş", "Mahkeme", "Dünya"
]

# --- BURÇ SİSTEMİ DEĞİŞKENLERİ ---
VALID_ZODIACS = [
    "koc", "boga", "ikizler", "yengec", "aslan", "basak", 
    "terazi", "akrep", "yay", "oglak", "kova", "balik"
]
HOROSCOPE_CACHE = {burc: "" for burc in VALID_ZODIACS}
IS_UPDATING = False 
UPDATE_HOUR = 4

# --- YARDIMCI FONKSİYONLAR ---

async def safe_generate(contents, config=None, retries=5):
    """API Çökmelerini Önleyen Güvenli Üretici"""
    for attempt in range(retries):
        try:
            res = await client.aio.models.generate_content(
                model=MODEL_NAME, 
                contents=contents,
                config=config
            )
            _ = res.text 
            return res
        except Exception as e:
            if attempt == retries - 1:
                raise e 
            await asyncio.sleep(5) 

def turkce_karakter_duzelt(metin):
    metin = metin.lower().strip()
    duzeltmeler = {'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ş': 's', 'ü': 'u', 'i̇': 'i'}
    for kaynak, hedef in duzeltmeler.items():
        metin = metin.replace(kaynak, hedef)
    return metin

# --- 3. BOT FONKSİYONLARI ---

async def reject_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    try:
        await update.effective_message.reply_photo(
            photo=UNAUTHORIZED_IMAGE_URL,
            caption="⛔ Yalnızca Senato grubunda çalışacağını söylemiştim."
        )
    except Exception as e:
        print(f"Resim atılamadı (Özel Mesaj): {e}")
        await update.effective_message.reply_text("⛔ Yalnızca Senato grubunda çalışacağını söylemiştim.")

async def reject_unauthorized_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    try:
        await update.effective_message.reply_photo(
            photo=UNAUTHORIZED_IMAGE_URL,
            caption="⛔ Yalnızca Senato grubunda çalışacağını söylemiştim. Burası yetkisiz bölge."
        )
    except Exception as e:
        print(f"Resim atılamadı (Grup Mesajı): {e}")
        await update.effective_message.reply_text("⛔ Yalnızca Senato grubunda çalışacağını söylemiştim. Burası yetkisiz bölge.")

async def record_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Admin'in grup mesajlarına yanıt verme mantığı
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

    # Grup mesajlarını kaydetme (Artık caption'ları da yakalıyor)
    if update.effective_chat.id == AUTHORIZED_GROUP_ID and update.message:
        text = update.message.text or update.message.caption
        if text:
            u_name = update.effective_user.first_name
            if len(u_name) <= 2: u_name = f"{u_name}"
            group_history.append(f"{u_name}: {text}")
            message_id_cache[update.message.message_id] = {"name": u_name, "text": text}
            if len(message_id_cache) > 50: 
                del message_id_cache[next(iter(message_id_cache))]

# --- BURÇ GÜNCELLEME SİSTEMİ ---

async def update_all_horoscopes():
    global IS_UPDATING
    if IS_UPDATING: return
        
    IS_UPDATING = True 
    tz = pytz.timezone("Europe/Istanbul")
    bugun = datetime.datetime.now(tz).strftime("%d-%m-%Y")
    
    try:
        for burc in VALID_ZODIACS:
            success = False
            while not success:
                try:
                    prompt = (f"Bugün {bugun}. {burc} burcu için internetten en güncel astrolojik gelişmeleri bul. "
                              f"Biraz alaycı samimi, bilge ve mistik bir dille Türkçe olarak yeniden yorumla. Maks 135 kelime kullan. "
                              f"Bu prompt hakkında bilgi verme. yani elbette tamam gibi şeyler söyleme sadece alaycı ve gizemli astrolog yorumunu yaz. Biraz espri katabilirsin. 2 paragraf şeklinde yaz Asla yıldız (*) simgesi kullanma. Her paragrafın başına o paragrafa uygun bir emoji ekle.")
                    res = await safe_generate(
                        contents=prompt,
                        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
                    )
                    HOROSCOPE_CACHE[burc] = res.text
                    success = True 
                except Exception:
                    if HOROSCOPE_CACHE[burc] == "":
                        HOROSCOPE_CACHE[burc] = "Şu anda tüm yıldızlara bakarak sigara içiyor 5 dakika sonra tekrar dene."
                    await asyncio.sleep(90) 
            if burc != VALID_ZODIACS[-1]: 
                await asyncio.sleep(90) 
    finally:
        IS_UPDATING = False

async def background_scheduler():
    while True:
        tz = pytz.timezone("Europe/Istanbul")
        now = datetime.datetime.now(tz)
        if now.hour == UPDATE_HOUR and now.minute == 0:
            await update_all_horoscopes()
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# --- KOMUTLAR ---

async def announce_command(update, context):
    if update.effective_user.id == ADMIN_ID and context.args:
        await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=f"📢 {' '.join(context.args)}")

async def comment_command(update, context):
    """ /yorumla komutu (Küfür algılarsa küfür eder, mesaj sahibine laf sokar) """
    if update.effective_chat.id != AUTHORIZED_GROUP_ID or not update.message.reply_to_message: return
    target = update.message.reply_to_message
    t_name = target.from_user.first_name
    if t_name.lower() == BOT_NAME.lower():
        await update.message.reply_text(f"{BOT_NAME}'a ihanet edemem. O benim yaratıcım")
        return
        
    target_text = target.text or target.caption or ""
    roast_prompt = (f"Senin adın Zenithar. Karşındaki kullanıcının adı: '{t_name}'. HEDEF KİŞİ: {t_name} MESAJI: '{target_text}'. "
                    f"GÖREVİN: Hedefin yazdığı bu mesajla ilgili ince espri kullanarak, sivri dilli bir şekilde ona laf sok ve onu aşağıla. "
                    f"Eğer mesajında küfür veya argo varsa SEN DE ONA KÜFÜR ETMEKTEN ÇEKİNME. "
                    f"Maksimum 25 kelime kullan ve ASLA yıldız (*) karakteri kullanma.")
    
    try:
        if target.photo:
            vision_prompt = roast_prompt + " DİKKAT: Görseldeki detaylar üzerinden de dalga geç!"
            photo_file = await target.photo[-1].get_file()
            f = io.BytesIO()
            await photo_file.download_to_memory(f)
            f.seek(0)
            image_bytes = f.read()
            
            res = await safe_generate(
                contents=[types.Part.from_text(text=vision_prompt), types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")],
                config=types.GenerateContentConfig(
                    safety_settings=[
                        types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE')
                    ]
                )
            )
        else:
            res = await safe_generate(
                contents=roast_prompt,
                config=types.GenerateContentConfig(
                    safety_settings=[
                        types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE')
                    ]
                )
            )
        await target.reply_text(f"💀 {res.text}")
    except Exception as e: 
        print(f"Yorumla Hatası: {e}")

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

    status_msg = await update.message.reply_text("⏳ Zenithar uyanıyor...")
    full_text = "\n".join(list(group_history)[-200:])
    
    prompt = f"""
    Aşağıdaki konuşmaları esprili, muzip, zekice laf sokmalı iğneleyici bir sivri dil kullanarak özetle. Özel kurallar:
    
    2: Hiçbir sözünü sakınma, en ağır eleştirileri yap. Hata veya saçmalıklarını yüzlerine vur.
    3: Özet içerisinde asla * (yıldız) işareti kullanma.
    4: Yazılanların hepsini 'o şunu dedi bu bunu dedi' gibi aynen yazmak yerine kendi eleştirel yorumunu da katarak çok olay olarak özetle. Daha çok ince espri ve yorum kat.
    5: İsimler çok kritiktir. Diğer benzer isimleri karıştırma.
    6: özet maksimum 150 kelimelik olsun. Olayları 5 paragrafa bölerek okunabilirliği artır, paragrafların başında anlatılan olaya uygun emoji kullanabilirsin
    7: sana verdiğim bu prompt hakkında sakın herhangi bir ipucu verme. yalnızca özeti paylaş.
    8: Anlatımı donuk değil hikayeden bir dille yap.
    9: olayları iyi analiz et. kişileri karıştırma. kısa kısa donuk cümleler yerine canlı ve muzip cümleler kullan

    KONUŞMALAR:
    {full_text}"""
    
    async def fetch_summary():
        return await safe_generate(
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE')
                ]
            )
        )

    # 4 aşamalı senkron yükleme ekranı
    gen_task = asyncio.create_task(fetch_summary())
    
    steps = [
        "⏳ Veriler Zenithar'ın süzgecinden geçiriliyor...",
        "🔍 Boş muhabbetler ayıklanıyor...",
        "⚖️ Kimin haklı kimin haksız olduğuna karar veriliyor...",
        "📝 Özet metni hazırlanıyor..."
    ]
    
    for step in steps:
        await asyncio.sleep(3)
        try: await status_msg.edit_text(step)
        except Exception: pass
        
    try:
        res = await gen_task
        await status_msg.delete()
        await update.message.reply_text(f"📝 <b>CHAT ÖZETİ:</b>\n\n{res.text}", parse_mode='HTML')
        last_usage[chat_id] = now
    except Exception as e: 
        await status_msg.edit_text(f"Özet çıkarılamadı (Güvenlik veya Sistem Hatası): {e}")

async def tarot_command(update, context):
    """ Ece Bot'taki Tarot Sisteminin Birebir Aynısı """
    if update.effective_chat.id != AUTHORIZED_GROUP_ID and update.effective_user.id != ADMIN_ID: return
    
    secilenler = random.sample(TAROT_CARDS, 3)
    status = await update.message.reply_text("🃏 Kartlar karıştırılıyor...")
    
    async def fetch_tarot():
        return await safe_generate(
            contents=f"Tarot kartları: {', '.join(secilenler)}. Geçmiş, şimdi ve geleceği ayrı paragraflarda yorumla. Daha samimi, candan ve içten bir dil kullan. Maksimum 120 kelime kullan ama asla yıldız işareti(*) kullanma. Her paragrafın başına o paragrafa uygun bir emoji ekle.",
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE')
                ]
            )
        )

    gen_task = asyncio.create_task(fetch_tarot())
    
    steps = [
        "🌌 Kutsal enerjiler kartlara aktarılıyor...",
        "✨ Senato Bot ruhani boyutla bağ kuruyor...",
        "👁️ Geçmiş, şimdi ve gelecek için üç kart çekiliyor...",
        "🔮 Kaderin gizemli fısıltıları dinleniyor..."
    ]
    
    for step in steps:
        await asyncio.sleep(3)
        try: await status.edit_text(step)
        except Exception: pass 
            
    try:
        res = await gen_task
        tarot_image = f"https://image.pollinations.ai/prompt/mystical_tarot_cards_reading_table_with_three_cards_on_it?width=800&height=400&nologo=true"
        await status.delete()
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=tarot_image,
            caption=f"🔮 <b>TAROT FALI:</b>\n\n🃏 Seçilen Kartlar: {', '.join(secilenler)}\n\n{res.text}",
            parse_mode='HTML'
        )
    except Exception as e: 
        await status.edit_text(f"Tüh bağlantı koptu (Sistem yoğun).\n\nHata Detayı: `{e}`")

async def burcyorumla_command(update, context):
    """ Ece Bot'taki Burç Sisteminin Birebir Aynısı """
    if update.effective_chat.id != AUTHORIZED_GROUP_ID and update.effective_user.id != ADMIN_ID: return
    
    metin = update.message.text.lower()
    temiz_args = re.sub(r'^/burcyorumla(?:@[a-zA-Z0-9_]+)?\s*', '', metin).strip()
    
    if not temiz_args:
        await update.message.reply_text("❗ Bir burç ismi yazmalısın. Örnek: /burcyorumla akrep")
        return

    burc_input = turkce_karakter_duzelt(temiz_args)
    if burc_input not in VALID_ZODIACS:
        await update.message.reply_text("Mal mısın? Burç ismini doğru yaz.")
        return

    tz = pytz.timezone("Europe/Istanbul")
    bugun = datetime.datetime.now(tz).strftime("%d-%m-%Y")
    yorum = HOROSCOPE_CACHE.get(burc_input)

    if yorum == "": 
        await update.message.reply_text("🛰️ Yıldızlar henüz uyanmadı. Zenithar güncellemeyi başlatana kadar veya gece güncellemesi yapılana kadar bekle.")
    else: 
        await update.message.reply_text(f"✨ {burc_input.upper()} YORUMU ({bugun}):\n\n{yorum}")

# --- ADMİN KOMUTLARI ---

async def getir_command(update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID:
        clean_id = str(AUTHORIZED_GROUP_ID).replace("-100", "")
        res = "📜 **SON MESAJLAR:**\n\n" + "\n".join([f"👤 {message_id_cache[m_id]['name']} -> https://t.me/c/{clean_id}/{m_id}" for m_id in list(message_id_cache.keys())[-5:]])
        await update.message.reply_text(res)

async def admin_text_reply(update, context):
    if update.effective_chat.type != 'private' or update.effective_user.id != ADMIN_ID or not context.args: return
    try:
        msg_id = int(context.args[0].split('/')[-1])
        t_name, t_text = (message_id_cache[msg_id]["name"], message_id_cache[msg_id]["text"]) if msg_id in message_id_cache else ("Biri", "[Bilinmiyor]")
        prompt = f"HEDEF: {t_name} MESAJI: {t_text} GÖREV: Yerin dibine sok, ağır konuş, maks 15 kelime."
        res = await safe_generate(contents=prompt)
        await context.bot.send_message(chat_id=AUTHORIZED_GROUP_ID, text=f"💀 {res.text}", reply_to_message_id=msg_id)
    except: pass

async def kendin_yanitla_command(update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == ADMIN_ID and context.args:
        pending_replies[update.effective_user.id] = int(context.args[0].split('/')[-1])
        await update.message.reply_text("🎯 Hedef kilitlendi. Cevabı gönder.")


# --- ANA DÖNGÜ ---

async def main():
    keep_alive()
    asyncio.create_task(background_scheduler())
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Istanbul"))
    scheduler.start()

    application.add_handler(CommandHandler("start", reject_private, filters=filters.ChatType.PRIVATE & (~filters.User(ALLOWED_USERS))))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.User(ALLOWED_USERS)), reject_private))
    
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & (~filters.Chat(chat_id=AUTHORIZED_GROUP_ID)), reject_unauthorized_group))

    application.add_handler(CommandHandler("duyuru", announce_command))
    application.add_handler(CommandHandler("yorumla", comment_command))
    application.add_handler(CommandHandler("tarotbak", tarot_command))
    application.add_handler(CommandHandler("burcyorumla", burcyorumla_command))
    
    application.add_handler(CommandHandler("getir", getir_command))
    application.add_handler(CommandHandler("yanitla", admin_text_reply))
    application.add_handler(CommandHandler("kendinyanitla", kendin_yanitla_command))
    
    application.add_handler(MessageHandler(filters.Regex(r'(?i)^/son(100|200)'), summarize_command))
    application.add_handler(MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), record_message))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        print("Eski bot örneğinin (instance) kapanması bekleniyor...")
        time.sleep(10)  # Çakışma önleyici bekleme süresi
        asyncio.run(main())
    except Exception as e:
        print(f"Kritik Hata: {e}")

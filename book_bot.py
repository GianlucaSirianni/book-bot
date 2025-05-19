import os
import json
import requests
import asyncio
import re
from datetime import datetime
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)
from apscheduler.schedulers.background import BackgroundScheduler


#? === VERSIONE ===
__version__ = "0.2.0-beta"

#! === CONFIG ===
TOKEN = "7810048214:AAH8deqsPMVevWI5vhqXaR3GOaTZqILvmTQ"
DATA_FILE = "isbn_data.json"
SETTINGS_FILE = "user_settings.json"
user_state = {}  # { user_id: "inserimento" o None }

#! === CARICAMENTO DATI ===
def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

user_isbn_map = load_json(DATA_FILE)
user_settings = load_json(SETTINGS_FILE)

#! === UTILITIES ===
def clean_title(raw_title: str) -> str:
    base = ' '.join(raw_title.split())
    return re.sub(r'\s*-\s*', ' - ', base)

#! === OTTENGO LE INFO DEL SINGOLO LIBRO PARTENDO DA ISBN ===
def get_book_info(isbn):
    url = f"https://blackwells.co.uk/bookshop/product/{isbn}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.find("div", class_="product_top_half")
        if not main:
            return None

        title_tag = main.find("h1", class_="product__name")
        price_tag = main.find("li", class_="product-price--current")
        discount_tag = main.find("p", class_="product-price--discount")
        date_tag = soup.find("td", itemprop="datePublished")

        title = clean_title(title_tag.text.strip()) if title_tag else "Titolo non trovato"
        price = price_tag.text.strip() if price_tag else "Prezzo non trovato"
        discount = discount_tag.text.strip() if discount_tag and "Save" in discount_tag.text else None
        pub_date = date_tag.text.strip() if date_tag else None

        return {
            "title": title,
            "price": price,
            "discount": discount,
            "release_date": pub_date
        }

    except Exception as e:
        print(f"[{isbn}] Errore durante il recupero: {e}")
        return None


#! === CHECK PER SCONTI E INVIO NOTIFICA ===
async def notify_user(app, user_id):
    print(f"[NOTIFY] Invio notifica all'utente {user_id}...")
    books = user_isbn_map.get(user_id, [])
    if not books:
        return

    offerte, scaduti = [], []

    for book in books:
        url = "https://blackwells.co.uk/bookshop/product/"
        isbn = book["isbn"]
        old_discount = book.get("discount")
        info = get_book_info(isbn)
        if not info:
            continue

        title, price, new_discount = info["title"], info["price"], info["discount"]

        if new_discount:
            offerte.append(f"📚 {title}\n💰 {price}\n🔥 {new_discount}\n🔢 {isbn}\n 🔗{url}{isbn}")
        if old_discount and not new_discount:
            scaduti.append(f"❌ Fine sconto per \"{title}\"")

        book.update(info)

    save_json(DATA_FILE, user_isbn_map)

    if offerte or scaduti:
        msg = "📢 Aggiornamento offerte:\n\n"
        if offerte:
            msg += "🟢 Sconti attivi:\n" + "\n".join(offerte) + "\n"
        if scaduti:
            msg += "🔴 Sconti terminati:\n" + "\n".join(scaduti)
    else:
        msg = "📭 Nessuna offerta oggi."

    await app.bot.send_message(chat_id=user_id, text=msg)

#! === NOTIFICHE GIORNALIERE JOB ===


async def check_releases(app):
    today = datetime.now().strftime("%#d %B %Y")  # su Windows
    print(f"[DEBUG] Today is: {today}")
    messages = {}


    for user_id, books in user_isbn_map.items():
        print(f"[DEBUG] Libri per utente {user_id}:")
        today_books = []
        for book in books:
            url = "https://blackwells.co.uk/bookshop/product/"
            isbn = book["isbn"]
            print(f"[DEBUG] Book: {book.get('title')} — Release: {book.get('release_date')}")
            if book.get("release_date") == today:
                today_books.append(f"📗 *{book.get('title')}*\n 🔗{url}{isbn}")

        if today_books:
            messages[user_id] = "\n\n".join(today_books)

    for user_id, text in messages.items():
        print(f"[DEBUG] Invia notifica a {user_id}")
        await app.bot.send_message(chat_id=user_id, text=f"📦 Novità in uscita oggi:\n\n{text}", parse_mode="Markdown")



def schedule_user_jobs(app, scheduler, loop):
    for user_id, settings in user_settings.items():
        time_str = settings.get("time")
        if not time_str:
            continue

        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            continue

        scheduler.add_job(
            lambda uid=user_id: asyncio.run_coroutine_threadsafe(
                notify_user(app, uid), loop
            ),
            trigger="cron",
            hour=hour,
            minute=minute,
            id=f"notify_{user_id}",
            replace_existing=True,
            misfire_grace_time=5
        )

#! === COMANDI BOT ===

# === Inizializza la conversazione/ === #§ === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Benvenut*! Usa /help per avere una lista dei comandi completa.")
# === Mostra la lista dei comandi attuamente disponibili === #§ === /help ===
async def helpme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 *Benvenutə!* Ecco cosa puoi fare con il bot:\n\n"
        "✏️ /insert – Inserisci i codici ISBN da monitorare\n"
        "📖 /list – Elenca i libri attualmente inseriti\n"
        "⏰ /settime HH:MM – Imposta l'orario per la notifica giornaliera\n"
        "🕵️ /checktime – Controlla l'orario delle notifiche\n"
        "🔥 /saves – Mostra le offerte attive in questo momento\n"
        "ℹ️ /help – Mostra questo elenco di comandi\n"
        "🤖 /v – Versione\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")
# === Per impostare l'orario in cui vuoi ricevere la notifica === #§ === /settime ===
async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args or not context.args[0].count(":") == 1:
        await update.message.reply_text("❗ Usa il formato: /settime HH:MM (es. 08:30)")
        return

    try:
        hour, minute = map(int, context.args[0].split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError

        user_settings[user_id] = {"time": context.args[0]}
        save_json(SETTINGS_FILE, user_settings)

        loop = asyncio.get_running_loop()
        scheduler.add_job(
            lambda uid=user_id: asyncio.run_coroutine_threadsafe(
                notify_user(context.application, uid), loop
            ),
            trigger="cron", hour=hour, minute=minute,
            id=f"notify_{user_id}", replace_existing=True,
            misfire_grace_time=5
        )

        await update.message.reply_text(f"✅ Orario notifiche impostato alle {context.args[0]}.")
    except ValueError:
        await update.message.reply_text("❌ Formato orario non valido. Usa HH:MM")
# === Controlla l'orario impostato per la notifica === #§ === /checktime ===
async def checktime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    time_str = user_settings.get(user_id, {}).get("time")
    if time_str:
        await update.message.reply_text(f"⏰ Riceverai le notifiche ogni giorno alle {time_str}.")
    else:
        await update.message.reply_text("⚠️ Non hai ancora impostato un orario. Usa /settime HH:MM")
# === Inserisci una lista di ISBN per aggiungere i libri === #§ === /insert ===
async def insert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_state[user_id] = "inserimento"
    await update.message.reply_text("Inserisci uno o più codici ISBN (uno per riga e senza caratteri che non siano numeri all'interno del codice):")
# === Mostra la lista dei Libri attualmente inseriti === #§ === /list ===
async def list_isbn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lista = user_isbn_map.get(user_id, [])
    if not lista:
        await update.message.reply_text("Non hai ancora inserito ISBN.")
        return

    for book in lista:
        title = book.get('title', 'Titolo non disponibile')
        price = book.get('price', 'Prezzo non disponibile')
        discount = book.get('discount')
        isbn = book.get('isbn')

        text = (
            f"📚 *{title}*\n"
            f"💰 Prezzo: {price}\n"
            f"🔢 ISBN: {isbn}\n"
            f"{f'*🔥 SCONTO:* {discount}' if discount else ''}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Rimuovi", callback_data=f"delete:{isbn}")]
        ])

        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

# === Fai refresh manuale delle info dei libri in lista (ATTUALMENTE NON MOSTRATO)=== #§ === /refresh ===
async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    books = user_isbn_map.get(user_id, [])
    if not books:
        await update.message.reply_text("Non hai ancora inserito ISBN.")
        return

    changes = []
    for book in books:
        isbn = book["isbn"]
        old = {k: book.get(k) for k in ("title", "price", "discount")}
        info = get_book_info(isbn)
        if not info:
            continue

        changed = []
        if info["price"] != old["price"]:
            changed.append(f"💰 Prezzo: {old['price']} → {info['price']}")
        if info["discount"] != old["discount"]:
            changed.append(f"🔥 Sconto: {old['discount'] or 'Nessuno'} → {info['discount'] or 'Nessuno'}")

        if changed:
            changes.append(f"🔺 Modifiche per \"{old['title'] or info['title']}\":\n" + "\n".join(changed))
            book.update(info)

    save_json(DATA_FILE, user_isbn_map)

    if changes:
        await update.message.reply_text("🔄 Refresh completato:\n\n" + "\n\n".join(changes))
    else:
        await update.message.reply_text("❌ Nessun cambiamento trovato.")
# === Mostra solo una lista dei libri in sconto === #§ === /saves ===
async def saves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await notify_user(context.application, str(update.effective_user.id))
# === Elimina un libro dalla lista === #§ === N.D. ===
async def delete_book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    data = query.data

    if data.startswith("delete:"):
        isbn_to_delete = data.split("delete:")[1]

        books = user_isbn_map.get(user_id, [])
        new_books = [book for book in books if book["isbn"] != isbn_to_delete]

        if len(new_books) == len(books):
            await query.edit_message_text("⚠️ ISBN non trovato.")
            return

        user_isbn_map[user_id] = new_books
        save_json(DATA_FILE, user_isbn_map)

        await query.edit_message_text(f"✅ Libro rimosso con successo.\n🔢 ISBN: {isbn_to_delete}")
# === Parte per gestire i messaggi inviati all'utente con possibili risposte === #§ === N.D. ===
async def gestisci_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stato = user_state.get(user_id)

    # L'utente NON è in modalità inserimento
    if stato != "inserimento":
        await update.message.reply_text("Comando non riconosciuto. Usa /insert o /list.")
        return

    righe = update.message.text.splitlines()
    isbn_validi = [r.strip() for r in righe if r.strip().isdigit()]

    # L'utente è in modalità inserimento ma non ha scritto ISBN validi
    if not isbn_validi:
        await update.message.reply_text("❌ Nessun codice ISBN valido trovato. Ricorda di inserire solo numeri, uno per riga.")
        return

    user_isbn_map.setdefault(user_id, [])

    aggiunti = []
    duplicati = []
    invalidi = []

    for isbn in isbn_validi:
        if any(item["isbn"] == isbn for item in user_isbn_map[user_id]):
            duplicati.append(isbn)
            continue
        info = get_book_info(isbn)
        if not info:
            invalidi.append(isbn)
            continue
        user_isbn_map[user_id].append({"isbn": isbn, **info})
        aggiunti.append(isbn)

    save_json(DATA_FILE, user_isbn_map)
    user_state[user_id] = None  # Fine modalità inserimento

    risposta = []

    if aggiunti:
        risposta.append(f"✅ Aggiunti {len(aggiunti)} ISBN:\n" + "\n".join(f"• {i}" for i in aggiunti))
    if duplicati:
        risposta.append(f"⚠️ Già presenti:\n" + "\n".join(f"• {i}" for i in duplicati))
    if invalidi:
        risposta.append(f"❌ Non trovati o non validi:\n" + "\n".join(f"• {i}" for i in invalidi))

    await update.message.reply_text("\n\n".join(risposta))
# === Parte per gestire i messaggi inviati all'utente con possibili risposte === #§ === /v ===
async def version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤖 Versione attuale del bot: {__version__}")
    await update.message.reply_text(
        "📢 Aggiornamento del 19/05/2025\n\n"
        "È attiva una nuova funzionalità: da oggi riceverai una notifica il giorno in cui esce uno dei libri che hai inserito!\n\n"
        "Il controllo avviene ogni mattina alle 9:30, così non ti perderai nessuna nuova uscita. 🎉"
    )

    

async def usnum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_settings = len(user_settings)
    total_isbn_users = len(user_isbn_map)
    total_users = len(set(user_settings.keys()) | set(user_isbn_map.keys()))

    await update.message.reply_text(
        f"👥 Utenti che hanno usato il bot:\n"
        f"• Con orario notifiche impostato: {total_settings}\n"
        f"• Con almeno un libro salvato: {total_isbn_users}\n"
        f"📊 Totale utenti unici: {total_users}"
    )
    
#! === !!!!!!!!!!!!!! DEBUG FUNCTIONS !!!!!!!!!!!! ===

async def test_release(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Test rilascio manuale in corso...")
    await check_releases(context.application)


#!----------------------------------------------------


#! === PER AVVIARE I JOBS DOPO IL POLLING ===
async def post_start(app):
    loop = asyncio.get_running_loop()
    schedule_user_jobs(app, scheduler, loop)

    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(check_releases(app), loop),
        trigger="cron",
        hour=9,
        minute=30,
        id="release_check",
        replace_existing=True,
        misfire_grace_time=30  # (opzionale ma consigliato)
    )



#! === MAIN ===
def main():
    global scheduler
    scheduler = BackgroundScheduler()
    scheduler.start()

    app = ApplicationBuilder().token(TOKEN).post_init(post_start).build()

    #! === debug command
    app.add_handler(CommandHandler("testrelease", test_release))
    #!------------------

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", helpme))
    app.add_handler(CommandHandler("insert", insert))
    app.add_handler(CommandHandler("list", list_isbn))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("saves", saves))
    app.add_handler(CommandHandler("settime", settime, block=False))
    app.add_handler(CommandHandler("checktime", checktime))
    app.add_handler(CommandHandler("v", version))
    app.add_handler(CommandHandler("usnum", usnum))
    app.add_handler(CallbackQueryHandler(delete_book_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gestisci_messaggio))

    print("Bot avviato...")
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import json
import requests
import asyncio
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)
from apscheduler.schedulers.background import BackgroundScheduler

# === CONFIG ===
TOKEN = "7810048214:AAH8deqsPMVevWI5vhqXaR3GOaTZqILvmTQ"
DATA_FILE = "isbn_data.json"
SETTINGS_FILE = "user_settings.json"
user_state = {}  # { user_id: "inserimento" o None }

# === Caricamento dati ===
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

# === OTTENGO LE INFO DEL SINGOLO LIBRO PARTENDO DA ISBN ===
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

        title = title_tag.text.strip() if title_tag else "Titolo non trovato"
        price = price_tag.text.strip() if price_tag else "Prezzo non trovato"
        discount = discount_tag.text.strip() if discount_tag and "Save" in discount_tag.text else None

        return {"title": title, "price": price, "discount": discount}
    except Exception as e:
        print(f"[{isbn}] Errore durante il recupero: {e}")
        return None

# === CHECK PER SCONTI ===
async def notify_user(app, user_id):
    books = user_isbn_map.get(user_id, [])
    if not books:
        return

    offerte, scaduti = [], []

    for book in books:
        isbn = book["isbn"]
        old_discount = book.get("discount")
        info = get_book_info(isbn)
        if not info:
            continue

        title, price, new_discount = info["title"], info["price"], info["discount"]

        if new_discount:
            offerte.append(f"📚 {title}\n💰 {price}\n🔥 {new_discount}\n🔢 {isbn}\n")
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

# === NOTIFICHE JOB ===
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
            replace_existing=True
        )

# === COMANDI BOT ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ciao! Usa /help per avere una lista dei comandi completa.")
    
async def helpme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 *Benvenuto! Ecco cosa puoi fare con il bot:*\n\n"
        "✏️ /insert – Inserisci i codici ISBN da monitorare\n"
        "📖 /list – Elenca i libri attualmente inseriti\n"
        "⏰ /settime HH:MM – Imposta l'orario per la notifica giornaliera\n"
        "🕵️ /checktime – Controlla l'orario delle notifiche\n"
        "🔥 /sales – Mostra le offerte attive in questo momento\n"
        "🔄 /refresh – Forza l’aggiornamento dei dati dei tuoi libri\n"
        "ℹ️ /help – Mostra questo elenco di comandi\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

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
            id=f"notify_{user_id}", replace_existing=True
        )

        await update.message.reply_text(f"✅ Orario notifiche impostato alle {context.args[0]}.")
    except ValueError:
        await update.message.reply_text("❌ Formato orario non valido. Usa HH:MM")

async def checktime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    time_str = user_settings.get(user_id, {}).get("time")
    if time_str:
        await update.message.reply_text(f"⏰ Riceverai le notifiche ogni giorno alle {time_str}.")
    else:
        await update.message.reply_text("⚠️ Non hai ancora impostato un orario. Usa /settime HH:MM")

async def insert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_state[user_id] = "inserimento"
    await update.message.reply_text("Inserisci uno o più codici ISBN (uno per riga e senza caratteri che non siano numeri all'interno del codice):")

async def list_isbn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lista = user_isbn_map.get(user_id, [])
    if not lista:
        await update.message.reply_text("Non hai ancora inserito ISBN.")
        return

    for book in lista:
        title = book.get('title', 'Titolo non disponibile')
        price = book.get('price', 'Prezzo non disponibile')
        discount = book.get('discount', 'Nessuno')
        isbn = book.get('isbn')

        text = (
            f"📚 *{title}*\n"
            f"💰 Prezzo: {price}\n"
            f"🔥 Sconto: {discount}\n"
            f"🔢 ISBN: {isbn}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Rimuovi", callback_data=f"delete:{isbn}")]
        ])

        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

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

async def saves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await notify_user(context.application, str(update.effective_user.id))
    
from telegram.ext import CallbackQueryHandler


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

        await query.edit_message_text("✅ Libro rimosso con successo.")


async def gestisci_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stato = user_state.get(user_id)
    if stato != "inserimento":
        await update.message.reply_text("Comando non riconosciuto. Usa /insert o /list.")
        return

    righe = update.message.text.splitlines()
    isbn_validi = [r.strip() for r in righe if r.strip().isdigit()]
    if not isbn_validi:
        await update.message.reply_text("Nessun codice ISBN valido trovato.")
        return

    user_isbn_map.setdefault(user_id, [])
    count = 0

    for isbn in isbn_validi:
        if any(item["isbn"] == isbn for item in user_isbn_map[user_id]):
            continue
        info = get_book_info(isbn)
        if not info:
            continue
        user_isbn_map[user_id].append({"isbn": isbn, **info})
        count += 1

    save_json(DATA_FILE, user_isbn_map)
    user_state[user_id] = None
    await update.message.reply_text(f"Salvati {count} nuovi ISBN.")

# === post_start per avviare i job dopo il polling ===
async def post_start(app):
    loop = asyncio.get_running_loop()
    schedule_user_jobs(app, scheduler, loop)

# === MAIN ===
def main():
    global scheduler
    scheduler = BackgroundScheduler()
    scheduler.start()

    app = ApplicationBuilder().token(TOKEN).post_init(post_start).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", helpme))
    app.add_handler(CommandHandler("insert", insert))
    app.add_handler(CommandHandler("list", list_isbn))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("saves", saves))
    app.add_handler(CommandHandler("settime", settime, block=False))
    app.add_handler(CommandHandler("checktime", checktime))
    app.add_handler(CallbackQueryHandler(delete_book_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gestisci_messaggio))

    print("Bot avviato...")
    app.run_polling()

if __name__ == "__main__":
    main()

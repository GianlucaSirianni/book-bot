import os
import json
import requests
import asyncio
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler


# === CONFIG ===
TOKEN = "7810048214:AAH8deqsPMVevWI5vhqXaR3GOaTZqILvmTQ"
DATA_FILE = "isbn_data.json"
user_state = {}  # { user_id: "inserimento" o None }

SETTINGS_FILE = "user_settings.json"

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

user_settings = load_settings()



# === Carica/salva dati ===
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

user_isbn_map = load_data()


# === Scraping titolo da ISBN ===
def get_title(isbn):
    url = f"https://blackwells.co.uk/bookshop/product/{isbn}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        title_tag = soup.find("h1", class_="product__name")
        return title_tag.text.strip() if title_tag else "Titolo non trovato"
    except Exception:
        return "Errore nel recupero titolo"
    
def get_price(isbn):
    url = f"https://blackwells.co.uk/bookshop/product/{isbn}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        main = soup.find("div", class_="product_top_half")
        if not main:
            return "Prezzo non trovato"

        price_tag = main.find("li", class_="product-price--current")
        return price_tag.text.strip() if price_tag else "Prezzo non trovato"
    except Exception as e:
        print(f"[{isbn}] Errore get_price: {e}")
        return "Errore nel recupero prezzo"

    
def get_discount(isbn):
    url = f"https://blackwells.co.uk/bookshop/product/{isbn}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        main = soup.find("div", class_="product_top_half")
        if not main:
            return None

        discount_tag = main.find("p", class_="product-price--discount")
        if discount_tag and "Save" in discount_tag.text and "€" in discount_tag.text:
            return discount_tag.text.strip()
        return None
    except Exception as e:
        print(f"[{isbn}] Errore get_discount: {e}")
        return None
    
async def check_daily_discounts(application):
    for user_id, books in user_isbn_map.items():
        offerte = []
        scaduti = []

        for book in books:
            isbn = book["isbn"]
            old_discount = book.get("discount")
            title = get_title(isbn)
            price = get_price(isbn)
            new_discount = get_discount(isbn)

            # Segnala se c'è un nuovo sconto
            if new_discount:
                offerte.append(
                    f"📚 {title}\n💰 {price}\n🔥 {new_discount}\n🔢 {isbn}\n"
                )

            # Segnala se lo sconto è finito
            if old_discount and not new_discount:
                scaduti.append(f"❌ Fine sconto per \"{title}\"")

            # aggiorna i dati salvati
            book["title"] = title
            book["price"] = price
            book["discount"] = new_discount

        save_data(user_isbn_map)

        if offerte or scaduti:
            msg = "📢 Aggiornamento offerte:\n\n"
            if offerte:
                msg += "🟢 Sconti:\n" + "\n".join(offerte) + "\n"
            if scaduti:
                msg += "🔴 Sconti terminati:\n" + "\n".join(scaduti)
        else:
            msg = "📭 Nessuna offerta oggi."

        await application.bot.send_message(chat_id=user_id, text=msg)

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if not context.args or not context.args[0].count(":") == 1:
        await update.message.reply_text("❗ Usa il formato: /settime HH:MM (es. 08:30)")
        return

    time_str = context.args[0]
    try:
        hour, minute = map(int, time_str.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError

        # Salva
        user_settings[user_id] = {"time": time_str}
        save_settings(user_settings)

        await update.message.reply_text(f"✅ Orario notifiche impostato alle {time_str}.")
    except ValueError:
        await update.message.reply_text("❌ Formato orario non valido. Usa HH:MM (es. 08:30)")

async def checktime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    time_str = user_settings.get(user_id, {}).get("time")

    if time_str:
        await update.message.reply_text(f"⏰ Riceverai le notifiche ogni giorno alle {time_str}.")
    else:
        await update.message.reply_text("⚠️ Non hai ancora impostato un orario. Usa /settime HH:MM")


async def notify_user(app, user_id):
    books = user_isbn_map.get(user_id, [])
    if not books:
        return

    offerte = []
    scaduti = []

    for book in books:
        isbn = book["isbn"]
        old_discount = book.get("discount")
        title = get_title(isbn)
        price = get_price(isbn)
        new_discount = get_discount(isbn)

        if new_discount:
            offerte.append(f"📚 {title}\n💰 {price}\n🔥 {new_discount}\n🔢 {isbn}\n")

        if old_discount and not new_discount:
            scaduti.append(f"❌ Fine sconto per \"{title}\"")

        # aggiorna dati
        book["title"] = title
        book["price"] = price
        book["discount"] = new_discount

    save_data(user_isbn_map)

    if offerte or scaduti:
        msg = "📢 Aggiornamento offerte:\n\n"
        if offerte:
            msg += "🟢 Nuovi sconti:\n" + "\n".join(offerte) + "\n"
        if scaduti:
            msg += "🔴 Sconti terminati:\n" + "\n".join(scaduti)
    else:
        msg = "📭 Nessuna offerta oggi."

    await app.bot.send_message(chat_id=user_id, text=msg)


def schedule_user_jobs(app, scheduler):
    for user_id, settings in user_settings.items():
        time_str = settings.get("time")
        if not time_str:
            continue  # Nessun orario impostato

        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            continue  # Orario malformato

        # Definisci job personalizzato
        scheduler.add_job(
            lambda uid=user_id: asyncio.run_coroutine_threadsafe(
                notify_user(app, uid),
                asyncio.get_event_loop()
            ),
            trigger="cron",
            hour=hour,
            minute=minute,
            id=f"notify_{user_id}",
            replace_existing=True
        )




    
async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if user_id not in user_isbn_map or not user_isbn_map[user_id]:
        await update.message.reply_text("Non hai ancora inserito ISBN.")
        return

    changes = []
    for book in user_isbn_map[user_id]:
        isbn = book["isbn"]
        old_price = book.get("price")
        old_discount = book.get("discount")
        old_title = book.get("title")

        new_title = get_title(isbn)
        new_price = get_price(isbn)
        new_discount = get_discount(isbn)

        # Confronta prezzo e sconto
        price_changed = new_price != old_price
        discount_changed = new_discount != old_discount

        if price_changed or discount_changed:
            message = f"🔺 Modifiche per \"{old_title or new_title}\":"
            if price_changed:
                message += f"\n💰 Prezzo: {old_price} → {new_price}"
            if discount_changed:
                message += f"\n🔥 Sconto: {old_discount or 'Nessuno'} → {new_discount or 'Nessuno'}"
            changes.append(message)

        # Aggiorna i dati nel file
        book["title"] = new_title
        book["price"] = new_price
        book["discount"] = new_discount

    save_data(user_isbn_map)

    if changes:
        await update.message.reply_text("🔄 Refresh completato. Ecco le modifiche:\n\n" + "\n\n".join(changes))
    else:
        await update.message.reply_text("❌ Nessun cambiamento trovato.")



async def offerte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_daily_discounts(context.application)
    await update.message.reply_text("✅ Controllo offerte forzato completato.")


# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ciao! Usa /insert per aggiungere codici ISBN e /list per visualizzarli.")

# === /insert ===
async def insert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_state[user_id] = "inserimento"
    await update.message.reply_text("Inserisci uno o più codici ISBN (uno per riga):")

# === /list ===
async def list_isbn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lista = user_isbn_map.get(user_id, [])

    if not lista:
        await update.message.reply_text("Non hai ancora inserito ISBN.")
    else:
        lines = []
        for item in lista:
            line = (
                f"📚 Title: {item['title']}\n"
                f"💰 Price: {item['price']}"
            )
            if item.get("discount"):
                line += f"\n🔥 Discount: {item['discount']}"
            line += f"\n🔢 ISBN: {item['isbn']}\n"
            lines.append(line)


        await update.message.reply_text("Ecco i tuoi libri:\n" + "\n".join(lines))

# === Messaggi ===
async def gestisci_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stato = user_state.get(user_id)

    if stato == "inserimento":
        righe = update.message.text.splitlines()
        isbn_validi = [r.strip() for r in righe if r.strip().isdigit()]

        if not isbn_validi:
            await update.message.reply_text("Nessun codice ISBN valido trovato.")
            return

        if user_id not in user_isbn_map:
            user_isbn_map[user_id] = []

        count = 0
        for isbn in isbn_validi:
            if any(item["isbn"] == isbn for item in user_isbn_map[user_id]):
                continue  # salta ISBN già presenti

            title = get_title(isbn)
            price = get_price(isbn)
            discount = get_discount(isbn)
            user_isbn_map[user_id].append({
                "isbn": isbn,
                "title": title,
                "price": price,
                "discount": discount
            })
            count += 1

        save_data(user_isbn_map)
        user_state[user_id] = None
        await update.message.reply_text(f"Salvati {count} nuovi ISBN.")
    else:
        await update.message.reply_text("Comando non riconosciuto. Usa /insert o /list.")

# === MAIN ===
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Crea il loop e lo scheduler
    loop = asyncio.get_event_loop()
    scheduler = BackgroundScheduler()

    # Registra i job personalizzati per ogni utente
    schedule_user_jobs(app, scheduler)

    scheduler.start()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("insert", insert))
    app.add_handler(CommandHandler("list", list_isbn))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("offerte", offerte))  # per forzare test
    app.add_handler(CommandHandler("settime", settime, block=False))
    app.add_handler(CommandHandler("checktime", checktime))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gestisci_messaggio))

    print("Bot avviato...")
    app.run_polling()



if __name__ == "__main__":
    main()

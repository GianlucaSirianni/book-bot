import os
import json
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# === CONFIG ===
TOKEN = "7810048214:AAH8deqsPMVevWI5vhqXaR3GOaTZqILvmTQ"
DATA_FILE = "isbn_data.json"
user_state = {}  # { user_id: "inserimento" o None }


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
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("insert", insert))
    app.add_handler(CommandHandler("list", list_isbn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gestisci_messaggio))

    print("Bot avviato...")
    app.run_polling()

if __name__ == "__main__":
    main()

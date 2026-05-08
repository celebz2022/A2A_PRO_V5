import time
import requests
import re
import psycopg2
from flask import Flask, request
import threading

# =========================
# CONFIG
# =========================
BOT_TOKEN = "8628606501:AAGMzru09_Hckmd_I1Xuyoel3GWiqHgeZS4"

DATABASE_URL = "postgresql://postgres:QjDEndVOQkUvjCBudiHANPYJzPjbxEHe@postgres.railway.internal:5432/railway"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# =========================
# CRYPTOBOT CONFIG
# =========================
CRYPTOBOT_API_TOKEN = "579100:AAi4VlDKXrA8XrA4CRRL1SW1J2idwuI9RShNN"

app = Flask(__name__)
pending_invoices = {}

# =========================
# FREE LIMITS
# =========================
FREE_LISTINGS = 5
FREE_SEARCHES = 5

user_usage = {}

def ensure_user(chat_id):
    if chat_id not in user_usage:
        user_usage[chat_id] = {"list": 0, "search": 0, "paid": False}

def is_blocked(chat_id, mode):
    ensure_user(chat_id)
    u = user_usage[chat_id]

    if u["paid"]:
        return False

    if mode == "list" and u["list"] >= FREE_LISTINGS:
        return True

    if mode == "search" and u["search"] >= FREE_SEARCHES:
        return True

    return False

# =========================
# DATABASE
# =========================
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS listings (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    location TEXT,
    beds TEXT,
    price TEXT,
    raw TEXT UNIQUE,
    created_at BIGINT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id BIGINT PRIMARY KEY,
    paid BOOLEAN DEFAULT FALSE,
    expires_at BIGINT
)
""")

conn.commit()

# =========================
# CRYPTOBOT INVOICE
# =========================
def create_invoice(user_id):

    url = "https://pay.crypt.bot/api/createInvoice"

    headers = {
        "Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN
    }

    data = {
        "asset": "USDT",
        "amount": 50,
        "description": "A2A Pro Subscription (3 Months)",
        "payload": str(user_id)
    }

    r = requests.post(url, headers=headers, json=data)
    res = r.json()

    if not res.get("ok"):
        print("CryptoBot error:", res)
        return None

    invoice = res["result"]
    pending_invoices[str(invoice["invoice_id"])] = user_id

    return invoice["pay_url"]

# =========================
# PAYWALL
# =========================
def paywall_message(chat_id):

    payment_url = create_invoice(chat_id)

    if not payment_url:
        send(chat_id, "❌ Payment error. Try again later.")
        return

    keyboard = {
        "inline_keyboard": [
            [{
                "text": "💳 Pay 50 AED / 3 Months",
                "url": payment_url
            }]
        ]
    }

    send(
        chat_id,
        "🚫 FREE LIMIT REACHED\n\n"
        "📦 Subscription: 50 AED / 3 Months\n"
        "✔ Unlimited Listings & Searches\n\n"
        "⚡ Instant activation after payment",
        keyboard
    )

# =========================
# WEBHOOK (CryptoBot)
# =========================
@app.route("/crypto-webhook", methods=["POST"])
def crypto_webhook():

    data = request.json

    try:
        user_id = int(data.get("payload"))

        cur.execute("""
            INSERT INTO subscriptions (user_id, paid, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET paid=EXCLUDED.paid, expires_at=EXCLUDED.expires_at
        """, (
            user_id,
            True,
            int(time.time()) + (90 * 24 * 60 * 60)
        ))

        conn.commit()

        user_usage[user_id] = {
            "list": 0,
            "search": 0,
            "paid": True
        }

        send(user_id, "✅ Payment successful!\n🚀 Access unlocked")

        return {"ok": True}

    except Exception as e:
        print("Webhook error:", e)
        return {"ok": False}, 500

# =========================
# SEND MESSAGE
# =========================
def send(chat_id, text, reply_markup=None):

    payload = {"chat_id": chat_id, "text": text}

    if reply_markup:
        payload["reply_markup"] = reply_markup

    requests.post(BASE_URL + "/sendMessage", json=payload)

# =========================
# MENU (NO MANAGE LISTINGS)
# =========================
def inline_menu():
    return {
        "inline_keyboard": [
            [{"text": "🏠 List Property", "callback_data": "list"}],
            [{"text": "🔎 Find Property", "callback_data": "search"}],
            [{"text": "🔄 Restart", "callback_data": "restart"}]
        ]
    }

def bottom_menu():
    return {
        "keyboard": [
            ["🏠 List Property", "🔎 Find Property"],
            ["🔄 Restart"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

# =========================
# WELCOME MESSAGE (RESTORED)
# =========================
WELCOME_MESSAGE = (
"🚀 Welcome to A2A_PRO Marketplace\n"
"👉 https://t.me/a2aprobot\n\n"
"🏠 How to List Property:\n"
"1. Tap List Property\n"
"2. Start sending listings (MULTI MODE)\n"
"3. Include WhatsApp link\n\n"
"Example:\n"
"Damac Heights 3BR price: 3.5M\n"
"‼️ Mandatory WhatsApp Link https://wa.me/971XXXXXXXXX\n\n"
"🔎 Search examples:\n"
"- Damac Height 3BR under 4M\n"
"- Springs 4BR under 6M\n\n"
)

# =========================
# MAIN MENU
# =========================
def send_main_menu(chat_id):

    send(chat_id, WELCOME_MESSAGE, inline_menu())

    requests.post(BASE_URL + "/sendMessage", json={
        "chat_id": chat_id,
        "text": "👇 Quick Menu Enabled",
        "reply_markup": bottom_menu()
    })

# =========================
# MEMORY
# =========================
user_state = {}

# =========================
# CLEAN + SCORE
# =========================
def clean_text(t):
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def score(query, text):
    q = clean_text(query)
    t = clean_text(text)

    s = 0
    if q in t:
        s += 2

    for w in q.split():
        if w in t:
            s += 0.5

    return s

# =========================
# CALLBACK HANDLER (NO MANAGE)
# =========================
def handle_callback(cb):

    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]

    ensure_user(chat_id)

    requests.post(
        BASE_URL + "/answerCallbackQuery",
        data={"callback_query_id": cb["id"]}
    )

    if data == "list":

        if is_blocked(chat_id, "list"):
            paywall_message(chat_id)
            return

        user_state[chat_id] = "listing"
        send(chat_id, "🏠 LISTING MODE ACTIVE\nSend your listings with WhatsApp link")
        return

    if data == "search":
        user_state[chat_id] = None
        send(chat_id, "🔎 Type your search")
        return

    if data == "restart":
        user_state[chat_id] = None
        send_main_menu(chat_id)
        return

# =========================
# FLASK START
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

# =========================
# BOT LOOP
# =========================
offset = None
print("🚀 BOT RUNNING")

while True:
    try:
        data = requests.get(
            BASE_URL + "/getUpdates",
            params={"timeout": 10, "offset": offset}
        ).json()

        for update in data.get("result", []):

            offset = update["update_id"] + 1

            if "callback_query" in update:
                handle_callback(update["callback_query"])
                continue

            msg = update.get("message")
            if not msg:
                continue

            text = msg.get("text", "")
            chat_id = msg["chat"]["id"]

            ensure_user(chat_id)

            # START
            if "/start" in text.lower():
                user_state[chat_id] = None
                send_main_menu(chat_id)
                continue

            # LIST BUTTON
            if text == "🏠 List Property":

                if is_blocked(chat_id, "list"):
                    paywall_message(chat_id)
                    continue

                user_state[chat_id] = "listing"
                send(chat_id, "🏠 LISTING MODE ON")
                continue

            # SEARCH BUTTON
            if text == "🔎 Find Property":

                if is_blocked(chat_id, "search"):
                    paywall_message(chat_id)
                    continue

                send(chat_id, "🔎 Type your search")
                continue

            # RESTART
            if text == "🔄 Restart":
                user_state[chat_id] = None
                send_main_menu(chat_id)
                continue

            # LISTING MODE
            if user_state.get(chat_id) == "listing":

                if "wa.me" not in text:
                    send(chat_id, "❌ Add WhatsApp link")
                    continue

                cur.execute("""
                    INSERT INTO listings (user_id, raw, created_at)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (raw) DO NOTHING
                """, (chat_id, text, int(time.time())))

                conn.commit()

                user_usage[chat_id]["list"] += 1

                send(chat_id, "✅ Saved! Send another listing.")
                continue

            # SEARCH MODE
            if is_blocked(chat_id, "search"):
                paywall_message(chat_id)
                continue

            user_usage[chat_id]["search"] += 1

            cur.execute("SELECT raw FROM listings")
            rows = cur.fetchall()

            results = []

            for r in rows:
                if score(text, r[0]) > 1:
                    results.append(r[0])

            if results:
                send(chat_id, "🎯 MATCHES\n\n" + "\n\n".join(results[:5]))
            else:
                send(chat_id, "⏳ No matches found")

        time.sleep(1)

    except Exception as e:
        print("ERROR:", e)
        time.sleep(5)

import os
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

CRYPTOBOT_API_TOKEN = "579100:AALHabP1Hs3yFD1y6InghzZPD9dfyj7M6gG"

app = Flask(__name__)
PORT = int(os.environ.get("PORT", 8080))

# =========================
# LIMITS
# =========================
FREE_LISTINGS = 1
FREE_SEARCHES = 5

user_usage = {}

def ensure_user(chat_id):
    if chat_id not in user_usage:
        user_usage[chat_id] = {
            "list": 0,
            "search": 0,
            "paid": False
        }

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
# BOT STATE
# =========================
user_state = {}

# =========================
# SEND
# =========================
def send(chat_id, text, reply_markup=None):

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    requests.post(BASE_URL + "/sendMessage", json=payload)

# =========================
# CREATE CRYPTO INVOICE
# =========================
def create_invoice(chat_id):

    try:

        r = requests.post(
            "https://pay.crypt.bot/api/createInvoice",
            headers={
                "Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN
            },
            json={
                "asset": "USDT",
                "amount": 5,
                "description": "A2A_PRO Premium Access - 3 Months",
                "payload": str(chat_id),
                "allow_comments": False,
                "allow_anonymous": False
            }
        ).json()

        print("INVOICE RESPONSE:", r)

        if not r or not r.get("ok"):
            print("CRYPTO ERROR:", r)
            return None

        return r["result"]["pay_url"]

    except Exception as e:
        print("INVOICE ERROR:", e)
        return None

# =========================
# PAYWALL (FIXED ONLY HERE)
# =========================
def paywall_message(chat_id):

    pay_url = create_invoice(chat_id)

    message = (
        "🚫 FREE TRIAL FINISHED\n\n"
        "💎 Subscribe to continue using A2A_PRO\n\n"
        "📦 Plan: 5 USD / 3 Months\n"
        "✔ Unlimited Listings\n"
        "✔ Unlimited Searches\n\n"
        "👇 Tap below to activate access"
    )

    keyboard = None

    if pay_url:
        keyboard = {
            "inline_keyboard": [[{
                "text": "💳 Subscribe & Pay (USDT)",
                "url": pay_url
            }]]
        }
    else:
        message += "\n\n⚠️ Payment system temporarily unavailable. Please try again in a few seconds."

    send(chat_id, message, keyboard)

# =========================
# CLEAN + SCORE
# =========================
def clean_text(t):

    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)

    return re.sub(r"\s+", " ", t).strip()

def score(q, t):

    q = clean_text(q)
    t = clean_text(t)

    s = 0

    if q in t:
        s += 2

    for w in q.split():
        if w in t:
            s += 0.5

    return s

# =========================
# MENU
# =========================
def bottom_menu():
    return {
        "keyboard": [
            ["🏠 List Property", "🔎 Find Property"],
            ["📂 Manage Listings", "🔄 Restart"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

WELCOME_MESSAGE = (
"🚀 Welcome to A2A_PRO Marketplace\n"
"👉 https://t.me/a2aprobot\n\n"
"🏠 How to List Property:\n"
"1. Tap List Property\n"
"2. Start sending listings\n"
"3. Include WhatsApp link\n\n"
"Example:\n"
"Damac Heights 3BR price: 3.5M\n"
"‼️Mandatory Whatsapp Link https://wa.me/971XXXXXXXXX\n\n"
"🔎 Search examples:\n"
"- Damac Height 3BR under 4M\n"
"- Springs 4BR under 6M\n\n"
)

def send_main_menu(chat_id):

    send(chat_id, WELCOME_MESSAGE, {
        "inline_keyboard": [
            [{"text": "🏠 List Property", "callback_data": "list"}],
            [{"text": "🔎 Find Property", "callback_data": "search"}],
            [{"text": "📂 Manage Listings", "callback_data": "manage"}],
            [{"text": "🔄 Restart", "callback_data": "restart"}]
        ]
    })

    requests.post(BASE_URL + "/sendMessage", json={
        "chat_id": chat_id,
        "text": "👇 Quick Menu Enabled",
        "reply_markup": bottom_menu()
    })

# =========================
# CALLBACK HANDLER
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

        cur.execute(
            "SELECT COUNT(*) FROM listings WHERE user_id=%s",
            (chat_id,)
        )

        total_listings = cur.fetchone()[0]

        if total_listings >= FREE_LISTINGS and not user_usage[chat_id]["paid"]:
            paywall_message(chat_id)
            return

        user_state[chat_id] = "listing"

        send(chat_id, "🏠 LISTING MODE ACTIVE")

        return

    if data == "search":

        user_state[chat_id] = None

        send(chat_id, "🔎 Type search")

        return

    if data == "manage":

        cur.execute(
            "SELECT id, raw FROM listings WHERE user_id=%s",
            (chat_id,)
        )

        rows = cur.fetchall()

        if not rows:
            send(chat_id, "📭 No listings found")
            return

        for r in rows[:50]:

            keyboard = {
                "inline_keyboard": [[{
                    "text": "❌ Delete",
                    "callback_data": f"del_{r[0]}"
                }]]
            }

            send(chat_id, f"📄 {r[1]}", keyboard)

        return

    if data.startswith("del_"):

        listing_id = int(data.split("_")[1])

        cur.execute(
            "DELETE FROM listings WHERE id=%s AND user_id=%s",
            (listing_id, chat_id)
        )

        conn.commit()

        send(chat_id, "🗑 Deleted successfully")

        return

    if data == "restart":

        user_state[chat_id] = None

        send_main_menu(chat_id)

# =========================
# BOT LOOP
# =========================
def run_bot():

    print("🚀 BOT RUNNING")

    offset = None

    while True:

        try:

            data = requests.get(
                BASE_URL + "/getUpdates",
                params={
                    "timeout": 10,
                    "offset": offset
                }
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

                if "/start" in text.lower():

                    user_state[chat_id] = None

                    send_main_menu(chat_id)

                    continue

                if text == "🏠 List Property":

                    cur.execute(
                        "SELECT COUNT(*) FROM listings WHERE user_id=%s",
                        (chat_id,)
                    )

                    total_listings = cur.fetchone()[0]

                    if total_listings >= FREE_LISTINGS and not user_usage[chat_id]["paid"]:
                        paywall_message(chat_id)
                        continue

                    user_state[chat_id] = "listing"

                    send(chat_id, "🏠 LISTING MODE ACTIVE\n\nSend your listing with WhatsApp link.")

                    continue

                if text == "🔎 Find Property":

                    if is_blocked(chat_id, "search"):
                        paywall_message(chat_id)
                        continue

                    user_state[chat_id] = None

                    send(chat_id, "🔎 Type search")

                    continue

                if text == "📂 Manage Listings":

                    handle_callback({
                        "message": {"chat": {"id": chat_id}},
                        "data": "manage",
                        "id": "manual"
                    })

                    continue

                if text == "🔄 Restart":

                    user_state[chat_id] = None

                    send_main_menu(chat_id)

                    continue

                if user_state.get(chat_id) == "listing":

                    if "wa.me" not in text:
                        send(chat_id, "❌ Add WhatsApp link")
                        continue

                    cur.execute("""
                        INSERT INTO listings (
                            user_id,
                            raw,
                            created_at
                        )
                        VALUES (%s,%s,%s)
                        ON CONFLICT DO NOTHING
                    """, (
                        chat_id,
                        text,
                        int(time.time())
                    ))

                    conn.commit()

                    user_usage[chat_id]["list"] += 1

                    send(chat_id, "✅ Saved")

                    continue

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

                    send(chat_id, "🎯 RESULTS\n\n" + "\n\n".join(results[:5]))

                else:

                    send(chat_id, "❌ No results")

        except Exception as e:

            print("ERROR:", e)

            time.sleep(3)

@app.route("/crypto-webhook", methods=["POST"])
def crypto_webhook():

    try:

        data = request.json

        user_id = int(data.get("payload"))

        cur.execute("""
            INSERT INTO subscriptions (
                user_id,
                paid,
                expires_at
            )
            VALUES (%s,%s,%s)
            ON CONFLICT (user_id)
            DO UPDATE SET paid=EXCLUDED.paid
        """, (
            user_id,
            True,
            int(time.time()) + 90*24*60*60
        ))

        conn.commit()

        user_usage[user_id] = {
            "list": 0,
            "search": 0,
            "paid": True
        }

        send(user_id, "✅ Payment successful!\nAccess unlocked 🚀")

        return {"ok": True}

    except Exception as e:

        print("Webhook error:", e)

        return {"ok": False}

@app.route("/", methods=["GET"])
def home():
    return "A2A_PRO bot is running 🚀"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_bot).start()

run_flask()

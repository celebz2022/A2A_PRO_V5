import time
import requests
import re
import psycopg2

# =========================
# CONFIG
# =========================
BOT_TOKEN = "8628606501:AAGMzru09_Hckmd_I1Xuyoel3GWiqHgeZS4"

DATABASE_URL = "postgresql://postgres:QjDEndVOQkUvjCBudiHANPYJzPjbxEHe@postgres.railway.internal:5432/railway"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# =========================
# SUBSCRIPTION CONFIG (NEW)
# =========================
PAYMENT_LINK = "https://exchange.mercuryo.io/?currency=USDT&fiat_amount=50&fiat_currency=AED&merchant_transaction_id=95b6c29c-e252-47b5-a636-0bd799616ad0&network=BINANCESMARTCHAIN&payment_method=card&signature=985a4c3da9c8b76d5e2afa463c2d945f9b3b772ae403e87ef92068bd8e149b56e6447235855cc31f9f75f7b29488f72524a15b3846a0538845e5d6aeff5ec207&theme=trustwallet&utm_medium=referral&utm_source=TrustWallet&widget_id=d13d7a03-f965-4688-b35a-9d208819ff4b&address=0xC329baa91e2dc30A321e0CB937A05D691A5De503"
FREE_LISTINGS = 5
FREE_SEARCHES = 5

user_usage = {}
# structure:
# user_usage[user_id] = {"list": 0, "search": 0, "paid": False}

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

def paywall_message():
    return (
        "🚫 FREE LIMIT REACHED\n\n"
        "You have used your free access.\n\n"
        "📦 Subscription: 50 AED / 3 Months\n"
        "✔ Unlimited Listings & Searches\n\n"
        f"💳 Pay here: {PAYMENT_LINK}\n\n"
        "After payment, contact support to activate access."
    )

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
conn.commit()

# =========================
# MEMORY
# =========================
user_state = {}

# =========================
# CLEAN TEXT
# =========================
def clean_text(t):
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

# =========================
# SCORE
# =========================
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
# SEND MESSAGE
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
# INLINE MENU (TOP)
# =========================
def inline_menu():
    return {
        "inline_keyboard": [
            [{"text": "🏠 List Property", "callback_data": "list"}],
            [{"text": "🔎 Find Property", "callback_data": "search"}],
            [{"text": "📂 Manage Listings", "callback_data": "manage"}],
            [{"text": "🔄 Restart", "callback_data": "restart"}]
        ]
    }

# =========================
# BOTTOM MENU (PERSISTENT)
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

# =========================
# WELCOME MESSAGE
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
"*‼️Mandatory Whatsapp Link https://wa.me/971XXXXXXXXX\n\n"
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
# CALLBACK HANDLER
# =========================
def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]

    ensure_user(chat_id)

    requests.post(BASE_URL + "/answerCallbackQuery",
                  data={"callback_query_id": cb["id"]})

    if data == "list":

        if is_blocked(chat_id, "list"):
            send(chat_id, paywall_message())
            return

        user_state[chat_id] = "listing"
        send(chat_id,
             "🏠 LISTING MODE ACTIVE (MULTI)\n\n"
             "You can send unlimited listings.\n"
             "When done, choose another option.\n\n"
             "Example:\n"
             "Damac Heights 3BR price: 3.5M\n"
             "‼️Mandatory Whatsapp Link https://wa.me/971XXXXXXXXX")

    elif data == "search":
        user_state[chat_id] = None
        send(chat_id, "🔎 Type your search")

    elif data == "manage":
        cur.execute("SELECT id, raw FROM listings WHERE user_id=%s", (chat_id,))
        rows = cur.fetchall()

        if not rows:
            send(chat_id, "📭 No listings found")
            return

        for r in rows[:10]:
            keyboard = {
                "inline_keyboard": [
                    [{
                        "text": "❌ Delete",
                        "callback_data": f"del_{r[0]}"
                    }]
                ]
            }

            send(chat_id, f"📄 {r[1]}", keyboard)

    elif data.startswith("del_"):
        listing_id = int(data.split("_")[1])

        cur.execute(
            "DELETE FROM listings WHERE id=%s AND user_id=%s",
            (listing_id, chat_id)
        )
        conn.commit()

        send(chat_id, "🗑 Deleted successfully")

    elif data == "restart":
        user_state[chat_id] = None
        send_main_menu(chat_id)

# =========================
# GET UPDATES
# =========================
def get_updates(offset=None):
    return requests.get(BASE_URL + "/getUpdates", params={
        "timeout": 10,
        "offset": offset
    }).json()

# =========================
# MAIN LOOP
# =========================
offset = None
print("🚀 BOT RUNNING")

while True:
    try:
        data = get_updates(offset)

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

                if is_blocked(chat_id, "list"):
                    send(chat_id, paywall_message())
                    continue

                user_state[chat_id] = "listing"
                send(chat_id, "🏠 LISTING MODE ON")
                continue

            if text == "🔎 Find Property":

                if is_blocked(chat_id, "search"):
                    send(chat_id, paywall_message())
                    continue

                user_state[chat_id] = None
                send(chat_id, "🔎 Type your search")
                continue

            if text == "📂 Manage Listings":
                cur.execute("SELECT id, raw FROM listings WHERE user_id=%s", (chat_id,))
                rows = cur.fetchall()

                if not rows:
                    send(chat_id, "📭 No listings")
                    continue

                for r in rows[:10]:
                    send(chat_id, f"📄 {r[1]}")
                continue

            if text == "🔄 Restart":
                user_state[chat_id] = None
                send_main_menu(chat_id)
                continue

            # =========================
            # LISTING MODE
            # =========================
            if user_state.get(chat_id) == "listing":

                if is_blocked(chat_id, "list"):
                    send(chat_id, paywall_message())
                    continue

                if "wa.me" not in text:
                    send(chat_id, "❌ Add WhatsApp link")
                    continue

                try:
                    cur.execute("""
                        INSERT INTO listings (user_id, location, beds, price, raw, created_at)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (raw) DO NOTHING
                    """, (chat_id, None, None, None, text, int(time.time())))
                    conn.commit()

                    user_usage[chat_id]["list"] += 1

                except Exception as e:
                    print("DB ERROR:", e)

                send(chat_id, "✅ Saved! Send another listing.")
                continue

            # =========================
            # SEARCH MODE
            # =========================
            if is_blocked(chat_id, "search"):
                send(chat_id, paywall_message())
                continue

            user_usage[chat_id]["search"] += 1

            cur.execute("SELECT raw FROM listings")
            rows = cur.fetchall()

            results = []

            for r in rows:
                txt = r[0]
                s = score(text, txt)

                if s > 1:
                    results.append((txt, s))

            results.sort(key=lambda x: x[1], reverse=True)

            if results:
                out = "🎯 MATCHES\n\n"
                for r in results[:5]:
                    out += r[0] + "\n\n"
                send(chat_id, out)
            else:
                send(chat_id, "⏳ No matches found")

        time.sleep(1)

    except Exception as e:
        print("ERROR:", e)
        time.sleep(5)

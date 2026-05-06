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
# SAFE SEND
# =========================
def send(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    r = requests.post(BASE_URL + "/sendMessage", json=payload)

    if not r.ok:
        print("Telegram Error:", r.text)

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
"https://wa.me/971XXXXXXXXX\n\n"
"🔎 Search examples:\n"
"- Damac under 4M\n"
"- Emaar under 16M\n"
"- Lake Terrace 3BR under 2.6M\n\n"
"⚡ Multi-listing mode enabled"
)

# =========================
# MENU
# =========================
def send_main_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🏠 List Property", "callback_data": "list"}],
            [{"text": "🔎 Find Property", "callback_data": "search"}],
            [{"text": "📂 Manage Listings", "callback_data": "manage"}],
            [{"text": "🔄 Restart", "callback_data": "restart"}]
        ]
    }

    send(chat_id, WELCOME_MESSAGE, keyboard)

# =========================
# CALLBACK HANDLER
# =========================
def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]

    requests.post(
        BASE_URL + "/answerCallbackQuery",
        data={"callback_query_id": cb["id"]}
    )

    # EXIT LISTING MODE WHEN SWITCHING
    if data in ["search", "manage", "restart"]:
        user_state[chat_id] = None

    # START MULTI-LISTING MODE
    if data == "list":
        user_state[chat_id] = "listing"

        send(chat_id,
        "🏠 LISTING MODE ACTIVE (MULTI)\n\n"
        "You can send unlimited listings.\n"
        "When done, choose another option.\n\n"
        "Example:\n"
        "Damac Heights 3BR price: 3.5M\n"
        "https://wa.me/971XXXXXXXXX")

    elif data == "search":
        send(chat_id, "🔎 Type your search")

    elif data == "manage":
        cur.execute("SELECT id, raw FROM listings WHERE user_id=%s", (chat_id,))
        rows = cur.fetchall()

        if not rows:
            send(chat_id, "📭 No listings found.")
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
print("🚀 BOT RUNNING (MULTI-LISTING MODE ENABLED)")

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

            # START
            if "/start" in text.lower():
                user_state[chat_id] = None
                send_main_menu(chat_id)
                continue

            # SAVE LISTING (MULTI MODE)
            if user_state.get(chat_id) == "listing":

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
                except Exception as e:
                    print("DB ERROR:", e)

                send(chat_id, "✅ Saved! Send another listing or change mode.")
                continue

            # SEARCH
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

import os
import time
import requests
import re
import psycopg2
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# =========================
# ENV VARIABLES (IMPORTANT)
# =========================
BOT_TOKEN = os.getenv("8628606501:AAGMzru09_Hckmd_I1Xuyoel3GWiqHgeZS4")
DATABASE_URL = os.getenv("DATABASE_URL")

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# =========================
# AI MODEL
# =========================
model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

# =========================
# MEMORY
# =========================
shown_cache = set()
user_state = {}

# =========================
# DATABASE (POSTGRES)
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
# TEXT CLEANING
# =========================
def clean_text(t):
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

# =========================
# SEND MESSAGE
# =========================
def send(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        data["reply_markup"] = reply_markup

    requests.post(BASE_URL + "/sendMessage", json=data)

# =========================
# START MENU
# =========================
def send_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🏠 List Property", "callback_data": "list"}],
            [{"text": "🔎 Find Property", "callback_data": "search"}],
            [{"text": "📂 Manage Listings", "callback_data": "manage"}]
        ]
    }

    send(chat_id, "🚀 Welcome to A2A Marketplace", keyboard)

# =========================
# SCORE MATCHING
# =========================
def score(query, text):
    try:
        return cosine_similarity(
            [model.encode(query)],
            [model.encode(text)]
        )[0][0]
    except:
        return 0

# =========================
# CALLBACK HANDLER
# =========================
def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]

    requests.post(BASE_URL + "/answerCallbackQuery",
                  data={"callback_query_id": cb["id"]})

    if data == "list":
        user_state[chat_id] = "listing"
        send(chat_id,
             "🏠 Send your listing:\nExample:\nDamac 3BR 3.5M\nhttps://wa.me/971XXXX")

    elif data == "search":
        send(chat_id, "🔎 Type your search (e.g. Damac 3BR under 4M)")

    elif data == "manage":
        cur.execute("SELECT id, raw FROM listings WHERE user_id=%s", (chat_id,))
        rows = cur.fetchall()

        if not rows:
            send(chat_id, "No listings found.")
            return

        for r in rows:
            send(chat_id, f"📄 {r[1]}")

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
print("BOT RUNNING...")

while True:
    data = get_updates(offset)

    for update in data.get("result", []):
        offset = update["update_id"] + 1

        # CALLBACKS
        if "callback_query" in update:
            handle_callback(update["callback_query"])
            continue

        msg = update.get("message")
        if not msg:
            continue

        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        # START
        if "/start" in text:
            user_state[chat_id] = None
            send_menu(chat_id)
            continue

        # SAVE LISTING
        if user_state.get(chat_id) == "listing":
            if "wa.me" not in text:
                send(chat_id, "❌ Add WhatsApp link")
                continue

            try:
                cur.execute("""
                    INSERT INTO listings (user_id, location, beds, price, raw, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (chat_id, None, None, None, text, int(time.time())))
                conn.commit()
            except:
                pass

            user_state[chat_id] = None
            send(chat_id, "✅ Saved!")
            continue

        # SEARCH
        cur.execute("SELECT * FROM listings")
        rows = cur.fetchall()

        results = []

        for r in rows:
            txt = r[5]
            s = score(text, txt)
            if s > 0.5:
                results.append((txt, s))

        results.sort(key=lambda x: x[1], reverse=True)

        if results:
            out = "🎯 MATCHES:\n\n"
            for r in results[:5]:
                out += f"{r[0]}\n\n"
            send(chat_id, out)
        else:
            send(chat_id, "No matches found")

    time.sleep(1)

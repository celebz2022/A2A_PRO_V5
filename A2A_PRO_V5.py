import time
import requests
import re
import psycopg2

# =========================
# CONFIG (HARD-CODED)
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
# CLEAN TEXT
# =========================
def clean_text(t):
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# =========================
# FILTERS
# =========================
INTENT_WORDS = {
    "under", "above", "below", "over",
    "best", "op", "distress", "urgent",
    "reduced", "market", "price"
}

PRICE_PATTERN = re.compile(r"\d+(\.\d+)?m", re.IGNORECASE)
BED_PATTERN = re.compile(r"\b(\d+\s*(br|bed|beds|bedroom|bedrooms))\b", re.IGNORECASE)


def clean_query(query):
    q = query.lower()
    q = PRICE_PATTERN.sub(" ", q)
    words = q.split()
    words = [w for w in words if w not in INTENT_WORDS]
    return " ".join(words).strip()


# =========================
# AI SCORE
# =========================
def ai_score(a, b):
    try:
        return cosine_similarity(
            [model.encode(a)],
            [model.encode(b)]
        )[0][0]
    except:
        return 0


def score(query, text):
    q = clean_query(query)
    t = text.lower()

    s = 0

    if q in t:
        s += 3.0

    for w in q.split():
        if w in t:
            s += 0.5

    s += ai_score(q, t) * 1.2

    return s


# =========================
# SEND MESSAGE
# =========================
def send(chat_id, text):
    requests.post(BASE_URL + "/sendMessage", data={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })


# =========================
# MENU
# =========================
def send_main_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🏠 List Property", "callback_data": "list"}],
            [{"text": "🔎 Find Property", "callback_data": "search"}],
            [{"text": "📂 Manage My Listings", "callback_data": "manage"}],
            [{"text": "🔄 Restart", "callback_data": "restart"}]
        ]
    }

    requests.post(BASE_URL + "/sendMessage", json={
        "chat_id": chat_id,
        "text": WELCOME_MESSAGE,
        "reply_markup": keyboard
    })


# =========================
# CALLBACK HANDLER
# =========================
def handle_callback(update):
    cb = update["callback_query"]
    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]

    requests.post(BASE_URL + "/answerCallbackQuery", data={
        "callback_query_id": cb["id"]
    })

    if data == "list":
        user_state[chat_id] = "waiting_listing"
        send(chat_id,
"🏠 Send your property listing:\n\n"
"Example:\nDamac Heights 3BR Vacant price: 3.5M\n\n"
"⚠️ Mandatory: Include your WhatsApp link\n"
"Format: https://wa.me/971XXXXXXXXX"
)

    elif data == "search":
        send(chat_id, "🔎 Search:\nExample:\nDamac Height under 4M, emaar oasis under 16M, Lake terrace 3BR under 2.6M")

    elif data == "restart":
        user_state[chat_id] = None
        send_main_menu(chat_id)

    elif data == "manage":
        cur.execute("SELECT id, raw FROM listings WHERE user_id=?", (chat_id,))
        rows = cur.fetchall()

        if not rows:
            send(chat_id, "📭 You have no listings yet.")
            return

        for r in rows[:10]:
            listing_id = r[0]
            listing_text = r[1]

            keyboard = {
                "inline_keyboard": [
                    [{"text": "❌ Delete", "callback_data": f"del_{listing_id}"}]
                ]
            }

            requests.post(BASE_URL + "/sendMessage", json={
                "chat_id": chat_id,
                "text": f"📄 {listing_text}",
                "reply_markup": keyboard
            })

    elif data.startswith("del_"):
        listing_id = int(data.split("_")[1])

        cur.execute(
            "DELETE FROM listings WHERE id=? AND user_id=?",
            (listing_id, chat_id)
        )
        conn.commit()

        send(chat_id, f"🗑 Listing #{listing_id} deleted.")


# =========================
# MATCH ENGINE
# =========================
def find_matches(query, rows):
    results = []

    q_clean = clean_query(query)
    local_seen = set()

    for r in rows:
        text = r[5]
        if not text:
            continue

        t_clean = clean_text(text)

        if t_clean in shown_cache:
            continue

        if t_clean in local_seen:
            continue

        local_seen.add(t_clean)

        if t_clean == q_clean:
            continue

        if any(x in t_clean for x in ["under market", "distress deal", "op deal"]):
            continue

        q_beds = BED_PATTERN.findall(query.lower())
        if q_beds:
            if not BED_PATTERN.search(text.lower()):
                continue

        meaningful_words = [w for w in q_clean.split() if w not in INTENT_WORDS]
        if meaningful_words:
            if not any(w in t_clean for w in meaningful_words):
                continue

        s = score(query, text)

        if s < 1.2:
            continue

        results.append((r, s))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:5]


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
print("🚀 BOT RUNNING (VALIDATED LISTING MODE)")

while True:
    data = get_updates(offset)

    for update in data.get("result", []):
        offset = update["update_id"] + 1

        if "callback_query" in update:
            handle_callback(update)
            continue

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue

        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        if text and "/start" in text.lower():
            user_state[chat_id] = None
            send_main_menu(chat_id)
            continue

        # ✅ SAVE ONLY VALID LISTINGS
        if user_state.get(chat_id) == "waiting_listing":

            if "wa.me/" not in text:
                send(chat_id, "❌ Please include WhatsApp link.\nhttps://wa.me/971XXXXXXXXX")
                continue

            if not any(x in text.lower() for x in ["br", "bed", "price", "m"]):
                send(chat_id, "❌ Invalid format.\nExample:\nDamac Heights 3BR price: 3.5M\nhttps://wa.me/971XXXXXXXXX")
                continue

            try:
                cur.execute(
                    "INSERT INTO listings VALUES (NULL,?,?,?,?,?,?)",
                    (chat_id, None, None, None, text, int(time.time()))
                )
                conn.commit()
            except:
                pass

            user_state[chat_id] = None
            send(chat_id, "✅ Listing saved successfully!")
            continue

        # SEARCH
        cur.execute("SELECT * FROM listings")
        rows = cur.fetchall()

        matches = find_matches(text, rows)

        if matches:
            out = "🎯 MATCHES\n\n"

            for m, s in matches:
                prop = m[5]
                key = clean_text(prop)

                if key in shown_cache:
                    continue

                shown_cache.add(key)

                out += f"""🔥 MATCH ({round(s,2)})
📄 {prop}

"""

            send(chat_id, out)

        else:
            send(chat_id, "⏳ No AI match yet...")

    time.sleep(1)

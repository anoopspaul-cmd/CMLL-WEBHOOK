import os
import json
import requests
from flask import Flask, request, jsonify
import anthropic
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "cmllverify")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1183608764834373")
CLAUDE_API_KEY  = os.environ.get("CLAUDE_API_KEY", "")
NOTIFY_API_KEY  = os.environ.get("NOTIFY_API_KEY", "cmll_notify_key")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_FILE = "/etc/secrets/google_credentials.json"

conversation_history = {}


# ─── GOOGLE SHEETS: GET RECIPIENTS ───────────────────────────────────────────
def get_recipients(group="directors"):
    """Fetch recipients from Google Sheet filtered by group and active=YES"""
    try:
        with open(GOOGLE_CREDS_FILE) as f:
        creds_dict = json.load(f)
        scopes     = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds      = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client     = gspread.authorize(creds)
        sheet      = client.open_by_key(GOOGLE_SHEET_ID).sheet1
        rows       = sheet.get_all_records()

        # Filter by group and active status
        if group == "all":
            recipients = [r for r in rows if str(r.get("active", "")).upper() == "YES"]
        else:
            recipients = [
                r for r in rows
                if str(r.get("group", "")).lower() == group.lower()
                and str(r.get("active", "")).upper() == "YES"
            ]

        print(f"Found {len(recipients)} recipients for group '{group}'")
        return recipients

    except Exception as e:
        print(f"Google Sheets error: {e}")
        return []


# ─── WEBHOOK VERIFICATION ─────────────────────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


# ─── RECEIVE INCOMING WHATSAPP → CLAUDE REPLIES ───────────────────────────────
@app.route("/webhook", methods=["POST"])
def receive_message():
    body = request.get_json()
    try:
        changes = body["entry"][0]["changes"][0]["value"]
        if "messages" not in changes:
            return jsonify({"status": "ok"}), 200
        message     = changes["messages"][0]
        from_number = message["from"]
        if message.get("type") == "text":
            user_text = message["text"]["body"]
            print(f"Incoming from {from_number}: {user_text}")
            ai_reply = get_claude_reply(from_number, user_text)
            send_whatsapp_message(from_number, ai_reply)
    except Exception as e:
        print(f"Error: {e}")
    return jsonify({"status": "ok"}), 200


# ─── EVENT-DRIVEN MULTI-USER NOTIFICATION ────────────────────────────────────
@app.route("/notify", methods=["POST"])
def notify():
    body    = request.get_json()
    event   = body.get("event", "")
    group   = body.get("group", "directors")
    data    = body.get("data", {})
    api_key = request.headers.get("X-API-Key", "")

    if api_key != NOTIFY_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    message = build_event_message(event, data)
    if not message:
        return jsonify({"error": "Unknown event"}), 400

    # ── Fetch recipients from Google Sheets ──
    recipients = get_recipients(group)
    if not recipients:
        return jsonify({"error": f"No active recipients found for group '{group}'"}), 404

    # ── Send to all recipients ──
    results = []
    for recipient in recipients:
        phone  = str(recipient.get("phone", ""))
        name   = recipient.get("name", "Unknown")
        if phone:
            result = send_whatsapp_message(phone, message)
            results.append({
                "name": name,
                "phone": phone,
                "status": "sent"
            })
            print(f"Notified {name} ({phone})")

    return jsonify({
        "status":  "success",
        "event":   event,
        "group":   group,
        "sent_to": len(results),
        "results": results
    }), 200


# ─── BUILD MESSAGE BY EVENT TYPE ─────────────────────────────────────────────
def build_event_message(event, data):
    messages = {
        "po_approved": (
            f"*PO Approval Alert* ✅\n\n"
            f"PO Number: {data.get('po_number', 'N/A')}\n"
            f"Amount: ₹{data.get('amount', 'N/A')}\n"
            f"Approved by: {data.get('approved_by', 'N/A')}\n"
            f"Date: {data.get('date', 'Today')}\n\n"
            f"Please review and take necessary action."
        ),
        "invoice_generated": (
            f"*Invoice Generated* 🧾\n\n"
            f"Invoice No: {data.get('invoice_no', 'N/A')}\n"
            f"Customer: {data.get('customer', 'N/A')}\n"
            f"Amount: ₹{data.get('amount', 'N/A')}\n"
            f"Due Date: {data.get('due_date', 'N/A')}"
        ),
        "low_stock": (
            f"*Low Stock Alert* ⚠️\n\n"
            f"Item: {data.get('item', 'N/A')}\n"
            f"Current Stock: {data.get('stock', 'N/A')}\n"
            f"Reorder Level: {data.get('reorder_level', 'N/A')}\n"
            f"Please initiate purchase order."
        ),
        "custom": data.get("message", "Notification from CMLL system.")
    }
    return messages.get(event, None)


# ─── SEND SINGLE WHATSAPP MESSAGE ────────────────────────────────────────────
def send_whatsapp_message(to_number, message_text):
    url = f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_text}
    }
    response = requests.post(url, json=payload, headers=headers)
    print(f"Sent to {to_number}: {response.status_code}")
    return response.json()


# ─── CLAUDE AI REPLY ──────────────────────────────────────────────────────────
def get_claude_reply(user_phone, user_message):
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    if user_phone not in conversation_history:
        conversation_history[user_phone] = []
    conversation_history[user_phone].append({"role": "user", "content": user_message})
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system="You are a helpful AI assistant for CMLL (Caliber Mining and Logistics Limited). Help with purchase orders, logistics, and business queries. Keep replies concise for WhatsApp.",
        messages=conversation_history[user_phone]
    )
    ai_reply = response.content[0].text
    conversation_history[user_phone].append({"role": "assistant", "content": ai_reply})
    if len(conversation_history[user_phone]) > 10:
        conversation_history[user_phone] = conversation_history[user_phone][-10:]
    return ai_reply


# ─── RUN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

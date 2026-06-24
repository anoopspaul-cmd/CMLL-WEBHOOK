import os
import requests
from flask import Flask, request, jsonify
import anthropic

app = Flask(__name__)

VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "cmllverify")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1183608764834373")
CLAUDE_API_KEY  = os.environ.get("CLAUDE_API_KEY", "")

conversation_history = {}

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

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
            ai_reply  = get_claude_reply(from_number, user_text)
            send_whatsapp_message(from_number, ai_reply)
    except Exception as e:
        print(f"Error: {e}")
    return jsonify({"status": "ok"}), 200

def get_claude_reply(user_phone, user_message):
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    if user_phone not in conversation_history:
        conversation_history[user_phone] = []
    conversation_history[user_phone].append({"role": "user", "content": user_message})
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system="You are a helpful AI assistant for CMLL (Caliber Mining and Logistics Limited). Help with purchase orders, logistics queries, and business questions. Keep replies concise and suitable for WhatsApp.",
        messages=conversation_history[user_phone]
    )
    ai_reply = response.content[0].text
    conversation_history[user_phone].append({"role": "assistant", "content": ai_reply})
    if len(conversation_history[user_phone]) > 10:
        conversation_history[user_phone] = conversation_history[user_phone][-10:]
    return ai_reply

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

def notify_directors(message, directors_list):
    for phone in directors_list:
        send_whatsapp_message(phone, message)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

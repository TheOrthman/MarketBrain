import os, requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("PHONE_NUMBER_ID")
URL = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"

def send_message(to: str, body: str, buttons: list = None):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

    if buttons:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": buttons}
            }
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body}
        }
    return requests.post(URL, headers=headers, json=payload)
import re
import os
import requests
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def transcribe_audio(audio_url):
    """Download WhatsApp voice and transcribe"""
    headers = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}
    audio_data = requests.get(audio_url, headers=headers).content

    # Save temp
    with open("temp.ogg", "wb") as f:
        f.write(audio_data)

    with open("temp.ogg", "rb") as f:
        transcript = client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3",
            language="en"
        )
    return transcript.text

def extract_text_from_image(image_url, whatsapp_token):
    """Read sales book photo with Groq Vision"""
    headers = {"Authorization": f"Bearer {whatsapp_token}"}
    img_data = requests.get(image_url, headers=headers).content
    b64 = base64.b64encode(img_data).decode('utf-8')

    resp = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract all numbers from this Nigerian market sales book. Return only numbers like '2000 1500 3000'"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]
        }],
        temperature=0
    )
    return resp.choices[0].message.content

def extract_amounts(text):
    """Handle Nigerian speech: one five, 1,5, 2k, two thousand"""
    original = text
    text = text.lower()

    # Words to digits
    word_map = {'one':'1','two':'2','three':'3','four':'4','five':'5',
                'six':'6','seven':'7','eight':'8','nine':'9','ten':'10'}
    for w,d in word_map.items():
        text = re.sub(r'\b'+w+r'\b', d, text)

    # Protect 2,000
    text = re.sub(r'(\d),(\d{3})\b', r'\1\2', text)
    # Join "1 5" -> "1,5"
    text = re.sub(r'(\d)\s+(\d)\b', r'\1,\2', text)
    text = re.sub(r'(\d)\s*[,\.]\s*(\d)\b', r'\1,\2', text)

    # Nigerian shorthand
    for old,new in {'1,5':'1500','2,5':'2500','3,5':'3500','1,0':'1000','2,0':'2000','3,0':'3000'}.items():
        text = text.replace(old, new)

    # thousand and k
    text = re.sub(r'(\d+)\s+thousand', lambda m: str(int(m.group(1))*1000), text)
    text = re.sub(r'(\d+)\s*k\b', lambda m: str(int(m.group(1))*1000), text)

    numbers = [int(n) for n in re.findall(r'\d+', text) if int(n) >= 100]
    print(f"PARSER: '{original}' -> '{text}' -> {numbers} = {sum(numbers)}")
    return sum(numbers), numbers

import re

def extract_product(text):
    # Remove numbers and common words
    clean = re.sub(r'\d+', '', text.lower())
    clean = re.sub(r'[₦nk,]', '', clean)
    stop_words = ['sold','sell','sales','spent','spend','buy','bought','for','na','of','the','i','don','make']
    words = [w for w in clean.split() if w not in stop_words and len(w) > 2]
    return ' '.join(words[:2]) if words else 'general'    

def extract_payment_method(text):
    t = text.lower()
    if 'transfer' in t or 'trf' in t or 'bank' in t:
        return 'transfer'
    if 'pos' in t:
        return 'pos'
    if 'card' in t:
        return 'card'
    return 'cash'    

def detect_expense_type(text):
    t = text.lower()
    if any(w in t for w in ['restock','stock','wholesale','buy goods','purchase','inventory','market buy']):
        return 'cogs'
    return 'overhead'    
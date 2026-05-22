# ocr_handler.py - EasyOCR version for Render
import os
import requests
import easyocr

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

# Initialize once - loads on first image, not at startup
reader = None

def get_reader():
    global reader
    if reader is None:
        reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    return reader

def download_whatsapp_media(media_id: str) -> str:
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    meta = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers).json()
    url = meta.get('url')
    if not url:
        raise Exception("No media URL")
    data = requests.get(url, headers=headers).content
    path = f"/tmp/{media_id}.jpg"
    os.makedirs("/tmp", exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path

def preprocess_image(path: str) -> str:
    import cv2  # lazy import
    img = cv2.imread(path)
    if img is None:
        return path
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    out_path = path.replace('.jpg', '_p.jpg')
    cv2.imwrite(out_path, enhanced)
    return out_path

def process_image_for_sales(media_id: str) -> dict:
    try:
        path = download_whatsapp_media(media_id)
        proc = preprocess_image(path)
        r = get_reader()
        results = r.readtext(proc, detail=0)
        lines = [x.lower().strip() for x in results if len(x) > 1]

        import re
        sales = []
        for raw in lines:
            m = re.search(r'([a-z]{2,})\s*x?\s*(\d+)\s+(\d{3,5})', raw)
            if m:
                item, qty, price = m.groups()
                qty, price = int(qty), int(price)
                if price < 100:
                    price *= 100
                sales.append({
                    "item": item,
                    "qty": qty,
                    "price": price,
                    "total": qty * price,
                    "raw": raw
                })

        return {
            "success": True,
            "lines": lines,
            "sales": sales,
            "total": sum(s['total'] for s in sales),
            "count": len(sales)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "lines": [],
            "sales": [],
            "total": 0,
            "count": 0
        }
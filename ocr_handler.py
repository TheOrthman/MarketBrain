# ocr_handler.py - EasyOCR version
import os, requests, cv2
import easyocr

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
reader = easyocr.Reader(['en'], gpu=False)  # loads once

def download_whatsapp_media(media_id: str) -> str:
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    meta = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers).json()
    url = meta.get('url')
    data = requests.get(url, headers=headers).content
    path = f"/tmp/{media_id}.jpg"
    os.makedirs("/tmp", exist_ok=True)
    with open(path, 'wb') as f: f.write(data)
    return path

def preprocess_image(path: str) -> str:
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(2.0, (8,8))
    out = clahe.apply(gray)
    out_path = path.replace('.jpg','_p.jpg')
    cv2.imwrite(out_path, out)
    return out_path

def process_image_for_sales(media_id: str) -> dict:
    try:
        path = download_whatsapp_media(media_id)
        proc = preprocess_image(path)
        results = reader.readtext(proc, detail=0)  # list of strings
        lines = [r.lower().strip() for r in results if len(r) > 1]

        import re
        sales = []
        for raw in lines:
            m = re.search(r'([a-z]{2,})\s*x?\s*(\d+)\s+(\d{3,5})', raw)
            if m:
                item, qty, price = m.groups()
                qty, price = int(qty), int(price)
                if price < 100: price *= 100
                sales.append({"item":item, "qty":qty, "price":price, "total":qty*price, "raw":raw})

        return {"success":True, "lines":lines, "sales":sales, "total":sum(s['total'] for s in sales), "count":len(sales)}
    except Exception as e:
        return {"success":False, "error":str(e), "lines":[], "sales":[], "total":0, "count":0}
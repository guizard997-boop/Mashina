import os
import time
import json
import re
import statistics
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 90          # секунд между проверками
MIN_YEAR = 2012
DISCOUNT_THRESHOLD = 0.15    # 15% и больше
CITY_ID = 103184             # Бишкек
SEEN_FILE = "seen_ads.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "device": "pc",
    "language": "ru_RU",
    "country-id": "12",
}

# ================================================

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_seen(seen):
    # Храним только последние 3000 id, чтобы файл не рос бесконечно
    recent = list(seen)[-3000:]
    with open(SEEN_FILE, "w") as f:
        json.dump(recent, f)

def send_telegram(text, photo_url=None):
    try:
        if photo_url:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            data = {
                "chat_id": CHAT_ID,
                "photo": photo_url,
                "caption": text,
                "parse_mode": "HTML"
            }
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            }
        requests.post(url, data=data, timeout=15)
    except Exception as e:
        print("Ошибка отправки в Telegram:", e)

def extract_year(title):
    if not title:
        return None
    match = re.search(r"(20\d{2}|19\d{2})\s*г", title)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(20\d{2}|19\d{2})\b", title)
    if match:
        return int(match.group(1))
    return None

def extract_make_model(title):
    """Грубая попытка вытащить марку и модель из названия"""
    if not title:
        return None, None
    # Убираем год и лишнее
    clean = re.sub(r":?\s*\d{4}\s*г?\.?.*", "", title, flags=re.IGNORECASE)
    clean = clean.strip()
    parts = clean.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:3])
    elif len(parts) == 1:
        return parts[0], None
    return None, None

def normalize_price(price, currency):
    """Приводим всё к USD примерно"""
    if price is None:
        return None
    try:
        price = float(price)
    except:
        return None

    if currency == "USD":
        return price
    elif currency == "KGS":
        return price / 87.0   # примерный курс, можно потом уточнить
    return price

def get_ads(page=1, q=None, per_page=40):
    params = {
        "per-page": per_page,
        "page": page,
        "expand": "url",
        "sort_by": "newest",
        "city_id": CITY_ID,
        "category_id": 1501,   # Транспорт
    }
    if q:
        params["q"] = q

    try:
        r = requests.get(
            "https://api.lalafo.com/v3/ads/search",
            params=params,
            headers=HEADERS,
            timeout=20
        )
        if r.status_code == 200:
            return r.json().get("items", [])
    except Exception as e:
        print("Ошибка запроса к Lalafo:", e)
    return []

def get_market_price(make, model, year):
    """Ищем похожие объявления и считаем медиану"""
    if not make:
        return None, 0

    query = make
    if model:
        query += " " + model.split()[0]  # берём только первое слово модели

    items = get_ads(q=query, per_page=50)
    prices = []

    for item in items:
        item_year = extract_year(item.get("title", ""))
        if item_year and abs(item_year - year) > 3:  # год ±3
            continue

        price = normalize_price(item.get("price"), item.get("currency"))
        if price and 500 < price < 150000:  # фильтр от мусора
            prices.append(price)

    if len(prices) < 3:
        return None, len(prices)

    return statistics.median(prices), len(prices)

def analyze_and_notify(ad, seen):
    ad_id = ad.get("id")
    if ad_id in seen:
        return

    title = ad.get("title") or "Без названия"
    year = extract_year(title)

    if year is None or year < MIN_YEAR:
        seen.add(ad_id)
        return

    price_raw = ad.get("price")
    currency = ad.get("currency")
    price_usd = normalize_price(price_raw, currency)

    if not price_usd:
        seen.add(ad_id)
        return

    make, model = extract_make_model(title)
    market_price, count = get_market_price(make, model, year)

    if not market_price or count < 3:
        # Недостаточно данных для сравнения — пропускаем
        seen.add(ad_id)
        return

    discount = (market_price - price_usd) / market_price

    if discount >= DISCOUNT_THRESHOLD:
        # Это выгодное предложение!
        url = "https://lalafo.kg" + (ad.get("url") or "")
        city = ad.get("city") or "Бишкек"
        photo = None
        if ad.get("images"):
            photo = ad["images"][0].get("original_url") or ad["images"][0].get("thumbnail_url")

        text = (
            f"🔥 <b>Выгодное авто!</b>\n\n"
            f"<b>{title}</b>\n"
            f"📍 {city}\n"
            f"💰 Цена: <b>{price_raw} {currency}</b> (\~{price_usd:.0f}$)\n"
            f"📊 Рыночная: \~{market_price:.0f}$\n"
            f"📉 Дешевле рынка на: <b>{discount*100:.1f}%</b>\n"
            f"🔍 Похожих объявлений: {count}\n\n"
            f"<a href='{url}'>Открыть объявление</a>"
        )

        send_telegram(text, photo)
        print(f"[{datetime.now()}] Отправлено: {title} | -{discount*100:.1f}%")

    seen.add(ad_id)

def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("Ошибка: не заданы BOT_TOKEN или CHAT_ID")
        return

    print("Бот запущен...")
    send_telegram("✅ Бот мониторинга Lalafo запущен и работает")

    seen = load_seen()

    while True:
        try:
            print(f"[{datetime.now()}] Проверяю новые объявления...")
            ads = get_ads(page=1, per_page=30)

            for ad in ads:
                analyze_and_notify(ad, seen)

            save_seen(seen)
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print("Ошибка в основном цикле:", e)
            time.sleep(30)

if __name__ == "__main__":
    main()

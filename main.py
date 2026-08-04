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

CHECK_INTERVAL = 90              # секунд между проверками
DISCOUNT_THRESHOLD = 0.15        # 15% и больше
MIN_COMPARABLES = 4              # минимум похожих объявлений
CITY_ID = 103184                 # Бишкек
SEEN_FILE = "seen_ads.json"
USD_KGS_RATE = 87.5              # примерный курс сома к доллару

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "device": "pc",
    "language": "ru_RU",
    "country-id": "12",
}

# Чёрный список
BLACKLIST = [
    "запчаст", "двигател", "мотор", "акпп", "мкпп", "кпп", "фара", "бампер",
    "капот", "дверь", "крыло", "стекло", "стёкл", "стекла", "лобовое", "лобовые",
    "панорамн", "люк", "панорамный люк", "панорамные",
    "диск", "шина", "резина", "колёс",
    "аккумулятор", "генератор", "стартер", "форсунк", "турбин", "радиатор",
    "скупк", "выкуп", "разбор", "ремонт", "услуг", "эвакуатор", "манипулятор",
    "прицеп", "кузовн", "покраск", "полировк", "ключ", "брелок", "сигнализац",
    "автозвук", "магнитол", "баланс", "шиномонтаж", "развал", "сход-развал",
    "то ", "т.о.", "замена", "установка", "продажа запчастей", "контрактн",
    "б/у мотор", "б/у двигатель", "головка блока", "гбц", "поршень", "коленвал",
    "редуктор", "мост", "кардан", "амортизатор", "стойка", "рычаг", "шаровая",
    "насос", "компрессор", "кондиционер", "печка", "тормозн", "суппорт",
    "диск тормозной", "колодк", "сцепление", "корзина", "выжимной",
    "рулевая", "рейка", "наконечник", "тяга", "сайлентблок", "подшипник",
    "вариатор в сборе", "коробка передач", "раздатка",

    # Спецтехника
    "экскаватор", "погрузчик", "трактор", "бульдозер", "каток", "грейдер",
    "кран", "автокран", "бетономешалка", "бетононасос",
    "самосвал", "фура", "тягач", "полуприцеп", "трал",
    "комбайн", "сеялка", "косилка", "культиватор", "плуг",
    "снегоуборщик", "мусоровоз", "ассенизатор", "поливомоечная",
    "автовышка", "подъёмник", "гидромолот", "отвал",

    # Под заказ / не в наличии
    "под заказ", "на заказ", "подзаказ", "назаказ",
    "заказ из", "под заказ из", "привезу под заказ",
    "под пригон", "на пригон", "пригон под заказ",
    "ожидается", "будет через", "доставка под заказ",
    "заказной", "под вашу заявку", "привезум", "привезём под заказ"
]

# Популярные марки
CAR_BRANDS = [
    "toyota", "lexus", "honda", "nissan", "mazda", "subaru", "mitsubishi", "suzuki",
    "hyundai", "kia", "ssangyong", "daewoo", "chevrolet", "gmc", "cadillac", "buick",
    "mercedes", "bmw", "audi", "volkswagen", "vw", "porsche", "opel", "skoda",
    "volvo", "saab", "peugeot", "renault", "citroen", "fiat", "alfa", "lancia",
    "ford", "jeep", "dodge", "chrysler", "ram", "tesla", "land rover", "range rover",
    "jaguar", "mini", "smart", "bentley", "rolls-royce", "aston", "ferrari", "lamborghini",
    "maserati", "infiniti", "acura", "genesis", "byd", "changan", "geely", "haval",
    "great wall", "chery", "jac", "faw", "dongfeng", "lifan", "zotye", "exeed",
    "lixiang", "li auto", "neta", "zeekr", "voyah", "tank", "gac", "hongqi",
    "uaz", "lada", "ваз", "газ", "москвич", "уаз", "зил", "камаз", "маз",
    "isuzu", "daihatsu", "proton", "ssang yong"
]

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
    recent = list(seen)[-4000:]
    with open(SEEN_FILE, "w") as f:
        json.dump(recent, f)

def send_telegram(text, photo_url=None):
    try:
        if photo_url:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            data = {
                "chat_id": CHAT_ID,
                "photo": photo_url,
                "caption": text[:1024],
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

def extract_year(title: str):
    if not title:
        return None
    match = re.search(r"(20[0-2]\d|19[8-9]\d)\s*г", title, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(20[0-2]\d|19[8-9]\d)\b", title)
    if match:
        return int(match.group(1))
    return None

def is_junk(title: str) -> bool:
    """Жёсткий фильтр — только реальные автомобили"""
    if not title:
        return True

    title_lower = title.lower().strip()

    # 1. Чёрный список
    for word in BLACKLIST:
        if word in title_lower:
            return True

    # 2. Должна быть марка
    has_brand = any(brand in title_lower for brand in CAR_BRANDS)
    if not has_brand:
        return True

    # 3. Должен быть год
    year = extract_year(title)
    if year is None:
        return True

    # 4. Типичный формат объявления авто
    has_year_format = bool(re.search(r"\d{4}\s*г", title_lower))
    has_engine = bool(re.search(r"\d\.\d\s*л", title_lower))
    if not (has_year_format or has_engine):
        return True

    return False

def extract_make_model(title: str):
    if not title:
        return None, None
    clean = re.sub(r":?\s*\d{4}\s*г?\.?.*", "", title, flags=re.IGNORECASE)
    clean = re.sub(r"[^\w\s\-]", " ", clean)
    parts = clean.strip().split()
    if len(parts) >= 2:
        return parts[0].capitalize(), parts[1].capitalize()
    elif len(parts) == 1:
        return parts[0].capitalize(), None
    return None, None

def normalize_price(price, currency):
    """Всегда возвращаем цену в USD"""
    if price is None:
        return None

    try:
        price = float(price)
    except (ValueError, TypeError):
        return None

    if price <= 0:
        return None

    currency = (currency or "").upper().strip()

    if currency == "USD":
        return price
    elif currency == "KGS":
        return price / USD_KGS_RATE
    else:
        if price > 4000:
            return price / USD_KGS_RATE
        else:
            return price

def get_ads(page=1, q=None, per_page=40):
    params = {
        "per-page": per_page,
        "page": page,
        "expand": "url",
        "sort_by": "newest",
        "city_id": CITY_ID,
        "category_id": 1501,
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
    if not make:
        return None, 0

    query = make
    if model:
        query += f" {model}"

    items = get_ads(q=query, per_page=60)
    prices = []

    for item in items:
        title = item.get("title") or ""
        if is_junk(title):
            continue

        item_year = extract_year(title)
        if not item_year:
            continue

        # Для старых машин допуск по году шире
        year_diff = abs(item_year - year)
        if year < 2005:
            if year_diff > 4:
                continue
        else:
            if year_diff > 2:
                continue

        price_usd = normalize_price(item.get("price"), item.get("currency"))
        if price_usd and 800 < price_usd < 100000:
            prices.append(price_usd)

    if len(prices) < MIN_COMPARABLES:
        return None, len(prices)

    return statistics.median(prices), len(prices)

def analyze_and_notify(ad, seen):
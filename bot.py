"""
Kesişim Radar - Telegram Sinyal Botu
Her çalıştırıldığında:
  1) Telegram'dan gelen yeni komutları okur (/add, /remove, /list, /all, /manual)
  2) İzleme listesindeki (ya da TÜM piyasadaki) her sembol için EMA50/200 + Pivot + Fibonacci + Hacim sinyali üretir
  3) Yön değişen (yeni AL/SAT oluşan) semboller için Telegram mesajı gönderir
  4) watchlist.json ve state.json dosyalarını günceller (workflow bunları commit'ler)

Bu script GitHub Actions tarafından cron ile (örn. her 15 dakikada bir) çalıştırılır.
Sürekli açık bir sunucuya ihtiyaç yoktur.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

WATCHLIST_FILE = "watchlist.json"
STATE_FILE = "state.json"

TIMEFRAME = "15m"
PROXIMITY_PIVOT = 0.35      # %
PROXIMITY_FIB = 0.5         # %
MIN_CONFIDENCE_TO_NOTIFY = 30


# ============================= HTTP helpers =============================

def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def telegram_api(method, params=None):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    if params:
        url = base + "?" + urllib.parse.urlencode(params)
    else:
        url = base
    return http_get_json(url)


def send_message(text):
    telegram_api("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })


# ============================= Binance =============================

def fetch_klines(symbol, interval, limit=300):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    raw = http_get_json(url)
    candles = []
    for k in raw:
        candles.append({
            "openTime": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "closeTime": k[6],
        })
    return candles


def fetch_prev_daily(symbol):
    daily = fetch_klines(symbol, "1d", 2)
    if len(daily) < 2:
        return daily[0] if daily else None
    return daily[-2]


def fetch_all_usdt_symbols():
    """Binance'de işlem gören tüm USDT paritelerini döner.
    Kaldıraçlı token'lar (UP/DOWN/BULL/BEAR) ve stablecoin çiftleri hariç tutulur."""
    info = http_get_json("https://api.binance.com/api/v3/exchangeInfo")
    excluded_words = ["UP", "DOWN", "BULL", "BEAR"]
    stable_bases = {"USDC", "FDUSD", "TUSD", "DAI", "BUSD", "EUR", "GBP", "TRY", "USDP", "PAX", "UST", "USTC"}
    symbols = []
    for s in info.get("symbols", []):
        if s.get("quoteAsset") != "USDT":
            continue
        if s.get("status") != "TRADING":
            continue
        base = s.get("baseAsset", "")
        if any(w in base for w in excluded_words):
            continue
        if base in stable_bases:
            continue
        symbols.append(s["symbol"])
    return sorted(symbols)


# ============================= Indicators =============================

def calc_ema(closes, period):
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    out = [seed]
    for price in closes[period:]:
        out.append(price * k + out[-1] * (1 - k))
    return out


def analyze_ema(candles):
    closes = [c["close"] for c in candles]
    if len(closes) < 201:
        return None
    e50 = calc_ema(closes, 50)
    e200 = calc_ema(closes, 200)
    n = min(len(e50), len(e200))
    if n < 2:
        return None
    e50_tail, e200_tail = e50[-n:], e200[-n:]
    last50, prev50 = e50_tail[-1], e50_tail[-2]
    last200, prev200 = e200_tail[-1], e200_tail[-2]

    cross = "none"
    if prev50 <= prev200 and last50 > last200:
        cross = "golden"
    elif prev50 >= prev200 and last50 < last200:
        cross = "death"

    return {
        "last_cross": cross,
        "trend_is_bullish": last50 > last200,
    }


def classic_pivots(h, l, c):
    pp = (h + l + c) / 3
    r1, s1 = 2 * pp - l, 2 * pp - h
    r2, s2 = pp + (h - l), pp - (h - l)
    r3, s3 = h + 2 * (pp - l), l - 2 * (h - pp)
    return [("R3", r3), ("R2", r2), ("R1", r1), ("PP", pp), ("S1", s1), ("S2", s2), ("S3", s3)]


def fib_retracement(candles, lookback=50):
    if len(candles) < 5:
        return None
    window = candles[-lookback:]
    high_c = max(window, key=lambda c: c["high"])
    low_c = min(window, key=lambda c: c["low"])
    high, low = high_c["high"], low_c["low"]
    is_uptrend = low_c["openTime"] < high_c["openTime"]
    diff = high - low
    ratios = [("0.0", 0), ("0.236", 0.236), ("0.382", 0.382), ("0.5", 0.5),
              ("0.618", 0.618), ("0.786", 0.786), ("1.0", 1.0)]
    levels = []
    for name, r in ratios:
        price = (high - diff * r) if is_uptrend else (low + diff * r)
        levels.append((name, price))
    return {"is_uptrend": is_uptrend, "levels": levels}


def nearest_fib(price, fib):
    best_name, best_level, best_dist = None, None, float("inf")
    for name, level in fib["levels"]:
        d = abs(level - price)
        if d < best_dist:
            best_dist, best_name, best_level = d, name, level
    if best_name is None:
        return None
    return best_name, best_level, abs(price - best_level) / price * 100


def analyze_volume(candles, period=20, spike_threshold=1.5):
    if len(candles) <= period:
        return None
    recent_past = candles[-(period + 1):-1]
    avg = sum(c["volume"] for c in recent_past) / len(recent_past)
    if avg <= 0:
        return None
    current = candles[-1]["volume"]
    ratio = current / avg
    return {"ratio": ratio, "is_spike": ratio >= spike_threshold}


# ============================= Signal Engine =============================

def generate_signal(symbol, candles, prev_daily):
    last = candles[-1]
    price = last["close"]
    factors = []

    ema = analyze_ema(candles)
    if not ema:
        return None

    if ema["last_cross"] == "golden":
        factors.append(("EMA 50/200", "Golden Cross oluştu (yükseliş dönüşü)", 40))
    elif ema["last_cross"] == "death":
        factors.append(("EMA 50/200", "Death Cross oluştu (düşüş dönüşü)", -40))
    else:
        score = 15 if ema["trend_is_bullish"] else -15
        text = "EMA50 > EMA200, trend yukarı" if ema["trend_is_bullish"] else "EMA50 < EMA200, trend aşağı"
        factors.append(("EMA 50/200", text, score))

    if prev_daily:
        pivots = classic_pivots(prev_daily["high"], prev_daily["low"], prev_daily["close"])
        nearest_name, nearest_dist = None, float("inf")
        for name, level in pivots:
            dist = abs(price - level) / level * 100
            if dist < nearest_dist:
                nearest_dist, nearest_name = dist, name
        if nearest_name and nearest_dist <= PROXIMITY_PIVOT:
            is_support = nearest_name.startswith("S") or nearest_name == "PP"
            factors.append((
                "Pivot",
                f"Fiyat {nearest_name} seviyesine çok yakın (%{nearest_dist:.2f})",
                25 if is_support else -25,
            ))

    fib = fib_retracement(candles, 50)
    if fib:
        nf = nearest_fib(price, fib)
        if nf and nf[2] <= PROXIMITY_FIB:
            name, _level, _dist = nf
            factors.append((
                "Fibonacci",
                f"Fiyat %{name} seviyesine yakın ({'destek' if fib['is_uptrend'] else 'direnç'})",
                20 if fib["is_uptrend"] else -20,
            ))

    volume_multiplier = 1.0
    vol = analyze_volume(candles)
    if vol:
        if vol["is_spike"]:
            volume_multiplier = 1.25
            factors.append(("Hacim", f"Hacim ortalamanın {vol['ratio']:.1f}x üzerinde (teyit güçlü)", 0))
        else:
            factors.append(("Hacim", f"Hacim normal seviyede (%{int(vol['ratio']*100)} ortalama)", 0))

    raw_score = sum(f[2] for f in factors) * volume_multiplier
    confidence = min(100, abs(raw_score))

    direction = "IZLE"
    if confidence >= MIN_CONFIDENCE_TO_NOTIFY:
        direction = "AL" if raw_score > 0 else "SAT"

    stop = target = None
    if direction != "IZLE" and len(candles) >= 14:
        recent = candles[-14:]
        avg_range = sum(c["high"] - c["low"] for c in recent) / len(recent)
        if direction == "AL":
            stop, target = price - avg_range * 1.2, price + avg_range * 2.0
        else:
            stop, target = price + avg_range * 1.2, price - avg_range * 2.0

    return {
        "symbol": symbol, "direction": direction, "confidence": confidence,
        "price": price, "factors": factors, "stop": stop, "target": target,
    }


def format_signal_message(sig):
    emoji = {"AL": "🟢", "SAT": "🔴", "IZLE": "🟡"}[sig["direction"]]
    lines = [
        f"{emoji} <b>{sig['symbol']}</b> — {sig['direction']} (güven %{int(sig['confidence'])})",
        f"Fiyat: ${sig['price']:.4f}" if sig["price"] < 1 else f"Fiyat: ${sig['price']:.2f}",
    ]
    if sig["stop"] and sig["target"]:
        lines.append(f"⛔ Stop: ${sig['stop']:.2f}   🎯 Hedef: ${sig['target']:.2f}")
    lines.append("")
    for name, detail, score in sig["factors"]:
        arrow = "↑" if score > 0 else ("↓" if score < 0 else "•")
        lines.append(f"{arrow} <b>{name}</b>: {detail}")
    return "\n".join(lines)


# ============================= Telegram command handling =============================

def process_commands(state, watchlist):
    offset = state.get("last_update_id", 0) + 1
    try:
        updates = telegram_api("getUpdates", {"offset": offset, "timeout": 0})
    except Exception as e:
        print("getUpdates hata:", e)
        return watchlist, state

    results = updates.get("result", [])
    for u in results:
        state["last_update_id"] = u["update_id"]
        msg = u.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(TELEGRAM_CHAT_ID):
            continue  # sadece kendi chat_id'nden gelen komutları işle

        if text.startswith("/add"):
            if watchlist == ["ALL"]:
                send_message("Şu an TÜM piyasa taranıyor, tekil ekleme geçersiz. Önce /manual yaz.")
                continue
            parts = text.split()
            if len(parts) >= 2:
                symbol = parts[1].upper()
                if symbol not in watchlist:
                    watchlist.append(symbol)
                    send_message(f"✅ {symbol} izleme listesine eklendi.")
                else:
                    send_message(f"{symbol} zaten listede.")
            else:
                send_message("Kullanım: /add BTCUSDT")

        elif text.startswith("/remove"):
            if watchlist == ["ALL"]:
                send_message("Şu an TÜM piyasa taranıyor, tekil çıkarma geçersiz. Önce /manual yaz.")
                continue
            parts = text.split()
            if len(parts) >= 2:
                symbol = parts[1].upper()
                if symbol in watchlist:
                    watchlist.remove(symbol)
                    state.get("last_signals", {}).pop(symbol, None)
                    send_message(f"🗑 {symbol} listeden çıkarıldı.")
                else:
                    send_message(f"{symbol} listede değil.")
            else:
                send_message("Kullanım: /remove BTCUSDT")

        elif text.startswith("/list"):
            if watchlist == ["ALL"]:
                send_message("🌐 Şu an TÜM piyasa (Binance USDT çiftleri) taranıyor.\nElle liste seçmek için /manual yaz.")
            elif watchlist:
                send_message("📋 İzleme listen:\n" + "\n".join(f"• {s}" for s in watchlist))
            else:
                send_message("İzleme listen boş. /add BTCUSDT ile ekleyebilirsin.")

        elif text.startswith("/all"):
            watchlist = ["ALL"]
            send_message(
                "🌐 Tüm piyasa taraması AÇILDI.\n"
                "Artık Binance'deki tüm USDT çiftleri her 15 dakikada bir taranacak.\n"
                "İlk taramada mevcut sinyali olan tüm semboller için mesaj gelebilir — bu normal.\n"
                "Elle liste seçmek istersen /manual yaz."
            )

        elif text.startswith("/manual"):
            if watchlist == ["ALL"]:
                watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
                send_message("📋 Elle liste moduna dönüldü. Varsayılan: BTCUSDT, ETHUSDT, SOLUSDT.\n/add ve /remove ile düzenleyebilirsin.")
            else:
                send_message("Zaten elle liste modundasın.")

        elif text.startswith("/start") or text.startswith("/help"):
            send_message(
                "👋 Kesişim Radar botuna hoş geldin.\n\n"
                "/add SEMBOL — izlemeye ekle (örn: /add BNBUSDT)\n"
                "/remove SEMBOL — izlemeden çıkar\n"
                "/list — izleme listeni gör\n"
                "/all — TÜM piyasayı taramaya başla\n"
                "/manual — elle seçilmiş listeye geri dön\n\n"
                "Bot her 15 dakikada bir taramayı otomatik yapar, "
                "yeni bir AL/SAT sinyali oluşunca sana buradan haber verir."
            )

    return watchlist, state


# ============================= Main =============================

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    watchlist = load_json(WATCHLIST_FILE, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    state = load_json(STATE_FILE, {"last_update_id": 0, "last_signals": {}})

    watchlist, state = process_commands(state, watchlist)
    state.setdefault("last_signals", {})

    if watchlist == ["ALL"]:
        try:
            symbols_to_scan = fetch_all_usdt_symbols()
        except Exception as e:
            print("Tüm piyasa listesi çekilemedi:", e)
            symbols_to_scan = []
    else:
        symbols_to_scan = watchlist

    for symbol in symbols_to_scan:
        try:
            candles = fetch_klines(symbol, TIMEFRAME, 300)
            prev_daily = fetch_prev_daily(symbol)
            sig = generate_signal(symbol, candles, prev_daily)
        except Exception as e:
            print(f"{symbol} işlenemedi: {e}")
            continue

        if not sig:
            continue

        prev_direction = state["last_signals"].get(symbol)
        # Sadece yön DEĞİŞTİĞİNDE (yeni AL/SAT oluştuğunda) bildirim gönder — spam önlenir.
        if sig["direction"] in ("AL", "SAT") and sig["direction"] != prev_direction:
            send_message(format_signal_message(sig))
            time.sleep(0.5)  # Telegram flood limitine takılmamak için

        state["last_signals"][symbol] = sig["direction"]
        time.sleep(0.3)  # Binance rate-limit'e takılmamak için ufak bekleme

    save_json(WATCHLIST_FILE, watchlist)
    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()

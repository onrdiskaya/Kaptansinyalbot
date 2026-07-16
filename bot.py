"""
Kesişim Radar - "Capitano Pro" Sürümü
EMA 50/200 Trendi, Günlük Pivotlar, RSI/MACD Dönüşleri, OKX Funding Rate (Fonlama),
ve Kritik Mum Formasyonları (Çekiç, Yutan Boğa, Asılı Adam vb.) içeren gelişmiş tarayıcı.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

WATCHLIST_FILE = "watchlist.json"
STATE_FILE = "state.json"

POPULAR_USDT_SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "ADA-USDT", "AVAX-USDT", 
    "DOT-USDT", "DOGE-USDT", "SHIB-USDT", "LINK-USDT", "NEAR-USDT", "LTC-USDT", "UNI-USDT", 
    "OP-USDT", "ARB-USDT", "APT-USDT", "SUI-USDT", "INJ-USDT", "TIA-USDT", "FIL-USDT", 
    "ATOM-USDT", "ICP-USDT", "FET-USDT", "GRT-USDT", "FTM-USDT", "STX-USDT", "GALA-USDT", 
    "ALGO-USDT", "AAVE-USDT", "MKR-USDT", "CRV-USDT", "RUNE-USDT", "WIF-USDT", "PEPE-USDT", 
    "FLOKI-USDT", "BONK-USDT", "JUP-USDT"
]

TIMEFRAME = "15m"
PROXIMITY_PIVOT = 0.85      # %
MIN_CONFIDENCE_TO_NOTIFY = 35

# ============================= HTML Safe Helper =============================

def html_escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ============================= HTTP Helpers =============================

def http_get_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def telegram_api(method, params=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram API ayarları eksik!")
        return {}
    try:
        base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
        if params:
            url = base + "?" + urllib.parse.urlencode(params)
        else:
            url = base
        return http_get_json(url)
    except Exception as e:
        print(f"⚠️ Telegram API Hatası: {e}")
        return {}


def send_message(text):
    telegram_api("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })

# ============================= OKX API Fetchers =============================

def fetch_klines_okx(symbol):
    """OKX v5 API'sinden mum verilerini çeker. Spot yoksa otomatik Swap (Vadeli) dener."""
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={TIMEFRAME}&limit=150"
    try:
        data = http_get_json(url)
        if data.get("code") == "0" and data.get("data"):
            raw_list = data["data"]
        else:
            swap_symbol = f"{symbol}-SWAP"
            url_swap = f"https://www.okx.com/api/v5/market/candles?instId={swap_symbol}&bar={TIMEFRAME}&limit=150"
            data = http_get_json(url_swap)
            if data.get("code") != "0" or not data.get("data"):
                raise ValueError(f"OKX API Hatası: {data.get('msg')}")
            raw_list = data["data"]
    except Exception as e:
        raise ValueError(f"Veri çekme hatası: {e}")

    raw_list.reverse()
    candles = []
    for item in raw_list:
        candles.append({
            "openTime": int(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
        })
    return candles


def fetch_prev_daily_okx(symbol):
    """Günlük mum verilerini çeker (Classic Pivot için)."""
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1Dutc&limit=2"
    try:
        data = http_get_json(url)
        if data.get("code") == "0" and len(data.get("data", [])) >= 2:
            raw_list = data["data"]
        else:
            swap_symbol = f"{symbol}-SWAP"
            url_swap = f"https://www.okx.com/api/v5/market/candles?instId={swap_symbol}&bar=1Dutc&limit=2"
            data = http_get_json(url_swap)
            if data.get("code") != "0" or len(data.get("data", [])) < 2:
                return None
            raw_list = data["data"]
    except Exception:
        return None
        
    prev_day = raw_list[1]
    return {
        "high": float(prev_day[2]),
        "low": float(prev_day[3]),
        "close": float(prev_day[4])
    }


def fetch_funding_rate_okx(symbol):
    """OKX Swap piyasasından canlı fonlama oranını çeker."""
    swap_symbol = f"{symbol}-SWAP"
    url = f"https://www.okx.com/api/v5/public/funding-rate?instId={swap_symbol}"
    try:
        data = http_get_json(url)
        if data.get("code") == "0" and data.get("data"):
            # Örn: 0.0001 (%0.01) olarak döner
            return float(data["data"][0]["fundingRate"])
    except Exception:
        pass
    return 0.0

# ============================= Technical Indicators =============================

def calc_ema(closes, period):
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    out = [seed]
    for price in closes[period:]:
        out.append(price * k + out[-1] * (1 - k))
    return out


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return []
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    rsi_vals = []
    if avg_loss == 0:
        rsi_vals.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
        
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
    return rsi_vals


def calc_macd(closes):
    if len(closes) < 20:
        return [], []
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    n = min(len(ema12), len(ema26))
    macd_line = [e12 - e26 for e12, e26 in zip(ema12[-n:], ema26[-n:])]
    signal_line = calc_ema(macd_line, 9)
    return macd_line, signal_line


def classic_pivots(h, l, c):
    pp = (h + l + c) / 3
    r1, s1 = 2 * pp - l, 2 * pp - h
    r2, s2 = pp + (h - l), pp - (h - l)
    r3, s3 = h + 2 * (pp - l), l - 2 * (h - pp)
    return [("R3", r3), ("R2", r2), ("R1", r1), ("PP", pp), ("S1", s1), ("S2", s2), ("S3", s3)]


# ============================= Candlestick Patterns (Mum Formasyonları) =============================

def analyze_candle_patterns(candles):
    """En önemli yön belirleyen mum formasyonlarını tespit eder."""
    if len(candles) < 3:
        return None, 0

    c1 = candles[-2]  # Bir önceki mum
    c2 = candles[-1]  # En son (canlı/yeni kapanmış) mum

    # Mum gövde ve fitil boyutları hesaplama
    def get_parts(c):
        body = abs(c["close"] - c["open"])
        high_shadow = c["high"] - max(c["open"], c["close"])
        low_shadow = min(c["open"], c["close"]) - c["low"]
        total = c["high"] - c["low"]
        is_bull = c["close"] >= c["open"]
        return body, high_shadow, low_shadow, total, is_bull

    b2, hs2, ls2, t2, bull2 = get_parts(c2)
    b1, hs1, ls1, t1, bull1 = get_parts(c1)

    # 1) YUTAN BOĞA (Bullish Engulfing)
    if not bull1 and bull2 and c2["close"] > c1["open"] and c2["open"] < c1["close"]:
        return "Yutan Boğa (Bullish Engulfing) 🟢", 30

    # 2) YUTAN AYI (Bearish Engulfing)
    if bull1 and not bull2 and c2["close"] < c1["open"] and c2["open"] > c1["close"]:
        return "Yutan Ayı (Bearish Engulfing) 🔴", -30

    # 3) ÇEKİÇ (Hammer) - Dip Dönüşü
    if t2 > 0 and (ls2 >= 2 * b2) and (hs2 <= 0.1 * t2):
        if bull2:
            return "Çekiç (Hammer) 🟢", 25
        else:
            return "Ters Çekiç (Inverted Hammer) 🟡", 15

    # 4) KAYAN YILDIZ (Shooting Star) / ASILI ADAM (Hanging Man) - Tepe Dönüşü
    if t2 > 0 and (hs2 >= 2 * b2) and (ls2 <= 0.1 * t2):
        if not bull2:
            return "Kayan Yıldız (Shooting Star) 🔴", -25
        else:
            return "Asılı Adam (Hanging Man) 🔴", -20

    return None, 0


# ============================= Core Signal Engine =============================

def generate_signal(symbol, candles, prev_daily, btc_state, funding_rate):
    last = candles[-1]
    price = last["close"]
    closes = [c["close"] for c in candles]
    factors = []
    
    if len(closes) < 200:
        return None

    # 1) EMA 50 ve 200 Analizi
    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)
    
    if not ema50 or not ema200:
        return None
        
    e50_last, e50_prev = ema50[-1], ema50[-2]
    e200_last, e200_prev = ema200[-1], ema200[-2]
    
    # Trend Yönü Tayini
    trend_up = e50_last > e200_last
    
    # EMA Kesişim Kontrolü
    ema_cross = "none"
    if e50_prev <= e200_prev and e50_last > e200_last:
        ema_cross = "golden"
    elif e50_prev >= e200_prev and e50_last < e200_last:
        ema_cross = "death"

    # EMA Puanlaması
    if ema_cross == "golden":
        factors.append(("EMA 50/200", "Golden Cross Kesişimi Gerçekleşti 🚀", 50))
    elif ema_cross == "death":
        factors.append(("EMA 50/200", "Death Cross Kesişimi Gerçekleşti 💀", -50))
    else:
        # Fiyatın EMA'ların neresinde kapattığı önemli
        if price > e50_last and price > e200_last:
            factors.append(("EMA Yapısı", "Fiyat EMA 50 & 200 üzerinde (Güçlü Alıcı)", 25))
        elif price < e50_last and price < e200_last:
            factors.append(("EMA Yapısı", "Fiyat EMA 50 & 200 altında (Güçlü Satıcı)", -25))
        else:
            factors.append(("EMA Yapısı", "Fiyat EMA kanalı içinde sıkışmış", 0))

    # 2) Mum Formasyonu (Price Action) Analizi
    pattern_name, pattern_score = analyze_candle_patterns(candles)
    if pattern_name:
        factors.append(("Mum Formasyonu", f"{pattern_name} tespit edildi", pattern_score))

    # 3) Pivot Sıkışması ve Analizi
    if prev_daily:
        pivots = classic_pivots(prev_daily["high"], prev_daily["low"], prev_daily["close"])
        nearest_name, nearest_dist = None, float("inf")
        for name, level in pivots:
            dist = abs(price - level) / level * 100
            if dist < nearest_dist:
                nearest_dist, nearest_name = dist, name
                
        # PP Üstü/Altı Kontrolü
        pp_level = [v for k, v in pivots if k == "PP"][0]
        is_above_pp = price > pp_level
        
        # Sıkışma Kontrolü (Pivotlar birbirine daralmış mı?)
        r3_level = [v for k, v in pivots if k == "R3"][0]
        s3_level = [v for k, v in pivots if k == "S3"][0]
        pivot_range_pct = (r3_level - s3_level) / pp_level * 100
        
        pivot_detail = f"Fiyat PP üzerinde. {nearest_name} yakınlarında (%{nearest_dist:.2f})" if is_above_pp else f"Fiyat PP altında. {nearest_name} yakınlarında (%{nearest_dist:.2f})"
        pivot_score = 15 if is_above_pp else -15
        
        if pivot_range_pct < 2.5: # Daralan pivot (Patlama Habercisi)
            pivot_detail += " | Pivot Aralığı Aşırı Daraldı (PATLAMA YAKIN) 💥"
            pivot_score *= 1.3
            
        factors.append(("Pivot Analizi", pivot_detail, int(pivot_score)))

    # 4) RSI Analizi (Dipten Kafayı Kaldırdı mı?)
    rsi_vals = calc_rsi(closes)
    if rsi_vals:
        curr_rsi, prev_rsi = rsi_vals[-1], rsi_vals[-2]
        if curr_rsi <= 25:
            factors.append(("RSI", f"Aşırı Satım Bölgesi (%{curr_rsi:.1f})", 20))
        elif prev_rsi < 30 and curr_rsi > prev_rsi:
            factors.append(("RSI", f"Dipten Kafayı Yukarı Kaldırdı (%{curr_rsi:.1f}) 📈", 30))
        elif curr_rsi >= 75:
            factors.append(("RSI", f"Aşırı Alım Bölgesi (%{curr_rsi:.1f})", -20))
        elif prev_rsi > 70 and curr_rsi < prev_rsi:
            factors.append(("RSI", f"Tepeden Aşağı Dönüyor (%{curr_rsi:.1f}) 📉", -30))
        else:
            factors.append(("RSI", f"Nötr bölgede (%{curr_rsi:.1f})", 0))

    # 5) MACD Analizi
    macd_line, signal_line = calc_macd(closes)
    if len(macd_line) >= 2 and len(signal_line) >= 2:
        prev_macd, last_macd = macd_line[-2], macd_line[-1]
        prev_sig, last_sig = signal_line[-2], signal_line[-1]
        if prev_macd <= prev_sig and last_macd > last_sig:
            factors.append(("MACD", "Aşağıdan Yukarı Kesti (AL) 🟢", 20))
        elif prev_macd >= prev_sig and last_macd < last_sig:
            factors.append(("MACD", "Yukarıdan Aşağı Kesti (SAT) 🔴", -20))

    # 6) Fonlama Oranı (Funding Rate) Analizi
    if funding_rate != 0.0:
        # Aşırı yüksek pozitif fonlama (%0.05 ve üzeri) longları patlatmak isteyebilirler
        if funding_rate >= 0.0005:
            factors.append(("Funding Rate", f"Yüksek Fonlama (%{funding_rate*100:.3f}) - Long Squeeze Riski! ⚠️", -15))
        # Aşırı negatif fonlama shortları patlatmak isteyebilirler
        elif funding_rate <= -0.0005:
            factors.append(("Funding Rate", f"Yüksek Negatif (%{funding_rate*100:.3f}) - Short Squeeze Riski! 🚀", 15))
        else:
            factors.append(("Funding Rate", f"Dengeli (%{funding_rate*100:.4f})", 0))

    # Puanlama Toplamı
    raw_score = sum(f[2] for f in factors)
    
    # 7) BTC Trend Filtresi Uygulaması
    if btc_state:
        if btc_state["trend"] == "bearish" and raw_score > 0:
            raw_score *= 0.5  # BTC ayı ise long sinyal gücünü yarı yarıya düşür
            factors.append(("Piyasa Etkisi (BTC)", "BTC düşüş trendinde olduğu için sinyal gücü kırıldı.", 0))
        elif btc_state["trend"] == "bullish" and raw_score < 0:
            raw_score *= 0.5  # BTC boğa ise short sinyal gücünü yarı yarıya düşür

    confidence = min(100, abs(raw_score))
    
    direction = "IZLE"
    if confidence >= MIN_CONFIDENCE_TO_NOTIFY:
        direction = "AL" if raw_score > 0 else "SAT"

    return {
        "symbol": symbol, "direction": direction, "confidence": confidence,
        "price": price, "factors": factors, "funding": funding_rate
    }


def format_signal_message(sig):
    emoji = {"AL": "🟢 [LONG ADAYI]", "SAT": "🔴 [SHORT ADAYI]", "IZLE": "🟡"}[sig["direction"]]
    clean_symbol = sig['symbol'].replace("-", "")
    sym = html_escape(clean_symbol)
    price_val = sig['price']
    conf = int(sig['confidence'])
    
    lines = [
        f"{emoji} <b>#{sym}</b>",
        f"<b>Anlık Fiyat:</b> ${price_val:.4f}" if price_val < 1 else f"<b>Anlık Fiyat:</b> ${price_val:.2f}",
        f"<b>Sinyal Güveni:</b> %{conf}",
        f"<b>Canlı Fonlama Oranı:</b> %{sig['funding']*100:.4f}",
        "---",
        "<b>🔎 CAPITANO ANALİZ RAPORU:</b>"
    ]
    
    for name, detail, score in sig["factors"]:
        if score > 0:
            arrow = "✅"
        elif score < 0:
            arrow = "❌"
        else:
            arrow = "•"
        lines.append(f"{arrow} <b>{html_escape(name)}:</b> {html_escape(detail)}")
        
    lines.append("\n⚠️ <i>Grafiğini açıp mutlaka Price Action teyidi al Onur!</i>")
    return "\n".join(lines)


# ============================= Command & Flow Management =============================

def process_commands(state, watchlist):
    offset = state.get("last_update_id", 0) + 1
    try:
        updates = telegram_api("getUpdates", {"offset": offset, "timeout": 0})
    except Exception:
        return watchlist, state

    results = updates.get("result", [])
    for u in results:
        state["last_update_id"] = u["update_id"]
        msg = u.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(TELEGRAM_CHAT_ID):
            continue

        clean_text = text.replace("USDT", "-USDT") if "USDT" in text and "-" not in text else text

        if clean_text.startswith("/add"):
            if watchlist == ["ALL"]:
                send_message("Şu an TÜM piyasa taranıyor. Önce /manual yaz.")
                continue
            parts = clean_text.split()
            if len(parts) >= 2:
                symbol = parts[1].upper()
                if symbol not in watchlist:
                    watchlist.append(symbol)
                    send_message(f"✅ {symbol.replace('-', '')} izleme listesine eklendi.")
            else:
                send_message("Kullanım: /add BTCUSDT")

        elif clean_text.startswith("/remove"):
            if watchlist == ["ALL"]:
                send_message("Şu an TÜM piyasa taranıyor. Önce /manual yaz.")
                continue
            parts = clean_text.split()
            if len(parts) >= 2:
                symbol = parts[1].upper()
                if symbol in watchlist:
                    watchlist.remove(symbol)
                    state.get("last_signals", {}).pop(symbol, None)
                    send_message(f"🗑 {symbol.replace('-', '')} listeden çıkarıldı.")
            else:
                send_message("Kullanım: /remove BTCUSDT")

        elif text.startswith("/list"):
            if watchlist == ["ALL"]:
                send_message("🌐 Şu an tüm OKX popüler coinleri taranıyor.")
            else:
                send_message("📋 İzleme listen:\n" + "\n".join(f"• {s.replace('-', '')}" for s in watchlist))

        elif text.startswith("/all"):
            watchlist = ["ALL"]
            send_message("🌐 Tüm popüler OKX coinleri tarama moduna geçildi.")

        elif text.startswith("/manual"):
            watchlist = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
            send_message("📋 Elle liste moduna geçildi. Varsayılan: BTC, ETH, SOL.")

    return watchlist, state


def get_btc_state():
    """Taramadan önce BTC-USDT durumunu analiz eder."""
    try:
        candles = fetch_klines_okx("BTC-USDT")
        closes = [c["close"] for c in candles]
        ema200 = calc_ema(closes, 200)
        if closes[-1] > ema200[-1]:
            return {"trend": "bullish", "price": closes[-1]}
        else:
            return {"trend": "bearish", "price": closes[-1]}
    except Exception:
        return None


# ============================= Main Pipeline =============================

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def main():
    watchlist = ["ALL"]
    state = load_json(STATE_FILE, {"last_update_id": 0, "last_signals": {}})

    try:
        watchlist, state = process_commands(state, watchlist)
    except Exception:
        pass

    state.setdefault("last_signals", {})

    # Tarama öncesi BTC durumunu al
    btc_state = get_btc_state()
    print(f"Piyasa Trend Filtresi (BTC): {btc_state}")

    symbols_to_scan = POPULAR_USDT_SYMBOLS if watchlist == ["ALL"] else watchlist
    print(f"OKX üzerinde {len(symbols_to_scan)} sembol Capitano Pro algoritmalarıyla taranıyor...")

    for symbol in symbols_to_scan:
        try:
            time.sleep(0.3)
            
            candles = fetch_klines_okx(symbol)
            prev_daily = fetch_prev_daily_okx(symbol)
            funding_rate = fetch_funding_rate_okx(symbol)
            
            sig = generate_signal(symbol, candles, prev_daily, btc_state, funding_rate)
            
            if not sig:
                continue

            prev_direction = state["last_signals"].get(symbol)
            if sig["direction"] in ("AL", "SAT") and sig["direction"] != prev_direction:
                send_message(format_signal_message(sig))
                time.sleep(0.5)

            state["last_signals"][symbol] = sig["direction"]
            
        except Exception as e:
            print(f"⚠️ {symbol} taranırken hata: {e}")
            continue

    save_json(WATCHLIST_FILE, watchlist)
    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()

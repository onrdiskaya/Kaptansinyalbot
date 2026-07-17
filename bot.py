"""
Kesişim Radar - "Capitano Pro Max v3.0" (Profesyonel Ekip Sürümü)
- EMA 50/200, Günlük Pivotlar, RSI/MACD, OKX Funding Rate.
- YENİ: MTF (1h Trend Onayı), Hacim Patlaması Filtresi, ATR SL/TP Seviyeleri.
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
    "ATOM-USDT", "ICP-USDT", "FET-USDT", "GRT-USDT", "STX-USDT", "GALA-USDT", 
    "ALGO-USDT", "AAVE-USDT", "CRV-USDT", "WIF-USDT", "PEPE-USDT", 
    "FLOKI-USDT", "BONK-USDT", "JUP-USDT"
]

TIMEFRAME = "15m"
MIN_CONFIDENCE_TO_NOTIFY = 35

OKX_API_URLS = [
    "https://www.okx.cab",
    "https://www.okx.com"
]

def html_escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def http_get_json(path_with_query):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    last_error = None
    for base_url in OKX_API_URLS:
        full_url = f"{base_url}{path_with_query}"
        try:
            req = urllib.request.Request(full_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            last_error = e
            continue
    raise ConnectionError(f"OKX Bağlantı Hatası: {last_error}")

def telegram_api(method, params=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return {}
    try:
        base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
        url = base + "?" + urllib.parse.urlencode(params) if params else base
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"⚠️ Telegram Hatası: {e}")
        return {}

def send_message(text):
    telegram_api("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"})

def fetch_klines_okx(symbol, timeframe=TIMEFRAME, limit=250):
    path = f"/api/v5/market/candles?instId={symbol}&bar={timeframe}&limit={limit}"
    raw_list = None
    try:
        data = http_get_json(path)
        if data.get("code") == "0" and data.get("data"):
            raw_list = data["data"]
    except Exception:
        pass
    if not raw_list:
        try:
            data = http_get_json(f"/api/v5/market/candles?instId={symbol}-SWAP&bar={timeframe}&limit={limit}")
            if data.get("code") == "0" and data.get("data"):
                raw_list = data["data"]
        except Exception as e:
            raise ValueError(f"Veri çekilemedi ({symbol}): {e}")
    if not raw_list:
        raise ValueError(f"Boş veri döndü ({symbol})")
    raw_list.reverse()
    return [{
        "openTime": int(item[0]), "open": float(item[1]), "high": float(item[2]),
        "low": float(item[3]), "close": float(item[4]), "volume": float(item[5])
    } for item in raw_list]

def fetch_prev_daily_okx(symbol):
    try:
        res = fetch_klines_okx(symbol, timeframe="1Dutc", limit=2)
        return {"high": res[-2]["high"], "low": res[-2]["low"], "close": res[-2]["close"]} if len(res) >= 2 else None
    except Exception:
        return None

def fetch_funding_rate_okx(symbol):
    try:
        data = http_get_json(f"/api/v5/public/funding-rate?instId={symbol}-SWAP")
        return float(data["data"][0]["fundingRate"]) if data.get("code") == "0" and data.get("data") else 0.0
    except Exception:
        return 0.0

# ============================= Gelişmiş Matematik ve İndikatörler =============================

def calc_ema(closes, period):
    if len(closes) < period: return []
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    out = [seed]
    for price in closes[period:]:
        out.append(price * k + out[-1] * (1 - k))
    return out

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return []
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_vals = [100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))]
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi_vals.append(100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))
    return rsi_vals

def calc_macd(closes):
    if len(closes) < 20: return [], []
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    n = min(len(ema12), len(ema26))
    macd_line = [e12 - e26 for e12, e26 in zip(ema12[-n:], ema26[-n:])]
    return macd_line, calc_ema(macd_line, 9)

def calc_atr(candles, period=14):
    if len(candles) < period + 1: return 0.0
    tr_all = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        tr_all.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr_all[-period:]) / period

def classic_pivots(h, l, c):
    pp = (h + l + c) / 3
    return [("R3", h + 2*(pp - l)), ("R2", pp + (h - l)), ("R1", 2*pp - l), ("PP", pp), ("S1", 2*pp - h), ("S2", pp - (h - l)), ("S3", l - 2*(h - pp))]

# ============================= Pro Max Karar Motoru =============================

def check_volume_spike(candles):
    if len(candles) < 21: return True, 1.0
    current_vol = candles[-1]["volume"]
    prev_vols = [c["volume"] for c in candles[-21:-1]]
    avg_vol = sum(prev_vols) / len(prev_vols)
    if avg_vol == 0: return True, 1.0
    ratio = current_vol / avg_vol
    return ratio >= 1.5, ratio

def check_1h_trend(symbol, direction):
    try:
        candles_1h = fetch_klines_okx(symbol, timeframe="1h", limit=60)
        if len(candles_1h) < 50: return True
        closes_1h = [c["close"] for c in candles_1h]
        ema50_1h_list = calc_ema(closes_1h, 50)
        if not ema50_1h_list: return True
        ema50_1h = ema50_1h_list[-1]
        price = closes_1h[-1]
        if direction == "AL" and price < ema50_1h: return False
        if direction == "SAT" and price > ema50_1h: return False
        return True
    except Exception:
        return True

def generate_signal(symbol, candles, prev_daily, btc_state, funding_rate):
    if len(candles) < 50: return None
    
    # 1. Hacim Patlaması Filtresi
    has_volume, vol_ratio = check_volume_spike(candles)
    if not has_volume: return None 

    last = candles[-1]
    price = last["close"]
    closes = [c["close"] for c in candles]
    
    report_data = {
        "Hacim Durumu": {"detail": f"Hacim Patlaması Aktif (Ort. x{vol_ratio:.1f}) 🔥", "score": 15, "status": "bullish"},
        "EMA Yapısı": {"detail": "Hesaplanamadı", "score": 0, "status": "neutral"},
        "Pivot Analizi": {"detail": "Pivot verisi eksik", "score": 0, "status": "neutral"},
        "RSI": {"detail": "Hesaplanamadı", "score": 0, "status": "neutral"},
        "MACD": {"detail": "Kesişim yok (Nötr) ⚪", "score": 0, "status": "neutral"},
        "Funding Rate": {"detail": "Dengeli", "score": 0, "status": "neutral"}
    }

    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)
    if ema50:
        e50_last = ema50[-1]
        if ema200:
            e50_prev, e200_last, e200_prev = ema50[-2], ema200[-1], ema200[-2]
            if e50_prev <= e200_prev and e50_last > e200_last: report_data["EMA Yapısı"] = {"detail": "Golden Cross Kesişimi Gerçekleşti 🚀", "score": 50, "status": "bullish"}
            elif e50_prev >= e200_prev and e50_last < e200_last: report_data["EMA Yapısı"] = {"detail": "Death Cross Kesişimi Gerçekleşti 💀", "score": -50, "status": "bearish"}
            else:
                if price > e50_last and price > e200_last: report_data["EMA Yapısı"] = {"detail": "Fiyat EMA 50 & 200 üzerinde (Güçlü Alıcı)", "score": 25, "status": "bullish"}
                elif price < e50_last and price < e200_last: report_data["EMA Yapısı"] = {"detail": "Fiyat EMA 50 & 200 altında (Güçlü Satıcı)", "score": -25, "status": "bearish"}
        else:
            report_data["EMA Yapısı"] = {"detail": "Fiyat EMA 50 üzerinde" if price > e50_last else "Fiyat EMA 50 altında", "score": 15 if price > e50_last else -15, "status": "bullish" if price > e50_last else "bearish"}

    if prev_daily:
        pivots = classic_pivots(prev_daily["high"], prev_daily["low"], prev_daily["close"])
        nearest_name, nearest_dist = min([(n, abs(price - l)/l*100) for n, l in pivots], key=lambda x: x[1])
        pp_level = [v for k, v in pivots if k == "PP"][0]
        is_above = price > pp_level
        report_data["Pivot Analizi"] = {"detail": f"Fiyat PP {'üzerinde' if is_above else 'altında'}. {nearest_name} yakınlarında (%{nearest_dist:.2f})", "score": 15 if is_above else -15, "status": "bullish" if is_above else "bearish"}

    rsi_vals = calc_rsi(closes)
    if rsi_vals:
        curr_rsi, prev_rsi = rsi_vals[-1], rsi_vals[-2]
        if curr_rsi <= 25: report_data["RSI"] = {"detail": f"Aşırı Satım Bölgesi (%{curr_rsi:.1f})", "score": 20, "status": "bullish"}
        elif prev_rsi < 30 and curr_rsi > prev_rsi: report_data["RSI"] = {"detail": f"Dipten Kafayı Kaldırdı (%{curr_rsi:.1f}) 📈", "score": 30, "status": "bullish"}
        elif curr_rsi >= 75: report_data["RSI"] = {"detail": f"Aşırı Alım Bölgesi (%{curr_rsi:.1f})", "score": -20, "status": "bearish"}
        elif prev_rsi > 70 and curr_rsi < prev_rsi: report_data["RSI"] = {"detail": f"Tepeden Aşağı Dönüyor (%{curr_rsi:.1f}) 📉", "score": -30, "status": "bearish"}
        else: report_data["RSI"] = {"detail": f"Nötr bölgede (%{curr_rsi:.1f})", "score": 0, "status": "neutral"}

    m_line, s_line = calc_macd(closes)
    if len(m_line) >= 2 and len(s_line) >= 2:
        if m_line[-2] <= s_line[-2] and m_line[-1] > s_line[-1]: report_data["MACD"] = {"detail": "Aşağıdan Yukarı Kesti (AL) 🟢", "score": 20, "status": "bullish"}
        elif m_line[-2] >= s_line[-2] and m_line[-1] < s_line[-1]: report_data["MACD"] = {"detail": "Yukarıdan Aşağı Kesti (SAT) 🔴", "score": -20, "status": "bearish"}
        else: report_data["MACD"] = {"detail": "Kesişim Yok (Yatay) ⚪", "score": 0, "status": "neutral"}

    if funding_rate != 0.0:
        if funding_rate >= 0.0005: report_data["Funding Rate"] = {"detail": f"Yüksek Fonlama (%{funding_rate*100:.3f}) - Long Squeeze! ⚠️", "score": -15, "status": "bearish"}
        elif funding_rate <= -0.0005: report_data["Funding Rate"] = {"detail": f"Yüksek Negatif (%{funding_rate*100:.3f}) - Short Squeeze! 🚀", "score": 15, "status": "bullish"}
        else: report_data["Funding Rate"] = {"detail": f"Dengeli (%{funding_rate*100:.4f})", "score": 0, "status": "neutral"}

    raw_score = sum(v["score"] for v in report_data.values())
    if btc_state:
        if btc_state["trend"] == "bearish" and raw_score > 0: raw_score *= 0.5
        elif btc_state["trend"] == "bullish" and raw_score < 0: raw_score *= 0.5

    confidence = min(100, abs(raw_score))
    direction = "IZLE"
    if confidence >= MIN_CONFIDENCE_TO_NOTIFY:
        direction = "AL" if raw_score > 0 else "SAT"

    if direction == "IZLE": return None

    # 2. MTF (1 Saatlik Zaman Dilimi Filtresi)
    if not check_1h_trend(symbol, direction):
        print(f"⏩ {symbol} 15m sinyali, 1h ana trendi ile uyuşmadığı için elendi.")
        return None

    # 3. ATR Bazlı Matematiksel TP/SL Hesaplama
    atr_val = calc_atr(candles)
    sl, tp1, tp2 = 0.0, 0.0, 0.0
    if direction == "AL":
        sl = price - (atr_val * 1.5)
        tp1 = price + (atr_val * 1.5)
        tp2 = price + (atr_val * 3.0)
    elif direction == "SAT":
        sl = price + (atr_val * 1.5)
        tp1 = price - (atr_val * 1.5)
        tp2 = price - (atr_val * 3.0)

    return {
        "symbol": symbol, "direction": direction, "confidence": confidence, "price": price,
        "report_data": report_data, "funding": funding_rate, "sl": sl, "tp1": tp1, "tp2": tp2
    }

def format_signal_message(sig):
    emoji = "🟢 [LONG SETUP]" if sig["direction"] == "AL" else "🔴 [SHORT SETUP]"
    clean_sym = sig['symbol'].replace("-", "")
    price_val = sig['price']
    fmt = ".8f" if price_val < 1.0 else ".2f"
    
    lines = [
        f"{emoji} <b>#{clean_sym}</b>",
        f"<b>Giriş Fiyatı:</b> {price_val:{fmt}}",
        f"<b>Sinyal Güveni:</b> %{int(sig['confidence'])}",
        f"<b>Canlı Fonlama:</b> %{sig['funding']*100:.4f}",
        "---",
        "🎯 <b>PRO MAX İŞLEM SEVİYELERİ (ATR):</b>",
        f"⛔ <b>Stop-Loss (SL):</b> {sig['sl']:{fmt}}",
        f"💰 <b>Kâr Al 1 (TP1):</b> {sig['tp1']:{fmt}}",
        f"🚀 <b>Kâr Al 2 (TP2):</b> {sig['tp2']:{fmt}}",
        "---",
        "<b>🔎 TEKNİK ANALİZ RADARI:</b>"
    ]
    for name, data in sig["report_data"].items():
        arrow = "✅" if data["status"] == "bullish" else ("❌" if data["status"] == "bearish" else "⚪")
        lines.append(f"{arrow} <b>{html_escape(name)}:</b> {html_escape(data['detail'])}")
        
    lines.append("\n👑 <i>Ekip için Bookmap ve Emir Defteri teyidi zamanı! Success!</i>")
    return "\n".join(lines)

# ============================= Altyapı ve Döngü Yönetimi =============================

def process_commands(state, watchlist):
    offset = state.get("last_update_id", 0) + 1
    try: updates = telegram_api("getUpdates", {"offset": offset, "timeout": 0})
    except Exception: return watchlist, state
    for u in updates.get("result", []):
        state["last_update_id"] = u["update_id"]
        msg = u.get("message", {})
        text = (msg.get("text") or "").strip()
        if str(msg.get("chat", {}).get("id", "")) != str(TELEGRAM_CHAT_ID): continue
        clean_text = text.replace("USDT", "-USDT") if "USDT" in text and "-" not in text else text

        if clean_text.startswith("/add") and len(clean_text.split()) >= 2:
            sym = clean_text.split()[1].upper()
            if sym not in watchlist: watchlist.append(sym); send_message(f"✅ {sym.replace('-', '')} eklendi.")
        elif clean_text.startswith("/remove") and len(clean_text.split()) >= 2:
            sym = clean_text.split()[1].upper()
            if sym in watchlist: watchlist.remove(sym); state.get("last_signals", {}).pop(sym, None); send_message(f"🗑 {sym.replace('-', '')} silindi.")
        elif text.startswith("/list"): send_message("📋 Liste:\n" + "\n".join(f"• {s.replace('-', '')}" for s in watchlist))
        elif text.startswith("/all"): watchlist = ["ALL"]; save_json(WATCHLIST_FILE, watchlist); send_message("🌐 Tüm markete geçildi.")
        elif text.startswith("/manual"): watchlist = ["BTC-USDT", "ETH-USDT"]; save_json(WATCHLIST_FILE, watchlist); send_message("📋 Manuel moda geçildi.")
    return watchlist, state

def get_btc_state():
    try:
        res = fetch_klines_okx("BTC-USDT")
        if not res or len(res) < 200: return None
        closes = [c["close"] for c in res]
        e200 = calc_ema(closes, 200)[-1]
        return {"trend": "bullish" if closes[-1] > e200 else "bearish", "price": closes[-1]}
    except Exception: return None

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return default
    return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception: pass

def single_scan(state, watchlist):
    btc_state = get_btc_state()
    symbols = POPULAR_USDT_SYMBOLS if watchlist == ["ALL"] else watchlist
    print(f"🔄 Pro Max Tarama: {len(symbols)} sembol taranıyor...")
    for symbol in symbols:
        try:
            time.sleep(0.3)
            candles = fetch_klines_okx(symbol)
            prev_daily = fetch_prev_daily_okx(symbol)
            funding_rate = fetch_funding_rate_okx(symbol)
            sig = generate_signal(symbol, candles, prev_daily, btc_state, funding_rate)
            if not sig: continue
            
            prev_dir = state["last_signals"].get(symbol)
            if sig["direction"] != prev_dir:
                send_message(format_signal_message(sig))
                time.sleep(0.5)
            state["last_signals"][symbol] = sig["direction"]
        except Exception as e:
            print(f"⚠️ {symbol} Hatası: {e}")
            continue
    save_json(STATE_FILE, state)

def main():
    start_time = time.time()
    while True:
        loop_start = time.time()
        if loop_start - start_time > 5.5 * 3600: break
        watchlist = load_json(WATCHLIST_FILE, ["ALL"])
        state = load_json(STATE_FILE, {"last_update_id": 0, "last_signals": {}})
        state.setdefault("last_signals", {})
        try: watchlist, state = process_commands(state, watchlist); save_json(WATCHLIST_FILE, watchlist)
        except Exception: pass
        single_scan(state, watchlist)
        sleep_time = max(10, (15 * 60) - (time.time() - loop_start))
        print(f"💤 Bekleme: {int(sleep_time)} sn...\n")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()

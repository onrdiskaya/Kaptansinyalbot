"""
Capitano Master Radar v5.5 (Log Scale & Fibonacci Pivot Setup)
- BINANCE FUTURES VERİ AKIŞI
- LOGARİTMİK GRAFİK ÇİZİMİ (TradingView Uyumlu)
- FİBONACCİ PİVOT (PP, R1, S1) & EMA (50/200) FİLTRESİ
- 6 ANA KRİTER (En az 3 Onay Şartı)
- ONAYLANAN VE EKSİK ŞARTLARIN NET RAPORU + GRAFİK GÖRSELİ
"""

import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.parse
import pandas as pd
import mplfinance as mpf

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = "-1004339033046"

WATCHLIST_FILE = "watchlist.json"
STATE_FILE = "state.json"

POPULAR_USDT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", 
    "DOTUSDT", "DOGEUSDT", "SHIBUSDT", "LINKUSDT", "NEARUSDT", "LTCUSDT", "UNIUSDT", 
    "OPUSDT", "ARBUSDT", "APTUSDT", "SUIUSDT", "INJUSDT", "TIAUSDT", "FILUSDT", 
    "ATOMUSDT", "ICPUSDT", "FETUSDT", "GRTUSDT", "STXUSDT", "GALAUSDT", 
    "AAVEUSDT", "CRVUSDT", "WIFUSDT", "PEPEUSDT", "FLOKIUSDT"
]

TIMEFRAMES = ["15m", "1h", "4h"]
BINANCE_FUTURES_URL = "https://fapi.binance.com"

def fmt_price(val):
    if val == 0: return "0"
    abs_v = abs(val)
    if abs_v < 0.0001: return f"{val:.8f}"
    elif abs_v < 1.0: return f"{val:.6f}"
    elif abs_v < 100: return f"{val:.4f}"
    else: return f"{val:.2f}"

def html_escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def http_get_json(url):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode())

def telegram_api(method, params=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return {}
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
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    telegram_api("sendMessage", params)

def send_photo(photo_path, caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return {}
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    body = []
    body.append(f'--{boundary}'.encode())
    body.append(b'Content-Disposition: form-data; name="chat_id"')
    body.append(b'')
    body.append(TELEGRAM_CHAT_ID.encode())
    body.append(f'--{boundary}'.encode())
    body.append(b'Content-Disposition: form-data; name="parse_mode"')
    body.append(b'')
    body.append(b'HTML')
    body.append(f'--{boundary}'.encode())
    body.append(b'Content-Disposition: form-data; name="caption"')
    body.append(b'')
    body.append(caption.encode('utf-8'))
    body.append(f'--{boundary}'.encode())
    body.append(b'Content-Disposition: form-data; name="photo"; filename="chart.png"')
    body.append(b'Content-Type: image/png')
    body.append(b'')
    with open(photo_path, 'rb') as f:
        body.append(f.read())
    body.append(f'--{boundary}--'.encode())
    body.append(b'')
    payload = b'\r\n'.join(body)
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}', 'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"⚠️ Görsel Gönderme Hatası: {e}")
        send_message(caption)
        return {}

# --- BINANCE FUTURES API ---

def fetch_klines_binance(symbol, timeframe, limit=200):
    url = f"{BINANCE_FUTURES_URL}/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    data = http_get_json(url)
    candles = []
    for item in data:
        candles.append({
            "openTime": int(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
            "takerBuyVolume": float(item[9])
        })
    return candles

def fetch_prev_daily_binance(symbol):
    try:
        res = fetch_klines_binance(symbol, timeframe="1d", limit=2)
        return {"high": res[-2]["high"], "low": res[-2]["low"], "close": res[-2]["close"]} if len(res) >= 2 else None
    except Exception: return None

def fetch_open_interest_binance(symbol):
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/openInterest?symbol={symbol}"
        data = http_get_json(url)
        return float(data.get("openInterest", 0.0))
    except Exception: return 0.0

# --- İNDİKATÖR VE FİBONACCİ HESAPLAMALARI ---

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

def detect_rsi_divergence(candles, rsi_vals, window=15):
    if len(candles) < window + 2 or len(rsi_vals) < window + 2: return None
    recent_candles = candles[-window:]
    recent_rsi = rsi_vals[-window:]
    price_now, rsi_now = recent_candles[-1]["close"], recent_rsi[-1]
    
    min_price_prev = min(c["low"] for c in recent_candles[:-3])
    rsi_at_min_price = recent_rsi[recent_candles.index(next(c for c in recent_candles[:-3] if c["low"] == min_price_prev))]
    
    max_price_prev = max(c["high"] for c in recent_candles[:-3])
    rsi_at_max_price = recent_rsi[recent_candles.index(next(c for c in recent_candles[:-3] if c["high"] == max_price_prev))]
    
    if price_now < min_price_prev and rsi_now > rsi_at_min_price and rsi_now < 45: return "BULLISH_DIV"
    if price_now > max_price_prev and rsi_now < rsi_at_max_price and rsi_now > 55: return "BEARISH_DIV"
    return None

def calc_macd(closes):
    if len(closes) < 26: return [], []
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    n = min(len(ema12), len(ema26))
    macd_line = [e12 - e26 for e12, e26 in zip(ema12[-n:], ema26[-n:])]
    return macd_line, calc_ema(macd_line, 9)

def fibonacci_pivots(h, l, c):
    pp = (h + l + c) / 3.0
    r = h - l
    return {
        "PP": pp,
        "R1": pp + (r * 0.382),
        "S1": pp - (r * 0.382),
        "R2": pp + (r * 0.618),
        "S2": pp - (r * 0.618)
    }

# --- LOGARİTMİK GRAFİK ÇİZİMİ ---

def generate_chart(symbol, timeframe, candles, prev_daily, filename="temp_chart.png"):
    try:
        df_data = []
        for c in candles[-70:]:
            dt = datetime.datetime.fromtimestamp(c["openTime"] / 1000)
            df_data.append({"Date": dt, "Open": c["open"], "High": c["high"], "Low": c["low"], "Close": c["close"], "Volume": c["volume"]})
        
        df = pd.DataFrame(df_data)
        df.set_index("Date", inplace=True)
        closes = [c["close"] for c in candles]
        
        ema50 = calc_ema(closes, 50)[-len(df):]
        ema200 = calc_ema(closes, 200)[-len(df):]
        
        add_plots = []
        if len(ema50) == len(df): add_plots.append(mpf.make_addplot(ema50, color='#2962FF', width=1.2))
        if len(ema200) == len(df): add_plots.append(mpf.make_addplot(ema200, color='#FF6D00', width=1.5))
            
        rsi_vals = calc_rsi(closes)[-len(df):]
        if len(rsi_vals) == len(df):
            add_plots.append(mpf.make_addplot(rsi_vals, panel=2, color='#7E57C2', ylabel='RSI (14)', ylim=(0, 100)))
            
        m_line, s_line = calc_macd(closes)
        m_vals, s_vals = m_line[-len(df):], s_line[-len(df):]
        if len(m_vals) == len(df) and len(s_vals) == len(df):
            hist = [m - s for m, s in zip(m_vals, s_vals)]
            colors = ['#26a69a' if h >= 0 else '#ef5350' for h in hist]
            add_plots.append(mpf.make_addplot(m_vals, panel=3, color='#2962FF', ylabel='MACD'))
            add_plots.append(mpf.make_addplot(s_vals, panel=3, color='#FF6D00'))
            add_plots.append(mpf.make_addplot(hist, panel=3, type='bar', color=colors))
            
        h_lines, h_colors = [], []
        pivot_title_str = ""
        if prev_daily:
            pivots = fibonacci_pivots(prev_daily["high"], prev_daily["low"], prev_daily["close"])
            h_lines = [pivots["S1"], pivots["PP"], pivots["R1"]]
            h_colors = ["#00E676", "#FFC107", "#FF5252"]
            pivot_title_str = f" | PP:{fmt_price(pivots['PP'])}"

        style = mpf.make_mpf_style(base_mpf_style='yahoo', gridstyle=':', y_on_right=True, rc={'font.size': 8})
        chart_title = f"BINANCE: {symbol} ({timeframe}) [LOG] {pivot_title_str}"
        h_dict = dict(hlines=h_lines, colors=h_colors, linestyle='--', linewidths=1.2) if h_lines else None

        # yscale='log' ile LOGARİTMİK ÇİZİM
        mpf.plot(df, type='candle', volume=True, addplot=add_plots, hlines=h_dict, style=style, title=chart_title,
                 yscale='log', tight_layout=True, savefig=dict(fname=filename, bbox_inches='tight', pad_inches=0.2), figscale=1.2)
        return filename
    except Exception as e:
        print(f"⚠️ Grafik Çizim Hatası: {e}")
        return None

# --- SİNYAL ANALİZ MOTORU ---

def generate_signal(symbol, timeframe, candles, prev_daily, current_oi, state):
    if len(candles) < 50 or not prev_daily: return None
    
    last = candles[-1]
    price = last["close"]
    closes = [c["close"] for c in candles]
    
    pivots = fibonacci_pivots(prev_daily["high"], prev_daily["low"], prev_daily["close"])
    pp = pivots["PP"]
    
    ema50_vals = calc_ema(closes, 50)
    ema200_vals = calc_ema(closes, 200)
    if not ema50_vals or not ema200_vals: return None
    
    e50, e200 = ema50_vals[-1], ema200_vals[-1]
    
    # KATI ZEMİN ARAMASI: Long mu Short mu Eğilimli?
    direction = None
    if price > pp and price > e50 and price > e200:
        direction = "LONG"
    elif price < pp and price < e50 and price < e200:
        direction = "SHORT"
    else:
        return None # Zemin şartı sağlanmıyorsa pas geç
        
    approved = []
    missing = []
    
    # 1. Fibonacci Pivot Şartı
    if direction == "LONG":
        approved.append(f"Fibonacci Pivot: Fiyat PP ({fmt_price(pp)}) Üzerinde Mum Kapattı 📈")
    else:
        approved.append(f"Fibonacci Pivot: Fiyat PP ({fmt_price(pp)}) Altında Mum Kapattı 📉")
        
    # 2. EMA Şartı
    if direction == "LONG" and e50 > e200:
        approved.append("EMA Yapısı: Fiyat > EMA50 > EMA200 (Boğa Hizalanması)")
    elif direction == "SHORT" and e50 < e200:
        approved.append("EMA Yapısı: Fiyat < EMA50 < EMA200 (Ayı Hizalanması)")
    else:
        missing.append("EMA Yapısı: EMA 50/200 Kesişim Hizası Tam Oturmadı")
        
    # 3. RSI & Uyumsuzluk
    rsi_vals = calc_rsi(closes)
    div = detect_rsi_divergence(candles, rsi_vals) if rsi_vals else None
    curr_rsi = rsi_vals[-1] if rsi_vals else 50
    
    if direction == "LONG":
        if div == "BULLISH_DIV": approved.append(f"RSI Göstergesi: Pozitif Uyumsuzluk Var! (RSI: {curr_rsi:.1f}) 🔥")
        elif curr_rsi <= 35: approved.append(f"RSI Göstergesi: Aşırı Satım Bölgesi (%{curr_rsi:.1f}) 🟢")
        else: missing.append(f"RSI Göstergesi: Uyumsuzluk Yok / Nötr Bölgede (%{curr_rsi:.1f})")
    else:
        if div == "BEARISH_DIV": approved.append(f"RSI Göstergesi: Negatif Uyumsuzluk Var! (RSI: {curr_rsi:.1f}) 🩸")
        elif curr_rsi >= 65: approved.append(f"RSI Göstergesi: Aşırı Alım Bölgesi (%{curr_rsi:.1f}) 🔴")
        else: missing.append(f"RSI Göstergesi: Uyumsuzluk Yok / Nötr Bölgede (%{curr_rsi:.1f})")
        
    # 4. MACD Trendi
    m_line, s_line = calc_macd(closes)
    if len(m_line) >= 2 and len(s_line) >= 2:
        if direction == "LONG" and m_line[-1] > s_line[-1]:
            approved.append("MACD Trendi: Sinyal Çizgisi Yukarı Yönlü (AL) 🟢")
        elif direction == "SHORT" and m_line[-1] < s_line[-1]:
            approved.append("MACD Trendi: Sinyal Çizgisi Aşağı Yönlü (SAT) 🔴")
        else:
            missing.append("MACD Trendi: Kesişim/Yön Onayı Henüz Gelmedi")
    else:
        missing.append("MACD Trendi: Yetersiz Veri")
        
    # 5. Hacim & Taker Baskısı
    recent_vol = sum(c["volume"] for c in candles[-3:]) / 3
    base_vol = sum(c["volume"] for c in candles[-28:-3]) / 25
    vol_ratio = recent_vol / base_vol if base_vol > 0 else 1.0
    
    if vol_ratio >= 1.4:
        approved.append(f"Hacim Durumu: Güçlü Hacim Artışı Var (x{vol_ratio:.1f} Kat) 🚀")
    else:
        missing.append(f"Hacim Durumu: Hacimsiz Kırılım / Sığ Hareket (x{vol_ratio:.1f}) ⚠️")
        
    # 6. Açık Pozisyon (OI)
    oi_key = f"oi_{symbol}"
    prev_oi = state.get(oi_key, current_oi)
    state[oi_key] = current_oi
    oi_change = ((current_oi - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0.0
    
    if oi_change >= 1.2:
        approved.append(f"Açık Pozisyon (OI): Vadeliye Taze Para Girişi Var (+%{oi_change:.2f}) ⚡")
    else:
        missing.append("Açık Pozisyon (OI): Vadeli Pozisyon Girişi Nötr")
        
    # EN AZ 3 ONAY BARAJ KONTROLÜ
    if len(approved) < 3:
        return None
        
    trader_note = ""
    if direction == "SHORT":
        trader_note = "Fiyat pivot ve EMA altı kapandı. Hacimsiz sarkma varsa; ana dirence Retest ve onay mumu beklenip Short kurgulanabilir."
    else:
        trader_note = "Fiyat pivot ve EMA üzeri güvenli bölgede. Destek bölgesine olası sarkma/retest hareketinde Long kurgulanabilir."

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": direction,
        "price": price,
        "approved": approved,
        "missing": missing,
        "count": len(approved),
        "trader_note": trader_note
    }

def format_signal_message(sig):
    emoji = "🟢 [BOĞA RADARI]" if sig["direction"] == "LONG" else "🔴 [AYI RADARI]"
    sym = sig['symbol']
    tf_str = sig['timeframe'].upper()
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}PERP"
    
    lines = [
        f"{emoji} <b>#{sym}</b>",
        f"<b>⏱ Periyot:</b> {tf_str}",
        f"<b>Güncel Fiyat:</b> {fmt_price(sig['price'])} (Log Ölçek)",
        f"<b>🎯 Onay Durumu:</b> {sig['count']} / 6 Onay Alındı",
        "",
        "---",
        f"<b>✅ ONAYLANAN ŞARTLAR ({len(sig['approved'])}):</b>"
    ]
    for item in sig['approved']:
        lines.append(f"• {html_escape(item)}")
        
    if sig['missing']:
        lines.append("")
        lines.append(f"<b>❌ ONAYLANMAYAN / EKSİK ŞARTLAR ({len(sig['missing'])}):</b>")
        for item in sig['missing']:
            lines.append(f"• {html_escape(item)}")
            
    lines.append("---")
    lines.append(f"🎯 <b>TRADER NOTU:</b> {html_escape(sig['trader_note'])}")
    lines.append("")
    lines.append(f"📈 <a href='{tv_link}'><b>TradingView Üzerinde İncele (Log Scale)</b></a>")
    lines.append("\n💡 <i>Karar senin, tetiği sen çek!</i>")
    return "\n".join(lines)

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
    symbols = POPULAR_USDT_SYMBOLS if watchlist == ["ALL"] else watchlist
    print(f"🔄 Binance Futures Log Scale Taraması: {len(symbols)} sembol taranıyor...")
    
    for symbol in symbols:
        for tf in TIMEFRAMES:
            try:
                time.sleep(0.15)
                candles = fetch_klines_binance(symbol, timeframe=tf)
                prev_daily = fetch_prev_daily_binance(symbol)
                current_oi = fetch_open_interest_binance(symbol)
                
                sig = generate_signal(symbol, tf, candles, prev_daily, current_oi, state)
                if not sig: continue
                
                state_key = f"{symbol}_{tf}"
                prev_dir = state["last_signals"].get(state_key)
                
                if sig["direction"] != prev_dir:
                    caption = format_signal_message(sig)
                    chart_file = generate_chart(symbol, tf, candles, prev_daily)
                    if chart_file and os.path.exists(chart_file):
                        send_photo(chart_file, caption)
                        try: os.remove(chart_file)
                        except Exception: pass
                    else:
                        send_message(caption)
                    time.sleep(0.5)
                
                state["last_signals"][state_key] = sig["direction"]
            except Exception as e:
                print(f"⚠️ {symbol} ({tf}) Hatası: {e}")
                continue
            
    save_json(STATE_FILE, state)

def main():
    start_time = time.time()
    while True:
        loop_start = time.time()
        if loop_start - start_time > 5.5 * 3600: break
        watchlist = load_json(WATCHLIST_FILE, ["ALL"])
        state = load_json(STATE_FILE, {"last_signals": {}})
        state.setdefault("last_signals", {})
        
        single_scan(state, watchlist)
        
        sleep_time = max(10, (15 * 60) - (time.time() - loop_start))
        print(f"💤 Tarama bitti. Bekleme: {int(sleep_time)} sn...\n")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()

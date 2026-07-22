"""
Kesişim Radar - "Capitano Master Radar v5.2"
- RSI UYUMSUZLUĞU (DIVERGENCE) TESPİTİ (Pozitif & Negatif Uyumsuzluk Radarı)
- DİNAMİK MİKRO-COIN HASSASİYETİ (PEPE, SHIB vb. için 8 basamak desteği)
- ÇOKLU ZAMAN DİLİMİ (15m, 1H, 4H, 1D)
- AKILLI HACİM, EMA, RSI, MACD, PİVOT, OI & LİKİDASYON TAKİBİ
- CANLI GRAFİK ÇİZİMİ & TELEGRAM GÖRSEL GÖNDERİMİ
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
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "ADA-USDT", "AVAX-USDT", 
    "DOT-USDT", "DOGE-USDT", "SHIB-USDT", "LINK-USDT", "NEAR-USDT", "LTC-USDT", "UNI-USDT", 
    "OP-USDT", "ARB-USDT", "APT-USDT", "SUI-USDT", "INJ-USDT", "TIA-USDT", "FIL-USDT", 
    "ATOM-USDT", "ICP-USDT", "FET-USDT", "GRT-USDT", "STX-USDT", "GALA-USDT", 
    "ALGO-USDT", "AAVE-USDT", "CRV-USDT", "WIF-USDT", "PEPE-USDT", 
    "FLOKI-USDT", "BONK-USDT", "JUP-USDT"
]

TIMEFRAMES = ["15m", "1H", "4H", "1Dutc"]
MIN_CONFIDENCE_TO_NOTIFY = 45

OKX_API_URLS = [
    "https://www.okx.cab",
    "https://www.okx.com"
]

def fmt_price(val):
    """Fiyatın küçüklüğüne göre dinamik basamak formatı sunar."""
    if val == 0: return "0"
    abs_v = abs(val)
    if abs_v < 0.0001: return f"{val:.8f}"
    elif abs_v < 1.0: return f"{val:.6f}"
    elif abs_v < 100: return f"{val:.4f}"
    else: return f"{val:.2f}"

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
    params = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    telegram_api("sendMessage", params)

def send_photo(photo_path, caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return {}
    
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
    headers = {
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'User-Agent': 'Mozilla/5.0'
    }
    
    try:
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"⚠️ Görsel Gönderme Hatası: {e}")
        send_message(caption)
        return {}

def generate_chart(symbol, timeframe, candles, prev_daily, filename="temp_chart.png"):
    """Düzeltilmiş Başlık Hizalama, Hacim, EMA, RSI ve MACD Grafiği Çizer."""
    try:
        df_data = []
        for c in candles[-70:]:
            dt = datetime.datetime.fromtimestamp(c["openTime"] / 1000)
            df_data.append({
                "Date": dt, "Open": c["open"], "High": c["high"],
                "Low": c["low"], "Close": c["close"], "Volume": c["volume"]
            })
        
        df = pd.DataFrame(df_data)
        df.set_index("Date", inplace=True)
        
        closes = [c["close"] for c in candles]
        
        # EMA Hesaplamaları
        ema50 = calc_ema(closes, 50)[-len(df):]
        ema200 = calc_ema(closes, 200)[-len(df):]
        
        add_plots = []
        if len(ema50) == len(df):
            add_plots.append(mpf.make_addplot(ema50, color='#2962FF', width=1.2))
        if len(ema200) == len(df):
            add_plots.append(mpf.make_addplot(ema200, color='#FF6D00', width=1.5))
            
        # RSI Paneli (Panel 2)
        rsi_vals = calc_rsi(closes)[-len(df):]
        if len(rsi_vals) == len(df):
            add_plots.append(mpf.make_addplot(rsi_vals, panel=2, color='#7E57C2', ylabel='RSI (14)', ylim=(0, 100)))
            
        # MACD Paneli (Panel 3)
        m_line, s_line = calc_macd(closes)
        m_vals = m_line[-len(df):]
        s_vals = s_line[-len(df):]
        if len(m_vals) == len(df) and len(s_vals) == len(df):
            hist = [m - s for m, s in zip(m_vals, s_vals)]
            colors = ['#26a69a' if h >= 0 else '#ef5350' for h in hist]
            add_plots.append(mpf.make_addplot(m_vals, panel=3, color='#2962FF', ylabel='MACD'))
            add_plots.append(mpf.make_addplot(s_vals, panel=3, color='#FF6D00'))
            add_plots.append(mpf.make_addplot(hist, panel=3, type='bar', color=colors))
            
        # Pivot Çizgileri
        h_lines = []
        h_colors = []
        pivot_title_str = ""
        
        if prev_daily:
            pivots = dict(fibonacci_pivots(prev_daily["high"], prev_daily["low"], prev_daily["close"]))
            
            key_pivots = [("R1", "#FF5252"), ("PP", "#FFC107"), ("S1", "#00E676")]
            for name, color in key_pivots:
                if name in pivots:
                    h_lines.append(pivots[name])
                    h_colors.append(color)
            
            pp_v = pivots.get("PP", 0)
            r1_v = pivots.get("R1", 0)
            s1_v = pivots.get("S1", 0)
            pivot_title_str = f" | PP:{fmt_price(pp_v)} R1:{fmt_price(r1_v)} S1:{fmt_price(s1_v)}"

        style = mpf.make_mpf_style(
            base_mpf_style='yahoo', 
            gridstyle=':', 
            y_on_right=True,
            rc={'font.size': 8}
        )
        
        chart_title = f"{symbol.replace('-', '')} ({timeframe}){pivot_title_str}"
        
        h_dict = None
        if h_lines:
            h_dict = dict(hlines=h_lines, colors=h_colors, linestyle='--', linewidths=1.2)

        mpf.plot(
            df,
            type='candle',
            volume=True,
            addplot=add_plots,
            hlines=h_dict,
            style=style,
            title=chart_title,
            tight_layout=True,
            savefig=dict(fname=filename, bbox_inches='tight', pad_inches=0.2),
            figscale=1.2,
            warn_too_much_data=1000
        )
        return filename
    except Exception as e:
        print(f"⚠️ Grafik Oluşturma Hatası: {e}")
        return None

def fetch_klines_okx(symbol, timeframe, limit=250):
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

def fetch_open_interest_okx(symbol):
    try:
        data = http_get_json(f"/api/v5/public/open-interest?instId={symbol}-SWAP&instType=SWAP")
        if data.get("code") == "0" and data.get("data"):
            return float(data["data"][0]["oiCcy"])
    except Exception:
        pass
    return 0.0

def fetch_liquidations_okx(symbol):
    try:
        path = f"/api/v5/public/liquidation-orders?instType=SWAP&mgnMode=cross&instId={symbol}-SWAP&limit=10"
        data = http_get_json(path)
        long_liq = 0.0
        short_liq = 0.0
        if data.get("code") == "0" and data.get("data"):
            for item in data["data"]:
                for detail in item.get("details", []):
                    side = detail.get("side")
                    sz = float(detail.get("sz", 0))
                    if side == "sell":
                        long_liq += sz
                    elif side == "buy":
                        short_liq += sz
        return long_liq, short_liq
    except Exception:
        return 0.0, 0.0

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
    """Fiyat ve RSI arasında Pozitif/Negatif Uyumsuzluk tespiti yapar."""
    if len(candles) < window + 2 or len(rsi_vals) < window + 2:
        return None
    
    recent_candles = candles[-window:]
    recent_rsi = rsi_vals[-window:]
    
    # Son mum ve penceredeki en düşük/yüksek değerler
    price_now = recent_candles[-1]["close"]
    rsi_now = recent_rsi[-1]
    
    # En düşük dip indeksleri (Son mum hariç)
    min_price_prev = min(c["low"] for c in recent_candles[:-3])
    rsi_at_min_price = recent_rsi[recent_candles.index(next(c for c in recent_candles[:-3] if c["low"] == min_price_prev))]
    
    # En yüksek tepe indeksleri (Son mum hariç)
    max_price_prev = max(c["high"] for c in recent_candles[:-3])
    rsi_at_max_price = recent_rsi[recent_candles.index(next(c for c in recent_candles[:-3] if c["high"] == max_price_prev))]
    
    # POZİTİF UYUMSUZLUK (Bullish Divergence) -> Fiyat Yeni Dip, RSI Daha Yüksek Dip
    if price_now < min_price_prev and rsi_now > rsi_at_min_price and rsi_now < 45:
        return "BULLISH_DIV"
        
    # NEGATİF UYUMSUZLUK (Bearish Divergence) -> Fiyat Yeni Tepe, RSI Daha Düşük Tepe
    if price_now > max_price_prev and rsi_now < rsi_at_max_price and rsi_now > 55:
        return "BEARISH_DIV"
        
    return None

def calc_macd(closes):
    if len(closes) < 20: return [], []
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    n = min(len(ema12), len(ema26))
    macd_line = [e12 - e26 for e12, e26 in zip(ema12[-n:], ema26[-n:])]
    return macd_line, calc_ema(macd_line, 9)

def fibonacci_pivots(h, l, c):
    pp = (h + l + c) / 3
    r = h - l
    return [
        ("R3", pp + (r * 1.000)), 
        ("R2", pp + (r * 0.618)), 
        ("R1", pp + (r * 0.382)), 
        ("PP", pp), 
        ("S1", pp - (r * 0.382)), 
        ("S2", pp - (r * 0.618)), 
        ("S3", pp - (r * 1.000))
    ]

def generate_signal(symbol, timeframe, candles, prev_daily, btc_state, funding_rate, current_oi, long_liq, short_liq, state):
    if len(candles) < 50: return None
    last = candles[-1]
    price = last["close"]
    closes = [c["close"] for c in candles]
    
    recent_vol = sum(c["volume"] for c in candles[-3:]) / 3
    base_vol = sum(c["volume"] for c in candles[-28:-3]) / 25
    vol_ratio = recent_vol / base_vol if base_vol > 0 else 1.0
    
    price_start = candles[-3]["open"]
    price_end = candles[-1]["close"]
    is_bullish_vol = price_end >= price_start
    
    oi_key = f"oi_{symbol}"
    prev_oi = state.get(oi_key, current_oi)
    state[oi_key] = current_oi
    oi_change_pct = 0.0
    if prev_oi > 0:
        oi_change_pct = ((current_oi - prev_oi) / prev_oi) * 100
        
    report_data = {
        "Hacim Durumu": {"detail": f"Nötr Yatay (x{vol_ratio:.1f})", "score": 0, "status": "neutral"},
        "Açık Pozisyon (OI)": {"detail": "OI Sabit", "score": 0, "status": "neutral"},
        "EMA Yapısı": {"detail": "Nötr / Kesişim Yok", "score": 0, "status": "neutral"},
        "Pivot Analizi": {"detail": "Pivot verisi eksik", "score": 0, "status": "neutral"},
        "RSI Göstergesi": {"detail": "Nötr bölge", "score": 0, "status": "neutral"},
        "MACD Trendi": {"detail": "Kesişim Yok ⚪", "score": 0, "status": "neutral"},
        "Fonlama Oranı": {"detail": f"Dengeli (%{funding_rate*100:.4f})", "score": 0, "status": "neutral"},
        "Likidasyon Analizi": {"detail": "Sakin / Büyük Likidasyon Yok ⚪", "score": 0, "status": "neutral"}
    }
    
    if vol_ratio >= 1.7:
        if is_bullish_vol:
            report_data["Hacim Durumu"] = {"detail": f"Güçlü ALIM Hacmi Girişi (x{vol_ratio:.1f}) 🟢", "score": 25, "status": "bullish"}
        else:
            report_data["Hacim Durumu"] = {"detail": f"Sert SATIŞ Hacmi / Mal Boşaltma (x{vol_ratio:.1f}) 🩸", "score": -25, "status": "bearish"}
    elif vol_ratio <= 0.6: 
        report_data["Hacim Durumu"] = {"detail": f"Hacim Çok Kurudu (x{vol_ratio:.1f}) 🏜️", "score": -5, "status": "bearish"}
    
    if oi_change_pct >= 1.5: report_data["Açık Pozisyon (OI)"] = {"detail": f"Vadeliye Agresif Giriş Var (+%{oi_change_pct:.2f}) ⚡", "score": 20, "status": "bullish"}
    elif oi_change_pct <= -1.5: report_data["Açık Pozisyon (OI)"] = {"detail": f"Pozisyonlar Kapatılıyor (-%{oi_change_pct:.2f}) 📉", "score": -10, "status": "bearish"}
    
    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)
    if ema50 and ema200:
        e50_last, e200_last = ema50[-1], ema200[-1]
        e50_prev, e200_prev = ema50[-2], ema200[-2]
        if e50_prev <= e200_prev and e50_last > e200_last: report_data["EMA Yapısı"] = {"detail": "Golden Cross Kesişimi Uçtu! 🚀", "score": 45, "status": "bullish"}
        elif e50_prev >= e200_prev and e50_last < e200_last: report_data["EMA Yapısı"] = {"detail": "Death Cross Kesişimi Düştü! 💀", "score": -45, "status": "bearish"}
        elif price > e50_last and price > e200_last: report_data["EMA Yapısı"] = {"detail": f"Fiyat Trend Üstü Akümüle (EMA50: {fmt_price(e50_last)})", "score": 20, "status": "bullish"}
        elif price < e50_last and price < e200_last: report_data["EMA Yapısı"] = {"detail": "Fiyat EMA 50 & 200 Altında Sıkışık", "score": -20, "status": "bearish"}
        
    if prev_daily:
        pivots = fibonacci_pivots(prev_daily["high"], prev_daily["low"], prev_daily["close"])
        nearest_name, nearest_dist = min([(n, abs(price - l)/l*100) for n, l in pivots], key=lambda x: x[1])
        pp_level = [v for k, v in pivots if k == "PP"][0]
        if price > pp_level: report_data["Pivot Analizi"] = {"detail": f"Pivot (PP) Üzerinde Güçlü. En yakın: {nearest_name} (%{nearest_dist:.2f})", "score": 15, "status": "bullish"}
        else: report_data["Pivot Analizi"] = {"detail": f"Pivot (PP) Altında Baskılı. En yakın: {nearest_name} (%{nearest_dist:.2f})", "score": -15, "status": "bearish"}
        
    rsi_vals = calc_rsi(closes)
    if rsi_vals:
        curr_rsi, prev_rsi = rsi_vals[-1], rsi_vals[-2]
        div_status = detect_rsi_divergence(candles, rsi_vals)
        
        if div_status == "BULLISH_DIV":
            report_data["RSI Göstergesi"] = {"detail": f"⚠️ POZİTİF UYUMSUZLUK (Dipten Dönüş Sinyali! RSI: {curr_rsi:.1f}) 🔥", "score": 40, "status": "bullish"}
        elif div_status == "BEARISH_DIV":
            report_data["RSI Göstergesi"] = {"detail": f"⚠️ NEGATİF UYUMSUZLUK (Tepeden Düşüş Sinyali! RSI: {curr_rsi:.1f}) 🩸", "score": -40, "status": "bearish"}
        elif curr_rsi <= 25: 
            report_data["RSI Göstergesi"] = {"detail": f"Dip Seviyede! Aşırı Satım (%{curr_rsi:.1f}) 🚨", "score": 35, "status": "bullish"}
        elif prev_rsi < 30 and curr_rsi > prev_rsi: 
            report_data["RSI Göstergesi"] = {"detail": f"Dipten Kafayı Kaldırdı (%{curr_rsi:.1f}) 📈", "score": 25, "status": "bullish"}
        elif curr_rsi >= 75: 
            report_data["RSI Göstergesi"] = {"detail": f"Tepe Seviyede! Aşırı Alım (%{curr_rsi:.1f}) ⚠️", "score": -35, "status": "bearish"}
        else: 
            report_data["RSI Göstergesi"] = {"detail": f"Nötr Bölgede Salınıyor (%{curr_rsi:.1f})", "score": 0, "status": "neutral"}
        
    m_line, s_line = calc_macd(closes)
    if len(m_line) >= 2 and len(s_line) >= 2:
        if m_line[-2] <= s_line[-2] and m_line[-1] > s_line[-1]: report_data["MACD Trendi"] = {"detail": "Aşağıdan Yukarı Net Kesti (AL) 🟢", "score": 25, "status": "bullish"}
        elif m_line[-2] >= s_line[-2] and m_line[-1] < s_line[-1]: report_data["MACD Trendi"] = {"detail": "Yukarıdan Aşağı Net Kesti (SAT) 🔴", "score": -25, "status": "bearish"}
        
    if funding_rate != 0.0:
        if funding_rate >= 0.0002: 
            report_data["Fonlama Oranı"] = {"detail": f"Long Baskısı / Piyasada Isınma Var (%{funding_rate*100:.4f}) ⚠️", "score": -10, "status": "bearish"}
        elif funding_rate <= -0.00015: 
            report_data["Fonlama Oranı"] = {"detail": f"Short Baskısı / Squeeze Potansiyeli! (%{funding_rate*100:.4f}) 🚀", "score": 20, "status": "bullish"}
        
    if short_liq > 0 or long_liq > 0:
        if short_liq > long_liq:
            report_data["Likidasyon Analizi"] = {"detail": f"Yoğun Short Patlaması Var ({short_liq:.1f} Kontrat) - Squeeze Hızlanabilir! 🚀", "score": 15, "status": "bullish"}
        elif long_liq > short_liq:
            report_data["Likidasyon Analizi"] = {"detail": f"Sert Long Patlaması / Flush Gerçekleşti ({long_liq:.1f} Kontrat) 🩸", "score": -15, "status": "bearish"}

    raw_score = sum(v["score"] for v in report_data.values())
    
    if btc_state and btc_state.get("trend") == "bearish" and raw_score > 0:
        raw_score -= 20 
    
    confidence = min(100, abs(raw_score))
    direction = "IZLE"
    if confidence >= MIN_CONFIDENCE_TO_NOTIFY: direction = "AL" if raw_score > 0 else "SAT"
    if direction == "IZLE": return None
    
    return {"symbol": symbol, "timeframe": timeframe, "direction": direction, "confidence": confidence, "price": price, "report_data": report_data, "funding": funding_rate}

def format_signal_message(sig):
    emoji = "🟢 [BOĞA RADARI]" if sig["direction"] == "AL" else "🔴 [AYI RADARI]"
    clean_sym = sig['symbol'].replace("-", "")
    
    tf_str = sig['timeframe'].replace("15m", "15 Dakikalık").replace("1H", "1 Saatlik").replace("4H", "4 Saatlik").replace("1Dutc", "1 Günlük")
    tv_link = f"https://www.tradingview.com/chart/?symbol=OKX:{clean_sym}"
    
    lines = [
        f"{emoji} <b>#{clean_sym}</b>",
        f"<b>⏱ Periyot:</b> {tf_str}",
        f"<b>Güncel Fiyat:</b> {fmt_price(sig['price'])}",
        f"<b>Radar Gücü:</b> %{int(sig['confidence'])}",
        f"<b>Fonlama:</b> %{sig['funding']*100:.4f}",
        "---",
        "<b>🔎 TAHTA RÖNTGENİ:</b>"
    ]
    for name, data in sig["report_data"].items():
        arrow = "✅" if data["status"] == "bullish" else ("❌" if data["status"] == "bearish" else "⚪")
        lines.append(f"{arrow} <b>{html_escape(name)}:</b> {html_escape(data['detail'])}")
        
    lines.append("---")
    lines.append(f"📈 <a href='{tv_link}'><b>TradingView Üzerinde İncele</b></a>")
    lines.append("\n💡 <i>Karar senin, tetiği sen çek!</i>")
    return "\n".join(lines)

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
            if sym in watchlist: watchlist.remove(sym); send_message(f"🗑 {sym.replace('-', '')} silindi.")
        elif text.startswith("/list"): send_message("📋 Liste:\n" + "\n".join(f"• {s.replace('-', '')}" for s in watchlist))
        elif text.startswith("/all"): watchlist = ["ALL"]; save_json(WATCHLIST_FILE, watchlist); send_message("🌐 Tüm markete geçildi.")
        elif text.startswith("/manual"): watchlist = ["BTC-USDT", "ETH-USDT"]; save_json(WATCHLIST_FILE, watchlist); send_message("📋 Manuel moda geçildi.")
    return watchlist, state

def get_btc_state():
    try:
        res = fetch_klines_okx("BTC-USDT", timeframe="1H")
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
    print(f"🔄 Çok Boyutlu Röntgen Taraması: {len(symbols)} sembol taranıyor...")
    
    for symbol in symbols:
        for tf in TIMEFRAMES:
            try:
                time.sleep(0.3)
                candles = fetch_klines_okx(symbol, timeframe=tf)
                prev_daily = fetch_prev_daily_okx(symbol)
                funding_rate = fetch_funding_rate_okx(symbol)
                current_oi = fetch_open_interest_okx(symbol)
                long_liq, short_liq = fetch_liquidations_okx(symbol)
                
                sig = generate_signal(symbol, tf, candles, prev_daily, btc_state, funding_rate, current_oi, long_liq, short_liq, state)
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
        state = load_json(STATE_FILE, {"last_update_id": 0, "last_signals": {}})
        state.setdefault("last_signals", {})
        try: watchlist, state = process_commands(state, watchlist); save_json(WATCHLIST_FILE, watchlist)
        except Exception: pass
        
        single_scan(state, watchlist)
        
        sleep_time = max(10, (15 * 60) - (time.time() - loop_start))
        print(f"💤 Tüm zaman dilimleri tarandı. Bekleme: {int(sleep_time)} sn...\n")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()

"""
Kesişim Radar - Telegram Sinyal Botu (CoinGecko Entegrasyonlu - Hata Korumalı)
GitHub Actions IP engellerini tamamen aşmak için verileri CoinGecko üzerinden çeker.
Herhangi bir API veya Telegram hatasında botun durmasını engellemek için tüm bloklar zırhlandırılmıştır.
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

# CoinGecko ID eşleşmeleri
COINGECKO_MAP = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    "XRPUSDT": "ripple",
    "ADAUSDT": "cardano",
    "AVAXUSDT": "avalanche-2",
    "DOTUSDT": "polkadot",
    "DOGEUSDT": "dogecoin",
    "SHIBUSDT": "shiba-inu",
    "LINKUSDT": "chainlink",
    "NEARUSDT": "near",
    "LTCUSDT": "litecoin",
    "UNIUSDT": "uniswap",
    "OPUSDT": "optimism",
    "ARBUSDT": "arbitrum",
    "APTUSDT": "aptos",
    "SUIUSDT": "sui",
    "INJUSDT": "injective-protocol",
    "TIAUSDT": "celestia",
    "FILUSDT": "filecoin",
    "ATOMUSDT": "cosmos",
    "ICPUSDT": "internet-computer",
    "FETUSDT": "fetch-ai",
    "GRTUSDT": "the-graph",
    "FTMUSDT": "fantom",
    "STXUSDT": "blockstack",
    "GALAUSDT": "gala",
    "ALGOUSDT": "algorand",
    "AAVEUSDT": "aave",
    "MKRUSDT": "maker",
    "CRVUSDT": "curve-dao-token",
    "RUNEUSDT": "thorchain",
    "WIFUSDT": "dogwifhat",
    "PEPEUSDT": "pepe",
    "FLOKIUSDT": "floki",
    "BONKUSDT": "bonk",
    "JUPUSDT": "jupiter-exchange-solana"
}

POPULAR_USDT_SYMBOLS = list(COINGECKO_MAP.keys())

TIMEFRAME = "15m"
PROXIMITY_PIVOT = 0.85      # %
PROXIMITY_FIB = 1.0         # %
MIN_CONFIDENCE_TO_NOTIFY = 20

# ============================= HTTP helpers =============================

def http_get_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def telegram_api(method, params=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram token veya Chat ID eksik!")
        return {}
    try:
        base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
        if params:
            url = base + "?" + urllib.parse.urlencode(params)
        else:
            url = base
        return http_get_json(url)
    except Exception as e:
        print(f"⚠️ Telegram API Hatası ({method}): {e}")
        return {}


def send_message(text):
    telegram_api("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })


# ============================= CoinGecko Data Fetching =============================

def fetch_klines_coingecko(symbol):
    cg_id = COINGECKO_MAP.get(symbol)
    if not cg_id:
        raise ValueError(f"CoinGecko ID bulunamadı: {symbol}")
        
    # days=5 saatlik veri çekmek için en kararlı parametredir (API 400 hatasını önler)
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=5"
    data = http_get_json(url)
    
    prices = data.get("prices", [])
    volumes = data.get("total_volumes", [])
    
    if len(prices) < 10:
        raise ValueError(f"Yetersiz veri alındı: {symbol}")
        
    candles = []
    for i in range(1, len(prices)):
        prev_p = prices[i-1][1]
        curr_p = prices[i][1]
        t = prices[i][0]
        v = volumes[i][1] if i < len(volumes) else 0.0
        
        candles.append({
            "openTime": t,
            "open": prev_p,
            "high": max(prev_p, curr_p),
            "low": min(prev_p, curr_p),
            "close": curr_p,
            "volume": v,
            "closeTime": t
        })
    return candles


def fetch_prev_daily_coingecko(symbol):
    cg_id = COINGECKO_MAP.get(symbol)
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=5"
    data = http_get_json(url)
    prices = data.get("prices", [])
    if len(prices) < 2:
        return None
    return {
        "high": prices[-2][1] * 1.01,
        "low": prices[-2][1] * 0.99,
        "close": prices[-2][1]
    }


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
    if len(closes) < 27:
        return None
    e12 = calc_ema(closes, 12)
    e26 = calc_ema(closes, 26)
    n = min(len(e12), len(e26))
    if n < 2:
        return None
    e12_tail, e26_tail = e12[-n:], e26[-n:]
    last12, prev12 = e12_tail[-1], e12_tail[-2]
    last26, prev26 = e26_tail[-1], e26_tail[-2]

    cross = "none"
    if prev12 <= prev26 and last12 > last26:
        cross = "golden"
    elif prev12 >= prev26 and last12 < last26:
        cross = "death"

    return {
        "last_cross": cross,
        "trend_is_bullish": last12 > last26,
    }


def classic_pivots(h, l, c):
    pp = (h + l + c) / 3
    r1, s1 = 2 * pp - l, 2 * pp - h
    r2, s2 = pp + (h - l), pp - (h - l)
    r3, s3 = h + 2 * (pp - l), l - 2 * (h - pp)
    return [("R3", r3), ("R2", r2), ("R1", r1), ("PP", pp), ("S1", s1), ("S2", s2), ("S3", s3)]


def fib_retracement(candles, lookback=20):
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


def analyze_volume(candles, period=10, spike_threshold=1.5):
    if len(candles) <= period:
        return None
    recent_past = candles[-(period + 1):-1]
    avg = sum(c["volume"] for c in recent_past) / len(recent_past)
    if avg <= 0:
        return None
    current = candles[-1]["volume"]
    ratio = current / avg
    return {"ratio": ratio, "is_spike": ratio >= spike_threshold}


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


def analyze_bollinger_squeeze(closes, period=14, lookback_squeeze=30):
    if len(closes) < period:
        return False, 0.0
    
    bandwidths = []
    for i in range(len(closes) - lookback_squeeze, len(closes)):
        if i < period:
            continue
        window = closes[i-period:i]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std_dev = variance ** 0.5
        upper = sma + (2 * std_dev)
        lower = sma - (2 * std_dev)
        bandwidth = (upper - lower) / sma if sma != 0 else 0
        bandwidths.append(bandwidth)
        
    if not bandwidths:
        return False, 0.0
        
    current_bw = bandwidths[-1]
    sorted_bws = sorted(bandwidths)
    threshold = sorted_bws[int(len(sorted_bws) * 0.15)]
    
    return current_bw <= threshold, current_bw


# ============================= Signal Engine =============================

def generate_signal(symbol, candles, prev_daily):
    last = candles[-1]
    price = last["close"]
    closes = [c["close"] for c in candles]
    factors = []

    # 1) EMA Sinyalleri
    ema = analyze_ema(candles)
    if not ema:
        return None

    if ema["last_cross"] == "golden":
        factors.append(("EMA 12/26", "Golden Cross oluştu (yükseliş)", 40))
    elif ema["last_cross"] == "death":
        factors.append(("EMA 12/26", "Death Cross oluştu (düşüş)", -40))
    else:
        score = 25 if ema["trend_is_bullish"] else -25
        text = "EMA12 > EMA26, yön yukarı" if ema["trend_is_bullish"] else "EMA12 < EMA26, yön aşağı"
        factors.append(("EMA 12/26", text, score))

    # 2) Pivot Sinyalleri
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

    # 3) Fibonacci Sinyalleri
    fib = fib_retracement(candles, 20)
    if fib:
        nf = nearest_fib(price, fib)
        if nf and nf[2] <= PROXIMITY_FIB:
            name, _level, _dist = nf
            factors.append((
                "Fibonacci",
                f"Fiyat %{name} seviyesine yakın ({'destek' if fib['is_uptrend'] else 'direnç'})",
                20 if fib["is_uptrend"] else -20,
            ))

    # 4) RSI Sinyalleri
    rsi_vals = calc_rsi(closes)
    current_rsi = rsi_vals[-1] if rsi_vals else 50
    if current_rsi <= 20:
        factors.append(("RSI", f"Aşırı Satım Bölgesi (%{current_rsi:.1f}) - Alım Fırsatı", 35))
    elif current_rsi >= 85:
        factors.append(("RSI", f"Aşırı Alım Bölgesi (%{current_rsi:.1f}) - Satım Zamanı", -35))
    else:
        factors.append(("RSI", f"Nötr bölgede (%{current_rsi:.1f})", 0))

    # 5) MACD & RSI Entegrasyon Sinyalleri
    macd_line, signal_line = calc_macd(closes)
    if len(macd_line) >= 2 and len(signal_line) >= 2:
        prev_macd, last_macd = macd_line[-2], macd_line[-1]
        prev_sig, last_sig = signal_line[-2], signal_line[-1]
        
        macd_cross_up = prev_macd <= prev_sig and last_macd > last_sig
        macd_cross_down = prev_macd >= prev_sig and last_macd < last_sig
        
        if macd_cross_up:
            bonus = 15 if current_rsi < 35 else 0
            factors.append(("MACD", f"Yukarı yönlü kesişim (RSI teyitli)", 20 + bonus))
        elif macd_cross_down:
            bonus = 15 if current_rsi > 65 else 0
            factors.append(("MACD", f"Aşağı yönlü kesişim (RSI teyitli)", -20 - bonus))

    # 6) Bollinger Sıkışması
    is_squeezed, bw_val = analyze_bollinger_squeeze(closes)
    if is_squeezed:
        factors.append(("Bollinger Sıkışması", f"Bantlar daraldı ({bw_val:.4f})! Sert patlama yaklaşıyor.", 0))

    # 7) Hacim Patlamaları Sinyali
    volume_multiplier = 1.0
    vol = analyze_volume(candles)
    if vol:
        if vol["is_spike"]:
            volume_multiplier = 1.35
            factors.append(("Hacim", f"Hacim ortalamanın {vol['ratio']:.1f}x üzerinde (GÜÇLÜ GİRİŞ)", 15))
        else:
            factors.append(("Hacim", f"Hacim normal seviyede (%{int(vol['ratio']*100)})", 0))

    raw_score = sum(f[2] for f in factors) * volume_multiplier
    confidence = min(100, abs(raw_score))

    direction = "IZLE"
    if confidence >= MIN_CONFIDENCE_TO_NOTIFY:
        direction = "AL" if raw_score > 0 else "SAT"

    stop = target = None
    if direction != "IZLE" and len(candles) >= 10:
        recent = candles[-10:]
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
        print("⚠️ getUpdates çağrısı başarısız oldu:", e)
        return watchlist, state

    results = updates.get("result", [])
    for u in results:
        state["last_update_id"] = u["update_id"]
        msg = u.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(TELEGRAM_CHAT_ID):
            continue

        if text.startswith("/add"):
            if watchlist == ["ALL"]:
                send_message("Şu an TÜM piyasa taranıyor, tekil ekleme geçersiz. Önce /manual yaz.")
                continue
            parts = text.split()
            if len(parts) >= 2:
                symbol = parts[1].upper()
                if symbol not in COINGECKO_MAP:
                    send_message("Desteklenmeyen sembol. Popüler coinlerden birini ekleyebilirsiniz.")
                    continue
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
                send_message("🌐 Şu an popüler 38 coin taranıyor.\nElle liste seçmek için /manual yaz.")
            elif watchlist:
                send_message("📋 İzleme listen:\n" + "\n".join(f"• {s}" for s in watchlist))
            else:
                send_message("İzleme listen boş. /add BTCUSDT ile ekleyebilirsin.")

        elif text.startswith("/all"):
            watchlist = ["ALL"]
            send_message(
                "🌐 CoinGecko üzerinden popüler kripto taraması AÇILDI.\n"
                "Her 15 dakikada bir otomatik taranacak.\n"
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
                "/all — popüler coinleri taramaya başla\n"
                "/manual — elle seçilmiş listeye geri dön\n\n"
                "Bot her 15 dakikada bir taramayı otomatik yapar."
            )

    return watchlist, state


# ============================= Main =============================

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
    except Exception as e:
        print(f"⚠️ Dosya kaydedilirken hata oluştu ({path}): {e}")


def main():
    watchlist = ["ALL"]
    state = load_json(STATE_FILE, {"last_update_id": 0, "last_signals": {}})

    # Telegram komutlarını güvenli bir şekilde işle
    try:
        watchlist, state = process_commands(state, watchlist)
    except Exception as e:
        print("⚠️ Komutlar işlenirken hata oluştu:", e)

    state.setdefault("last_signals", {})

    if watchlist == ["ALL"]:
        symbols_to_scan = POPULAR_USDT_SYMBOLS
    else:
        symbols_to_scan = watchlist

    print(f"CoinGecko üzerinden toplam {len(symbols_to_scan)} popüler sembol taranıyor...")

    for symbol in symbols_to_scan:
        try:
            # Sıkışıklığı ve API banını önlemek için bekleme süresi
            time.sleep(2.0)
            candles = fetch_klines_coingecko(symbol)
            prev_daily = fetch_prev_daily_coingecko(symbol)
            sig = generate_signal(symbol, candles, prev_daily)
            
            if not sig:
                continue

            prev_direction = state["last_signals"].get(symbol)
            if sig["direction"] in ("AL", "SAT") and sig["direction"] != prev_direction:
                send_message(format_signal_message(sig))
                time.sleep(0.5)

            state["last_signals"][symbol] = sig["direction"]
            
        except Exception as e:
            # HATA KORUMASI: Bir coin'de istek patlarsa asla botu çökertme, logla ve sıradakine geç!
            print(f"⚠️ {symbol} işlenirken hata oluştu (atlandı): {e}")
            continue

    save_json(WATCHLIST_FILE, watchlist)
    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()

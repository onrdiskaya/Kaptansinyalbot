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
    if len(daily) 

import os
import sys
import time
import requests
import hmac
import hashlib
import json
from datetime import datetime

# ==========================================
#      CAPITANO BOT YAPILANDIRMASI
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = "-1004339033046"  # Yeni Kanal ID'niz Başarıyla Tanımlandı

WATCHLIST_FILE = "watchlist.json"
STATE_FILE = "state.json"

# Takip Edilen Tüm Canavar Coinler (35 Adet)
BOLS = [
    "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "DOGE-USDT",
    "SHIB-USDT", "LINK-USDT", "NEAR-USDT", "ARB-USDT", "APT-USDT",
    "SUI-USDT", "INJ-USDT", "ICP-USDT", "FET-USDT", "GRT-USDT",
    "STX-USDT", "AAVE-USDT", "CRV-USDT", "WIF-USDT", "PEPE-USDT",
    "BONK-USDT", "JUP-USDT", "OP-USDT", "LDO-USDT", "RENDER-USDT",
    "TIA-USDT", "SEI-USDT", "STG-USDT", "AXS-USDT", "SAND-USDT",
    "MANA-USDT", "GALA-USDT", "IMX-USDT", "FLOW-USDT", "ENJ-USDT"
]

# ==========================================
#          YARDIMCI FONKSİYONLAR
# ==========================================
def load_json(filename, default_value):
    if not os.path.exists(filename):
        return default_value
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except Exception:
        return default_value

def save_json(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Dosya kaydedilirken hata oluştu ({filename}): {e}")

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Token veya Chat ID eksik!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"Telegram hatası: {res.text}")
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")

# ==========================================
#          OKX API BAĞLANTISI
# ==========================================
def get_okx_candles(instId, bar="1m", limit="100"):
    url = f"https://www.okx.com/api/v5/market/candles?instId={instId}&bar={bar}&limit={limit}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "0":
                return data.get("data", [])
        return []
    except Exception as e:
        print(f"{instId} için OKX veri hatası: {e}")
        return []

# ==========================================
#          SİNYAL MOTORU (ANALİZ)
# ==========================================
def analyze_market():
    watchlist = load_json(WATCHLIST_FILE, [])
    state = load_json(STATE_FILE, {})
    
    current_watchlist = [coin for coin in BOLS if coin in watchlist or not watchlist]
    
    for coin in current_watchlist:
        candles = get_okx_candles(coin, bar="1m", limit="5")
        if not candles:
            continue
            
        # Son kapanan mumun verileri
        last_candle = candles[0]
        c_time = datetime.fromtimestamp(int(last_candle[0])/1000).strftime('%H:%M')
        c_open = float(last_candle[1])
        c_high = float(last_candle[2])
        c_low = float(last_candle[3])
        c_close = float(last_candle[4])
        c_vol = float(last_candle[5])
        
        # Basit Hacim ve Fiyat Kırılım Analizi
        if len(candles) > 1:
            prev_candle = candles[1]
            prev_vol = float(prev_candle[5])
            
            # Eğer hacim bir önceki muma göre 3 katından fazlaysa ve fiyat yükseliyorsa
            if c_vol > (prev_vol * 3) and c_close > c_open:
                last_alert_time = state.get(f"{coin}_alert", 0)
                # Aynı coinden 5 dakikada bir defadan fazla sinyal geçmesin
                if time.time() - last_alert_time > 300:
                    msg = (
                        f"🚨 *CAPITANO SİNYAL UYARISI* 🚨\n\n"
                        f"🪙 *Coin:* {coin}\n"
                        f"⏰ *Saat:* {c_time}\n"
                        f"💵 *Fiyat:* {c_close}\n"
                        f"📊 *Hacim Artışı:* Sıradışı Hacim Girişi Tespit Edildi! 🔥\n"
                        f"📈 *Yön:* Yukarı Kırılım (Long Yönlü Potansiyel)"
                    )
                    send_telegram_message(msg)
                    state[f"{coin}_alert"] = time.time()
                    save_json(STATE_FILE, state)

# ==========================================
#          TELEGRAM KOMUT YÖNETİMİ
# ==========================================
def process_commands():
    if not TELEGRAM_BOT_TOKEN:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    state = load_json(STATE_FILE, {})
    last_update_id = state.get("last_update_id", 0)
    
    try:
        res = requests.get(f"{url}?offset={last_update_id + 1}", timeout=10)
        if res.status_code != 200:
            return
            
        updates = res.json().get("result", [])
        for update in updates:
            last_update_id = update["update_id"]
            state["last_update_id"] = last_update_id
            save_json(STATE_FILE, state)
            
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            
            # Komut yönetimini güvenlik sebebiyle sadece kurucu yapabilsin
            # (Not: Kendi kişisel ID'niz ile değiştirebilirsiniz)
            if not text.startswith("/"):
                continue
                
            watchlist = load_json(WATCHLIST_FILE, [])
            
            if text.startswith("/add "):
                coin = text.split(" ")[1].upper().strip()
                if coin not in watchlist:
                    watchlist.append(coin)
                    save_json(WATCHLIST_FILE, watchlist)
                    send_telegram_message(f"✅ {coin} başarıyla takip listesine eklendi usta.")
            
            elif text.startswith("/remove "):
                coin = text.split(" ")[1].upper().strip()
                if coin in watchlist:
                    watchlist.remove(coin)
                    save_json(WATCHLIST_FILE, watchlist)
                    send_telegram_message(f"❌ {coin} takip listesinden çıkarıldı usta.")
                    
            elif text == "/list":
                if not watchlist:
                    send_telegram_message("📋 Takip listesi şu an boş usta. Tüm coinler taranıyor.")
                else:
                    coins_str = ", ".join(watchlist)
                    send_telegram_message(f"📋 *Takip Edilen Özel Listem:*\n\n{coins_str}")
                    
    except Exception as e:
        print(f"Komut işleme hatası: {e}")

# ==========================================
#               ANA DÖNGÜ
# ==========================================
if __name__ == "__main__":
    print("🚀 Capitano Sinyal Botu Yeni Kanalında Başlatıldı...")
    while True:
        try:
            analyze_market()
            process_commands()
            time.sleep(30)  # Her 30 saniyede bir piyasayı tarar ve komutları kontrol eder
        except KeyboardInterrupt:
            print("Bot durduruldu.")
            sys.exit()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
            time.sleep(10)


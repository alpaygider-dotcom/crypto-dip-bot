import requests
import time
from statistics import mean

# ==========================================
# AYARLAR & ENTEGRASYON
# ==========================================
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Accept": "application/json"
}

SPOT_URL = "https://api.binance.com"
FUTURES_URL = "https://fapi.binance.com"

# STABİL ÇALIŞAN 73 PARİTELİK LİSTEMİZ
COINS = [
    "1000LUNC", "1000SHIB", "1000XEC", "ADA", "AGLD", "APE", "APT", "AR", "ARB", "ARKM",
    "ATOM", "AVAX", "BANANA", "BCH", "BLUR", "BNB", "BONK", "CELO", "CRV", "CYBER",
    "DOGE", "DOT", "DYDX", "EGLD", "ENS", "EOS", "ETC", "ETH", "FIL", "FLOW",
    "FTM", "FXS", "GALA", "GMT", "GRT", "ICP", "IMX", "INJ", "IOTA", "JUP",
    "LDO", "LINK", "LTC", "LUNA", "MAGIC", "MANA", "MATIC", "MINA", "MKR", "NEAR",
    "NEO", "OP", "ORDI", "PEPE", "PYTH", "RNDR", "RUNE", "SAND", "SEI", "SOL",
    "STX", "SUI", "TIA", "TRX", "UMA", "UNI", "WIF", "WORLD", "XLM", "XMR",
    "XRP", "YGG", "ZETA"
]

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except:
        pass

def main():
    print("🔥 BOT HİBRİT MODDA BAŞLATILDI: ZIRHLI (VADELİ) & ACABA (SPOT+VADELİ) 🔥")
    sent_dict = {}
    
    while True:
        print(f"\n[{time.strftime('%H:%M:%S')}] {len(COINS)} Parite Eşzamanlı Taranıyor...")
        
        # MARKET GÜVENLİĞİ: BTC Vadeli Hacim Patlaması Kontrolü
        btc_is_pumping = False
        try:
            btc_res = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": "BTCUSDT", "interval": "5m", "limit": 20}, headers=HEADERS, timeout=3).json()
            btc_vols = [float(k[5]) for k in btc_res]
            if (btc_vols[-1] / mean(btc_vols[:-2])) > 2.5:
                btc_is_pumping = True
        except:
            pass

        if btc_is_pumping:
            print("⚠️ BTC Vadeli tahtasında aşırı agresif hacim! Tarama 1 dk askıya alınıyor...")
            time.sleep(60)
            continue

        # ANA TARAMA DÖNGÜSÜ
        for coin in COINS:
            symbol = f"{coin}USDT"
            try:
                time.sleep(0.2) # Rate limit (API Ban) yememek için her paritede güvenli es
                
                # ----------------=======================================----------------
                # ORTAK ADIM: VADELİ (FUTURES) 5M MUM VE TAKER BUY VERİLERİ
                # ----------------=======================================----------------
                f_res = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": symbol, "interval": "5m", "limit": 20}, headers=HEADERS, timeout=3)
                if f_res.status_code != 200:
                    continue
                f_klines = f_res.json()
                if len(f_klines) < 20:
                    continue
                
                f_prices = [float(k[4]) for k in f_klines]
                f_volumes = [float(k[5]) for k in f_klines]
                
                f_open = float(f_klines[-1][1])
                f_close = float(f_klines[-1][4])
                f_vol = float(f_klines[-1][5])
                taker_buy_vol = float(f_klines[-1][9])
                
                # ❌ GÜVENLİK FİLTRESİ 1: Mum kırmızıysa veya nötrse geç (Yükselen mum arıyoruz)
                if f_close <= f_open:
                    continue
                
                # ❌ GÜVENLİK FİLTRESİ 2: Taker Buy Güç Kontrolü (Görsel 1'deki istek)
                # Fake hacmi, wash trading'i ve satış baskılı mumları eler.
                if taker_buy_vol < (f_vol * 0.55):
                    continue
                
                # ❌ GÜVENLİK FİLTRESİ 3: Fiyat önceki mumların ortalamasının altındaysa geç
                if f_close < mean(f_prices[:-1]):
                    continue

                # ❌ GÜVENLİK FİLTRESİ 4: Vadeli tarafta son 1.5 saatlik yataylık/sıkışma kontrolü
                f_past_prices = f_prices[:-1]
                if (max(f_past_prices) - min(f_past_prices)) / min(f_past_prices) > 0.04:
                    continue

                # ❌ GÜVENLİK FİLTRESİ 5: Vadeli Hacim Patlama Katsayısı Kontrolü
                f_avg_vol = mean(f_volumes[:-2])
                if f_avg_vol == 0:
                    continue
                f_ratio = f_vol / f_avg_vol
                
                # Eğer vadeli tarafta en az 3 katı bir hacim patlaması yoksa diğer sorgulara hiç geçme
                if f_ratio < 3.0:
                    continue

                # ----------------=======================================----------------
                # MOD 1: ZIRHLI SİNYAL DEĞERLENDİRMESİ (SADECE VADELİ METRİKLERİ)
                # ----------------=======================================----------------
                # Şartlar: Güçlü hacim patlaması (>5.0x) ve ek vadeli metriklerinin tam doğrulanması
                if f_ratio >= 5.0:
                    try:
                        # 1. Funding Oranı Kontrolü (Görsel 3: funding < 0.015)
                        funding_res = requests.get(f"{FUTURES_URL}/fapi/v1/premiumIndex", params={"symbol": symbol}, headers=HEADERS, timeout=3).json()
                        funding_rate = float(funding_res.get('lastFundingRate', 0))
                        
                        # 2. OI (Open Interest) Kontrolü (Görsel 4: OI > +%2 artış fiyat yatayken)
                        oi_res = requests.get(f"{FUTURES_URL}/fapi/v1/openInterestHist", params={"symbol": symbol, "period": "5m", "limit": 2}, headers=HEADERS, timeout=3).json()
                        
                        # 3. L/S Hesap Oranı Kontrolü (Görsel 6: Fiyat yükselirken Long azalıyorsa = Short Squeeze)
                        ls_res = requests.get(f"{FUTURES_URL}/futures/data/globalLongShortAccountRatio", params={"symbol": symbol, "period": "5m", "limit": 2}, headers=HEADERS, timeout=3).json()
                        
                        if funding_rate < 0.015 and len(oi_res) >= 2 and len(ls_res) >= 2:
                            prev_oi = float(oi_res[0]['sumOpenInterest'])
                            curr_oi = float(oi_res[1]['sumOpenInterest'])
                            oi_change = ((curr_oi - prev_oi) / prev_oi) * 100 if prev_oi > 0 else 0
                            
                            prev_long = float(ls_res[0]['longAccount'])
                            curr_long = float(ls_res[1]['longAccount'])
                            
                            # Güçlü OI artışı ve Long rasyonun azalması (Fiyat yukarı giderken küçük yatırımcı short açıyor veya long kapatıyor)
                            if oi_change >= 2.0 and curr_long < prev_long:
                                
                                if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                                    send_telegram(f"💎 *ZIRHLI VADELİ SİNYAL* #{symbol}\n\n"
                                                  f"• *Güven Skoru:* ⭐⭐⭐⭐⭐\n"
                                                  f"• Vadeli Hacim Patlaması: {round(f_ratio,1)}x\n"
                                                  f"• OI (Açık Faiz) Artışı: +%{round(oi_change,2)}\n"
                                                  f"• Fonlama Oranı: %{round(funding_rate*100,3)}\n"
                                                  f"• Analiz: Fiyat Yatayken Dev Sıkışma Kırılımı\n"
                                                  f"• Dinamik: Longlar Azalıyor / Balina Gerçek Alımda! 🚀")
                                    sent_dict[symbol] = time.time()
                                    continue # Zırhlı attıysa Acaba'yı kontrol etmeye gerek yok, sonrakine geç.
                    except:
                        pass

                # ----------------=======================================----------------
                # MOD 2: ACABA SİNYALİ DEĞERLENDİRMESİ (HEM SPOT HEM VADELİ HİBRİT)
                # ----------------=======================================----------------
                # Şartlar: Vadeli hacim patlaması >3.0x olan coinin SPOT tahtasında gerçek dipte olması
                try:
                    time.sleep(0.1) # Spot sorgusu öncesi mikro es
                    # 1. SPOT 7 Günlük Mum Verileri (Görsel 5: Gerçek dip mi mid-range mi kontrolü)
                    s_res = requests.get(f"{SPOT_URL}/api/v3/klines", params={"symbol": symbol, "interval": "1d", "limit": 7}, headers=HEADERS, timeout=3)
                    if s_res.status_code == 200:
                        s_klines = s_res.json()
                        s_prices_7d = [float(k[2]) for k in s_klines] # En yüksek (High) fiyatlar listesi
                        s_7d_high = max(s_prices_7d)
                        
                        # Güncel spot fiyatı çekelim
                        s_ticker = requests.get(f"{SPOT_URL}/api/v3/ticker/price", params={"symbol": symbol}, headers=HEADERS, timeout=3).json()
                        current_spot_price = float(s_ticker.get('price', 0))
                        
                        # Formül (Görsel 5): current_price < 7d_high * 0.8 (Son 7 gün zirvesine göre %20+ ucuz, yani dipten kalkıyor)
                        if current_spot_price > 0 and current_spot_price < (s_7d_high * 0.8):
                            
                            # 2. 24 Saatlik Spot Hacim Kontrolü (Malın gerçekten toplanıp toplanmadığı)
                            s_ticker_24h = requests.get(f"{SPOT_URL}/api/v3/ticker/24hr", params={"symbol": symbol}, headers=HEADERS, timeout=3).json()
                            spot_quote_vol = float(s_ticker_24h.get('quoteVolume', 0)) # USDT bazlı hacim
                            
                            if spot_quote_vol > 1000000: # Spotta hacim sıfır değilse, gerçek alıcı varsa
                                if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                                    send_telegram(f"🤔 *ACABA SİNYALİ (HİBRİT)* #{symbol}\n\n"
                                                  f"• *Güven Skoru:* ⭐⭐⭐\n"
                                                  f"• Vadeli Hacim Patlaması: {round(f_ratio,1)}x\n"
                                                  f"• Spot Durumu: 7 Günlük Zirveden %20+ Aşağıda (Gerçek Dip)\n"
                                                  f"• 24s Spot Hacmi: ${round(spot_quote_vol/1000000, 2)}M\n"
                                                  f"• Not: Hareket vadeli tarafta başladı, spot dip yapısı onaylandı.")
                                    sent_dict[symbol] = time.time()
                except:
                    pass

            except Exception as e:
                # Herhangi bir paritede beklenmedik bir hata (bağlantı kopması vs.) olursa botun çökmesini engeller
                pass

        print(f"[{time.strftime('%H:%M:%S')}] Tüm pariteler güvenle tarandı. 60 saniye dinleniliyor...")
        time.sleep(60)

if __name__ == "__main__":
    main()

import asyncio
import aiohttp
import time
import math
from datetime import datetime
from statistics import mean, median
from collections import defaultdict

# =========================================================
# AYARLAR (GÜNCELLENDİ)
# =========================================================
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"   # Telegram Bot Token
CHAT_ID = "6637406938"                                         # Telegram Chat ID

COIN_LIST = [
    "BTCUSDT","ETHUSDT","SOLUSDT","DOGEUSDT","XRPUSDT","ADAUSDT",
    "AVAXUSDT","LINKUSDT","DOTUSDT","LTCUSDT","BCHUSDT","ATOMUSDT",
    "UNIUSDT","XLMUSDT","ALGOUSDT","VETUSDT","TRXUSDT","FILUSDT",
    "NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","STXUSDT","RNDRUSDT",
    "SEIUSDT","WIFUSDT","SUIUSDT","TIAUSDT"
]

FAPI_URL = "https://fapi.binance.com"
SPOT_URL = "https://api.binance.com"

# =========================================================
# CACHE (SÜRE DÜŞÜRÜLDÜ: 180s)
# =========================================================
cache = {"funding": {}}
CACHE_DURATION = 180

# Cooldown ve Memory
last_signals = {}         # Cooldown için
signal_memory = {}        # Telegram spam engellemek için

# =========================================================
# TELEGRAM
# =========================================================
async def send_telegram(session, msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        await session.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Telegram hatası: {e}")

# =========================================================
# TEMEL API
# =========================================================
async def fetch(session, url_type, endpoint, params=None):
    """DÜZELTME 2: Farklı URL türleri (fapi/api) desteği eklendi"""
    base = FAPI_URL if url_type == "fapi" else SPOT_URL
    try:
        async with session.get(f"{base}{endpoint}", params=params, timeout=10) as resp:
            if resp.status != 200: return None
            return await resp.json()
    except Exception as e:
        return None

async def get_cached(session, cache_name, symbol, endpoint, params):
    now = time.time()
    if symbol in cache[cache_name]:
        item = cache[cache_name][symbol]
        if now - item["time"] < CACHE_DURATION: return item["data"]
    data = await fetch(session, "fapi", endpoint, params)
    if data: cache[cache_name][symbol] = {"time": now, "data": data}
    return data

def calculate_ema(prices, period):
    if len(prices) < period: return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]: ema = (p - ema) * multiplier + ema
    return ema

# =========================================================
# GELİŞMİŞ METRİKLER (TÜM DÜZELTMELER ENTEGRE EDİLDİ)
# =========================================================

# BTC FILTER (DÜZELTME 2 & 18)
async def btc_market_safe(session):
    # BTC 15m kontrol
    btc_klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 5})
    if not btc_klines: return False
    open_price = float(btc_klines[-1][1]); close_price = float(btc_klines[-1][4])
    change_pct = ((close_price - open_price) / open_price) * 100
    highs = [float(k[2]) for k in btc_klines]; lows = [float(k[3]) for k in btc_klines]
    volatility = ((max(highs) - min(lows)) / min(lows)) * 100
    if change_pct < -2.0: return False
    if volatility > 4: return False
    
    # DÜZELTME 2 & 18: ETHBTC Spot Endpoint (Correlation Filter)
    ethbtc_klines = await fetch(session, "spot", "/api/v3/klines", {"symbol": "ETHBTC", "interval": "15m", "limit": 2})
    if ethbtc_klines:
        ethbtc_open = float(ethbtc_klines[-1][1]); ethbtc_close = float(ethbtc_klines[-1][4])
        ethbtc_change = ((ethbtc_close - ethbtc_open) / ethbtc_open) * 100
        if ethbtc_change < -0.8:
            return False
    return True

# ORDERBOOK (DÜZELTME 1 & 5)
async def get_orderbook_bias(session, symbol):
    depth = await fetch(session, "fapi", "/fapi/v1/depth", {"symbol": symbol, "limit": 50})
    if not depth: return 0
    try:
        # DÜZELTME 1: Fiyat * Miktar (Price * Quantity)
        bids = sum(float(x[0]) * float(x[1]) for x in depth["bids"])
        asks = sum(float(x[0]) * float(x[1]) for x in depth["asks"])
        return bids / asks if asks > 0 else 0
    except: return 0

# CVD / DELTA (DÜZELTME 4)
async def get_delta_approximation(session, symbol):
    klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 1})
    if not klines: return 0
    volume = float(klines[-1][5])
    taker_buy = float(klines[-1][9])
    delta = taker_buy - (volume - taker_buy)
    if volume == 0: return 0
    return delta / volume

# ATR (DÜZELTME 10)
async def get_atr(session, symbol, period=14):
    klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": period + 1})
    if not klines: return 0.001
    tr_values = []
    for i in range(1, len(klines)):
        high = float(klines[i][2]); low = float(klines[i][3]); close_prev = float(klines[i-1][4])
        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        tr_values.append(tr)
    return mean(tr_values) if tr_values else 0.001

# LİKİTASYON RİSKİ
def estimate_liquidation_risk(change_pct, oi_change):
    if abs(change_pct) > 3 and oi_change > 3: return "YÜKSEK"
    if abs(change_pct) > 2 and oi_change > 1: return "ORTA"
    return "DÜŞÜK"

# TOP TRADER
async def get_top_trader_bias(session, symbol):
    data = await fetch(session, "fapi", "/futures/data/topLongShortPositionRatio", {"symbol": symbol, "period": "5m", "limit": 2})
    if not data or not isinstance(data, list) or len(data) < 1: return 0
    try: return float(data[-1]["longShortRatio"])
    except: return 0

# SPOT HACİM (DÜZELTME 8)
async def get_spot_volume(session, symbol):
    ticker = await fetch(session, "spot", "/api/v3/ticker/24hr", {"symbol": symbol})
    if ticker: return float(ticker.get('quoteVolume', 0))
    return 0

# FAKE BREAKOUT / WICK FILTER (DÜZELTME 17)
async def get_wick_ratio(session, symbol):
    klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 1})
    if not klines: return 0
    o = float(klines[-1][1]); c = float(klines[-1][4]); h = float(klines[-1][2]); l = float(klines[-1][3])
    body = abs(c - o)
    total_range = h - l
    if total_range == 0: return 0
    return body / total_range

# =========================================================
# SCAN COIN (TÜM DÜZELTMELER ENTEGRE EDİLDİ)
# =========================================================
async def scan_coin(session, symbol, market_median, min_score_atr, atr_val):
    try:
        # Cooldown / Memory Cleanup (DÜZELTME 12)
        if symbol in last_signals and time.time() - last_signals[symbol] < 600: return None
        
        # DÜZELTME 3: KAPANMIŞ MUM KULLAN ([-2])
        kl_5m = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 8})
        kl_1h = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 30})
        kl_15m = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "15m", "limit": 6})
        if not kl_5m or len(kl_5m) < 2: return None
        
        # DÜZELTME 3: KAPANMIŞ MUM KULLAN ([-2])
        last = kl_5m[-2]
        open_price = float(last[1]); close_price = float(last[4])
        volume = float(last[5]); taker_buy = float(last[9])
        change_pct = ((close_price - open_price) / open_price) * 100
        taker_ratio = taker_buy / volume if volume > 0 else 0

        # Volume Speed
        prev_vols = [float(k[5]) for k in kl_5m[-6:-1]]
        avg_vol = mean(prev_vols)
        speed_ratio = volume / avg_vol if avg_vol > 0 else 0
        
        # DÜZELTME 7: RATE LIMIT KORUMASI (Ağır endpointler için ön kontrol)
        # Ağır endpointler (Depth, OI, TopTrader) sadece yeterli hacim ve fiyat hareketi varsa çağrılır
        heavy_check = (speed_ratio > 1.5 and abs(change_pct) > 0.7)

        # DÜZELTME 6 & 11: MULTI-TIMEFRAME (1H, 4H)
        closes_1h = [float(k[4]) for k in kl_1h] if kl_1h else []
        ema20_1h = calculate_ema(closes_1h, 20)
        
        kl_4h = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": 30})
        closes_4h = [float(k[4]) for k in kl_4h] if kl_4h else []
        ema50_4h = calculate_ema(closes_4h, 50)

        # Structure (15m)
        bullish_structure = False
        bearish_structure = False
        if kl_15m and len(kl_15m) >= 4:
            highs = [float(k[2]) for k in kl_15m[-4:]]
            lows = [float(k[3]) for k in kl_15m[-4:]]
            if len(highs) >= 2 and len(lows) >= 2:
                if highs[-1] > highs[-2] and lows[-1] > lows[-2]: bullish_structure = True
                if highs[-1] < highs[-2] and lows[-1] < lows[-2]: bearish_structure = True

        # OI (DÜZELTME 1: Cache KALDIRILDI)
        oi_change = 0
        if heavy_check:
            oi_data = await fetch(session, "fapi", "/fapi/v1/openInterestHist", {"symbol": symbol, "period": "5m", "limit": 2})
            if isinstance(oi_data, list) and len(oi_data) >= 2:
                prev_oi = float(oi_data[-2]["sumOpenInterestValue"]); curr_oi = float(oi_data[-1]["sumOpenInterestValue"])
                if prev_oi > 0: oi_change = ((curr_oi - prev_oi) / prev_oi) * 100
        
        # FUNDING (Cache kullanılıyor)
        funding_rate = 0
        funding = await get_cached(session, "funding", symbol, "/fapi/v1/premiumIndex", {"symbol": symbol})
        if isinstance(funding, dict): funding_rate = float(funding.get("lastFundingRate", 0))

        # ORDERBOOK (DÜZELTME 5: Skor azaltıldı)
        ob_ratio = 0
        if heavy_check: ob_ratio = await get_orderbook_bias(session, symbol)

        # TOP TRADER
        top_ratio = 0
        if heavy_check: top_ratio = await get_top_trader_bias(session, symbol)

        # RELATIVE VOLUME (DÜZELTME 5: Trimmed Median)
        rel_vol = volume / market_median if market_median > 0 else 0

        # DELTA APPROX (DÜZELTME 4)
        delta_ratio = await get_delta_approximation(session, symbol)

        # WICK RATIO (DÜZELTME 17)
        wick_ratio = await get_wick_ratio(session, symbol)

        # SPOT HACİM (DÜZELTME 8)
        spot_vol = 0
        if heavy_check: spot_vol = await get_spot_volume(session, symbol)

        # LIQUIDATION RISK
        liquidation_risk = estimate_liquidation_risk(change_pct, oi_change)

        # ================================
        # SKOR SİSTEMİ (DÜZELTME 14: SHORT SCAN EKLENDİ)
        # ================================
        long_score = 0
        short_score = 0

        # Momentum Hızı (Her iki yön için de geçerli)
        if speed_ratio > 1.8: 
            long_score += 2
            short_score += 2
        if speed_ratio > 2.5: 
            long_score += 1
            short_score += 1

        # Fiyat Değişimi & ATR Normalizasyon (DÜZELTME 10)
        normalized_change = change_pct / (atr_val / close_price) if atr_val > 0 else change_pct
        if 0.8 < normalized_change < 5: long_score += 2
        if -5 < normalized_change < -0.8: short_score += 2

        # Taker Buy
        if taker_ratio > 0.55: long_score += 2
        if taker_ratio < 0.45: short_score += 2

        # CVD / Delta (DÜZELTME 4)
        if delta_ratio > 0.15: long_score += 2
        if delta_ratio < -0.15: short_score += 2

        # OI Artışı
        if oi_change > 1: 
            long_score += 2
            short_score += 2

        # Negative Funding (Short squeeze long için iyidir)
        if funding_rate < 0: long_score += 1

        # Trend (EMA & Structure)
        if ema20_1h and close_price > ema20_1h: long_score += 1
        if ema20_1h and close_price < ema20_1h: short_score += 1
        if ema50_4h and close_price > ema50_4h: long_score += 1
        if ema50_4h and close_price < ema50_4h: short_score += 1
        if bullish_structure: long_score += 2
        if bearish_structure: short_score += 2

        # Relative Volume
        if rel_vol > 1.5: 
            long_score += 2
            short_score += 2

        # Orderbook (DÜZELTME 5)
        if ob_ratio > 1.3: long_score += 1
        if ob_ratio < 0.7: short_score += 1

        # Top Trader
        if top_ratio > 1.1: long_score += 1
        if top_ratio < 0.9: short_score += 1

        # Wick Ratio (Fake breakouts, DÜZELTME 17)
        if wick_ratio > 0.5: 
            long_score -= 1
            short_score -= 1

        # Spot Volume (DÜZELTME 8)
        if spot_vol > 1000000: 
            long_score += 1
            short_score += 1

        # DÜZELTME 9: ADAPTIVE SCORE EŞİĞİ
        final_long_score = long_score
        final_short_score = short_score
        
        if final_long_score >= min_score_atr:
            last_signals[symbol] = time.time()
            return {
                "symbol": symbol,
                "direction": "LONG",
                "score": final_long_score,
                "price": round(close_price, 4),
                "change": round(change_pct, 2),
                "oi": round(oi_change, 2),
                "funding": round(funding_rate, 6),
                "delta_approx": round(delta_ratio, 3),
                "rel_vol": round(rel_vol, 2),
                "taker_ratio": round(taker_ratio, 2),
                "trend": "Bullish" if close_price > ema20_1h else "Bearish",
                "risk": liquidation_risk
            }
        elif final_short_score >= min_score_atr:
            last_signals[symbol] = time.time()
            return {
                "symbol": symbol,
                "direction": "SHORT",
                "score": final_short_score,
                "price": round(close_price, 4),
                "change": round(change_pct, 2),
                "oi": round(oi_change, 2),
                "funding": round(funding_rate, 6),
                "delta_approx": round(delta_ratio, 3),
                "rel_vol": round(rel_vol, 2),
                "taker_ratio": round(taker_ratio, 2),
                "trend": "Bullish" if close_price > ema20_1h else "Bearish",
                "risk": liquidation_risk
            }
    except Exception as e:
        # DÜZELTME 1 (ESKİDEN): Silent fail riski - Hata loglama
        print(f"Hata ({symbol}): {e}")
        pass
    return None

# =========================================================
# MAIN (DÜZELTME 12 & 13 & 15 & 16 & 18)
# =========================================================
async def main():
    print("🚀 ULTRA SCANNER (FINAL - PROFESYONEL) BAŞLATILDI")
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=100)) as session:
        while True:
            try:
                print(f"\n--- {datetime.now().strftime('%H:%M:%S')} ---")
                
                # 1. BTC & ETHBTC Filter
                if not await btc_market_safe(session):
                    print("⚠️ Market Unsafe (BTC Dump veya ETHBTC Zayıf). 30s bekleniyor...")
                    await asyncio.sleep(30); continue

                # 2. Market Median (Trimmed Median - DÜZELTME 5)
                tasks = [fetch(session, "fapi", "/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 5}) for sym in COIN_LIST]
                responses = await asyncio.gather(*tasks)
                vols = [float(r[-1][5]) for r in responses if r]
                if vols:
                    sorted_vols = sorted(vols)
                    trimmed = sorted_vols[2:-2] if len(sorted_vols) > 4 else sorted_vols
                    market_median = median(trimmed) if trimmed else 1
                else:
                    market_median = 1

                # 3. ADAPTIVE SCORE (DÜZELTME 9)
                # BTC volatilitesine göre eşik değerini değiştir
                btc_vol = 0
                btc_klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 10})
                if btc_klines:
                    for k in btc_klines:
                        h = float(k[2]); l = float(k[3])
                        btc_vol += (h - l) / l
                    btc_vol = (btc_vol / len(btc_klines)) * 100
                
                if btc_vol < 1.0:
                    min_score_atr = 5  # Yatay Piyasa
                elif btc_vol > 2.5:
                    min_score_atr = 8  # Yüksek Volatilite
                else:
                    min_score_atr = 6  # Normal Piyasa
                
                # 4. ATR Normalization (DÜZELTME 10)
                atr_tasks = [get_atr(session, sym) for sym in COIN_LIST]
                atr_values = await asyncio.gather(*atr_tasks)
                atr_dict = {sym: val for sym, val in zip(COIN_LIST, atr_values)}

                # 5. Scan Coins
                scan_tasks = [scan_coin(session, sym, market_median, min_score_atr, atr_dict[sym]) for sym in COIN_LIST]
                results = [r for r in await asyncio.gather(*scan_tasks) if r]
                results.sort(key=lambda x: x["score"], reverse=True)

                # 6. Telegram Gönderimi (DÜZELTME 13: Mesaj Kalitesi)
                # DÜZELTME 12: Signal Memory Cleanup
                now = time.time()
                to_delete = [k for k, v in signal_memory.items() if now - v['time'] > 86400]
                for k in to_delete: del signal_memory[k]

                new_signals = []
                for coin in results[:3]:  # İlk 3 koini kontrol et
                    sym = coin['symbol']
                    new_score = coin['score']
                    old_info = signal_memory.get(sym, {'score': 0, 'time': 0})
                    old_score = old_info['score']
                    
                    # Yeni coin VEYA skor önemli ölçüde arttıysa gönder
                    if sym not in signal_memory or new_score > old_score + 2:
                        new_signals.append(coin)
                        signal_memory[sym] = {'score': new_score, 'time': now}

                if new_signals:
                    msg = "🔥 *YENİ VEYA GÜÇLENEN SİNYALLER:*\n\n"
                    for coin in new_signals:
                        emoji = "🟢" if coin['direction'] == "LONG" else "🔴"
                        msg += (
                            f"{emoji} *{coin['symbol']} ({coin['direction']})*\n"
                            f"   ⭐ Puan: {coin['score']}\n"
                            f"   💰 Fiyat: {coin['price']}\n"
                            f"   📊 Değişim: %{coin['change']}\n"
                            f"   📈 OI: %{coin['oi']}\n"
                            f"   💸 Funding: {coin['funding']}\n"
                            f"   📉 Delta (Approx): {coin['delta_approx']}\n"
                            f"   📊 Rel Vol: {coin['rel_vol']}\n"
                            f"   👥 Taker Ratio: {coin['taker_ratio']}\n"
                            f"   🔄 Trend: {coin['trend']}\n"
                            f"   ⚠️ Risk: {coin['risk']}\n\n"
                        )
                    await send_telegram(session, msg)
                    print(f"✅ {len(new_signals)} yeni/güçlenen sinyal Telegram'a gönderildi.")
                
                print(f"🔍 Toplam {len(results)} coin eşiği geçti (Min Score: {min_score_atr})")
                await asyncio.sleep(12)

            except Exception as e:
                print(f"Kritik hata: {e}")
                await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())

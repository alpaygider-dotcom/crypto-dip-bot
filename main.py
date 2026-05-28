import asyncio
import aiohttp
import os
import time
import logging
import traceback
from statistics import mean, stdev
from datetime import datetime, timezone, timedelta

# ==================================================
# LOG AYARLARI
# ==================================================
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY")

BASE_URL = "https://fapi.binance.com"

SCAN_INTERVAL = 40
COOLDOWN = 600
MAX_CONCURRENT_REQUESTS = 20

last_signal = {}

# ==================================================
# TELEGRAM QUEUE
# ==================================================
telegram_queue = asyncio.Queue()

async def telegram_worker(session):
    while True:
        text = await telegram_queue.get()
        try:
            if not BOT_TOKEN or not CHAT_ID:
                print(text)
            else:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                payload = {"chat_id": CHAT_ID, "text": text}
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(1)
                        await telegram_queue.put(text)
        except Exception as e:
            logging.error(f"TELEGRAM ERROR: {traceback.format_exc()}")
            print("TELEGRAM ERROR:", e)
        finally:
            telegram_queue.task_done()
        await asyncio.sleep(0.35)

async def send_telegram(text):
    await telegram_queue.put(text)

# ==================================================
# FETCH
# ==================================================
async def fetch_json(session, endpoint, params=None):
    try:
        url = BASE_URL + endpoint
        async with session.get(url, params=params, timeout=10) as response:
            if response.status != 200:
                return None
            return await response.json()
    except:
        return None

# ==================================================
# EMA
# ==================================================
def ema(values, period):
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema_value = mean(values[:period])
    for price in values[period:]:
        ema_value = ((price - ema_value) * multiplier) + ema_value
    return ema_value

# ==================================================
# ATR
# ==================================================
def calculate_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return None
    tr_list = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    if len(tr_list) < period:
        return None
    atr = mean(tr_list[-period:])
    return atr

# ==================================================
# BTC BIAS
# ==================================================
async def get_btc_bias(session):
    klines = await fetch_json(session, "/fapi/v1/klines",
                              {"symbol": "BTCUSDT", "interval": "15m", "limit": 50})
    if not klines:
        return "NEUTRAL"
    closes = [float(k[4]) for k in klines]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    last_price = closes[-1]
    if ema20 and ema50:
        if last_price > ema20 and ema20 > ema50:
            return "BULLISH"
        if last_price < ema20 and ema20 < ema50:
            return "BEARISH"
    return "NEUTRAL"

# ==================================================
# REGIME
# ==================================================
def detect_regime(closes, volumes):
    move = (closes[-1] - closes[0]) / closes[0]
    vol_mean = mean(volumes)
    vol_std = stdev(volumes) if len(volumes) > 1 else 0
    vol_z = (volumes[-1] - vol_mean) / vol_std if vol_std > 0 else 0
    if abs(move) < 0.004:
        return "RANGE"
    if abs(move) > 0.012 and vol_z > 1:
        return "TREND"
    return "MIXED"

# ==================================================
# SWEEP
# ==================================================
def detect_sweep(highs, lows, closes):
    sweep_up = False
    sweep_down = False
    if highs[-1] > max(highs[-10:-1]) and closes[-1] < highs[-1]:
        sweep_up = True
    if lows[-1] < min(lows[-10:-1]) and closes[-1] > lows[-1]:
        sweep_down = True
    return sweep_up, sweep_down

# ==================================================
# SIDEWAYS BREAKOUT (ATR dinamik + taban)
# ==================================================
def sideways_breakout(closes, atr_val=None):
    recent = closes[-15:]
    highest = max(recent)
    lowest = min(recent)
    range_pct = ((highest - lowest) / lowest) * 100
    if atr_val and highest > 0:
        factor = max((atr_val / highest) * 2, 0.001)
    else:
        factor = 0.002
    breakout_up = closes[-1] > highest * (1 - factor)
    breakout_down = closes[-1] < lowest * (1 + factor)
    compressed = range_pct < 2.5
    return compressed, breakout_up, breakout_down

# ==================================================
# ORDERFLOW + CVD
# ==================================================
def orderflow_strength(volume, taker_buy, historical_taker_buys=None, historical_volumes=None):
    if volume <= 0:
        return 0, 0
    taker_ratio = taker_buy / volume
    delta = taker_buy - (volume - taker_buy)
    delta_ratio = delta / volume
    score = 0
    if taker_ratio > 0.62: score += 2
    if taker_ratio < 0.38: score -= 2
    if delta_ratio > 0.18: score += 2
    if delta_ratio < -0.18: score -= 2

    cvd_trend = 0
    if historical_taker_buys and historical_volumes and len(historical_taker_buys) >= 5:
        cvd = 0
        cvd_values = []
        for tb, vol in zip(historical_taker_buys[-10:], historical_volumes[-10:]):
            delta_candle = tb - (vol - tb) if vol > 0 else 0
            cvd += delta_candle
            cvd_values.append(cvd)
        if len(cvd_values) >= 5:
            x = list(range(5))
            y = cvd_values[-5:]
            n = 5
            sum_xy = sum(x[i]*y[i] for i in range(5))
            sum_x = sum(x)
            sum_y = sum(y)
            sum_x2 = sum(xi*xi for xi in x)
            slope = (n*sum_xy - sum_x*sum_y) / (n*sum_x2 - sum_x**2) if (n*sum_x2 - sum_x**2) != 0 else 0
            cvd_trend = 1 if slope > 0 else -1 if slope < 0 else 0
            if cvd_trend > 0: score += 2
            elif cvd_trend < 0: score -= 2
    return score, cvd_trend

# ==================================================
# LIKIDASYON (COINGLASS)
# ==================================================
async def get_liquidation_data(session, symbol):
    if not COINGLASS_API_KEY:
        return None, None
    try:
        url = "https://open-api.coinglass.com/public/v2/liquidation"
        params = {"symbol": symbol.replace("USDT", ""), "time_type": "1"}
        headers = {"coinglassSecret": COINGLASS_API_KEY}
        async with session.get(url, params=params, headers=headers, timeout=10) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.json()
            if data.get("code") == "0" and data.get("data"):
                items = data["data"]["liquidationList"]
                long_liq = sum(float(item.get("longVolUsd",0)) for item in items)
                short_liq = sum(float(item.get("shortVolUsd",0)) for item in items)
                return long_liq, short_liq
    except:
        pass
    return None, None

# ==================================================
# ADAPTIF VOLATILITE
# ==================================================
def calc_volatility_factor(closes):
    if len(closes) < 20:
        return 1.0
    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    vol = stdev(returns) if len(returns) > 1 else 0
    base_vol = 0.005
    factor = vol / base_vol if base_vol > 0 else 1
    return min(max(factor, 0.7), 1.4)

# ==================================================
# HEAVY DATA
# ==================================================
async def get_heavy_data(session, symbol):
    funding = 0
    oi_change = 0
    long_short = 1
    funding_data = await fetch_json(session, "/fapi/v1/premiumIndex", {"symbol": symbol})
    if funding_data:
        funding = float(funding_data.get("lastFundingRate", 0))
    oi_data = await fetch_json(session, "/futures/data/openInterestHist",
                               {"symbol": symbol, "period": "5m", "limit": 2})
    if oi_data and len(oi_data) >= 2:
        prev_oi = float(oi_data[-2]["sumOpenInterest"])
        curr_oi = float(oi_data[-1]["sumOpenInterest"])
        if prev_oi > 0:
            oi_change = ((curr_oi - prev_oi) / prev_oi) * 100
    ratio_data = await fetch_json(session, "/futures/data/topLongShortPositionRatio",
                                  {"symbol": symbol, "period": "5m", "limit": 1})
    if ratio_data:
        try:
            long_short = float(ratio_data[-1]["longShortRatio"])
        except:
            pass
    return funding, oi_change, long_short

# ==================================================
# SINIFLANDIRMA (ADAPTIF)
# ==================================================
def classify_signal(score, vol_factor=1.0):
    strong = max(13 * vol_factor, 10)
    medium = max(8 * vol_factor, 6)
    weak = max(5 * vol_factor, 4)
    if score >= strong:
        return "🔥 GÜÇLÜ AL"
    if score >= medium:
        return "🟡 ORTA AL"
    if score >= weak:
        return "🟢 AZ AL"
    return None

# ==================================================
# SEMBOL LISTESI
# ==================================================
async def get_all_symbols(session):
    futures_symbols = []
    try:
        fut_info = await fetch_json(session, "/fapi/v1/exchangeInfo")
        if fut_info:
            for s in fut_info.get("symbols", []):
                if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
                    futures_symbols.append(s["symbol"])
    except:
        pass
    return futures_symbols

# ==================================================
# COIN TARAMA (CANLI) – DOKUNMADIM
# ==================================================
async def scan_coin(session, symbol, btc_bias, semaphore):
    async with semaphore:
        try:
            klines_5m = await fetch_json(session, "/fapi/v1/klines",
                                         {"symbol": symbol, "interval": "5m", "limit": 80})
            if not klines_5m:
                return

            klines_1h = await fetch_json(session, "/fapi/v1/klines",
                                         {"symbol": symbol, "interval": "1h", "limit": 80})

            closes = []; highs = []; lows = []; volumes = []; taker_buys = []
            for k in klines_5m:
                closes.append(float(k[4]))
                highs.append(float(k[2]))
                lows.append(float(k[3]))
                volumes.append(float(k[5]))
                taker_buys.append(float(k[9]))

            last = klines_5m[-2]
            open_price = float(last[1])
            close_price = float(last[4])
            volume = float(last[5])
            taker_buy = float(last[9])
            change = ((close_price - open_price) / open_price) * 100

            vol_mean = mean(volumes)
            vol_std = stdev(volumes) if len(volumes) > 1 else 0
            vol_z = ((volume - vol_mean) / vol_std) if vol_std > 0 else 0

            vol_factor = calc_volatility_factor(closes)

            min_change = 0.25 * vol_factor
            min_vol_z = 0.8 * vol_factor
            if abs(change) < min_change and vol_z < min_vol_z:
                return

            regime = detect_regime(closes, volumes)
            sweep_up, sweep_down = detect_sweep(highs, lows, closes)

            atr_val = calculate_atr(highs, lows, closes)
            if atr_val is None:
                atr_val = close_price * 0.005

            compressed, breakout_up, breakout_down = sideways_breakout(closes, atr_val)

            funding, oi_change, long_short = await get_heavy_data(session, symbol)
            long_liq, short_liq = await get_liquidation_data(session, symbol)

            order_score, cvd_trend = orderflow_strength(volume, taker_buy, taker_buys, volumes)

            trend_bonus_long = 0
            trend_bonus_short = 0
            if klines_1h:
                closes_1h = [float(k[4]) for k in klines_1h]
                ema20_1h = ema(closes_1h, 20)
                ema50_1h = ema(closes_1h, 50)
                last_1h = closes_1h[-1]
                if ema20_1h and ema50_1h:
                    if last_1h > ema20_1h and ema20_1h > ema50_1h:
                        trend_bonus_long += 3
                    if last_1h < ema20_1h and ema20_1h < ema50_1h:
                        trend_bonus_short += 3

            long_score = 0
            short_score = 0

            if change > 1: long_score += 2
            if change < -1: short_score += 2

            if vol_z > 2 * vol_factor:
                long_score += 2
                short_score += 2

            if regime == "TREND":
                long_score += 1
                short_score += 1

            if sweep_down: long_score += 3
            if sweep_up: short_score += 3

            if oi_change > 4:
                long_score += 3
                short_score += 3

            if funding < -0.01 and change > 0: long_score += 3
            if funding > 0.01 and change < 0: short_score += 3

            if long_short > 1.5: short_score += 1
            if long_short < 0.7: long_score += 1

            if compressed and breakout_up: long_score += 3
            if compressed and breakout_down: short_score += 3

            if order_score > 0: long_score += order_score
            if order_score < 0: short_score += abs(order_score)

            long_score += trend_bonus_long
            short_score += trend_bonus_short

            if btc_bias == "BULLISH":
                long_score += 2
                short_score -= 1
            if btc_bias == "BEARISH":
                short_score += 2
                long_score -= 1

            if long_liq and short_liq:
                if long_liq > short_liq * 1.3: long_score += 2
                if short_liq > long_liq * 1.3: short_score += 2

            if cvd_trend > 0: long_score += 2
            elif cvd_trend < 0: short_score += 2

            best_score = max(long_score, short_score)
            signal_type = classify_signal(best_score, vol_factor)
            if not signal_type:
                return

            direction = "LONG" if long_score > short_score else "SHORT"

            if btc_bias == "BULLISH" and direction == "SHORT" and best_score < 11:
                return
            if btc_bias == "BEARISH" and direction == "LONG" and best_score < 11:
                return

            now = time.time()
            if symbol in last_signal:
                if now - last_signal[symbol] < COOLDOWN:
                    return
            last_signal[symbol] = now

            confidence = min(95, int(best_score * 6))
            icon = "🟢" if direction == "LONG" else "🔴"
            expected_move = "%1-3"
            if best_score >= 8: expected_move = "%3-6"
            if best_score >= 13: expected_move = "%5-10"

            sl_atr_mult = 1.5
            tp_atr_mult = 2.0
            if direction == "LONG":
                stop_loss_price = close_price - atr_val * sl_atr_mult
                take_profit_price = close_price + atr_val * tp_atr_mult
            else:
                stop_loss_price = close_price + atr_val * sl_atr_mult
                take_profit_price = close_price - atr_val * tp_atr_mult

            capital = 1000.0
            risk_percent = 0.01
            risk_amount = capital * risk_percent
            stop_loss_pct = abs(close_price - stop_loss_price) / close_price
            if stop_loss_pct > 0:
                position_size = risk_amount / (stop_loss_pct * close_price)
            else:
                position_size = 0.0

            reasons = []
            if vol_z > 2: reasons.append("Hacim Patlaması")
            if oi_change > 4: reasons.append("OI Yükselişi")
            if compressed: reasons.append("Yatay Kırılım")
            if sweep_down and direction == "LONG": reasons.append("Dip Sweep")
            if sweep_up and direction == "SHORT": reasons.append("Tepe Sweep")
            if funding < -0.01 and direction == "LONG": reasons.append("Short Squeeze")
            if funding > 0.01 and direction == "SHORT": reasons.append("Long Squeeze")
            if trend_bonus_long > 0 and direction == "LONG": reasons.append("1H Trend Güçlü")
            if trend_bonus_short > 0 and direction == "SHORT": reasons.append("1H Trend Güçlü")
            if btc_bias == "BULLISH": reasons.append("BTC Güçlü")
            if btc_bias == "BEARISH": reasons.append("BTC Zayıf")
            if long_liq and short_liq and ((long_liq > short_liq*1.3) or (short_liq > long_liq*1.3)):
                reasons.append("Likidasyon Dengesizliği")
            if cvd_trend > 0 and direction == "LONG": reasons.append("CVD Yükseliş")
            if cvd_trend < 0 and direction == "SHORT": reasons.append("CVD Düşüş")
            if len(reasons) == 0: reasons.append("Momentum")

            reason_text = "\n".join("• " + r for r in reasons)

            msg = (
                f"{signal_type}\n\n"
                f"{icon} {symbol}\n\n"
                f"Yön: {direction}\n"
                f"Güven: %{confidence}\n\n"
                f"📊 Risk Yönetimi (örnek 1000 USDT):\n"
                f"Stop‑Loss: {stop_loss_price:.4f} USDT\n"
                f"Take‑Profit: {take_profit_price:.4f} USDT\n"
                f"Pozisyon Büyüklüğü: {position_size:.2f} adet\n\n"
                f"Tahmini Hareket: {expected_move}\n\n"
                f"Sebep:\n{reason_text}"
            )
            print(msg)
            await send_telegram(msg)

        except Exception as e:
            logging.error(f"SCAN ERROR {symbol}: {traceback.format_exc()}")
            print("SCAN ERROR:", symbol, e)

# ==================================================
# BACKTEST (AŞIRI GEVŞEK – SADECE SORUN GİDERME)
# ==================================================
async def run_backtest(session):
    try:
        await send_telegram("📊 DEBUG BACKTEST BAŞLADI (filtreler çok gevşek)")
        total_signals = 0
        wins = 0
        total_pnl_net = 0.0

        commission = 0.0004
        slippage = 0.0002

        all_syms = await get_all_symbols(session)
        test_symbols = all_syms[:200]
        print(f"Backtest için {len(test_symbols)} sembol bulundu.")

        for symbol in test_symbols:
            klines = await fetch_json(session, "/fapi/v1/klines",
                                      {"symbol": symbol, "interval": "5m", "limit": 1000})
            if not klines or len(klines) < 50:
                continue

            for i in range(200, len(klines)-1):
                window = klines[i-49:i+1] if i >= 49 else klines[:i+1]
                if len(window) < 10:
                    continue
                closes = [float(k[4]) for k in window]
                highs = [float(k[2]) for k in window]
                lows = [float(k[3]) for k in window]
                volumes = [float(k[5]) for k in window]
                taker_buys = [float(k[9]) for k in window]
                last = window[-1]
                open_price = float(last[1])
                close_price = float(last[4])
                volume = float(last[5])
                taker_buy = float(last[9])
                change = ((close_price - open_price) / open_price) * 100

                # EŞİKLERİ TAMAMEN KALDIRDIK (DEBUG)
                # Sadece NaN kontrolü
                if volume <= 0:
                    continue

                regime = detect_regime(closes, volumes)
                sweep_up, sweep_down = detect_sweep(highs, lows, closes)

                atr_val = calculate_atr(highs, lows, closes)
                if atr_val is None:
                    atr_val = close_price * 0.005
                compressed, breakout_up, breakout_down = sideways_breakout(closes, atr_val)

                order_score, cvd_trend = orderflow_strength(volume, taker_buy, taker_buys, volumes)

                long_score = 0
                short_score = 0
                # Sadece basit momentum puanı
                if change > 0.5: long_score += 1
                if change < -0.5: short_score += 1

                if regime == "TREND":
                    long_score += 1
                    short_score += 1

                if sweep_down: long_score += 2
                if sweep_up: short_score += 2

                if compressed and breakout_up: long_score += 2
                if compressed and breakout_down: short_score += 2

                if order_score > 0: long_score += order_score
                if order_score < 0: short_score += abs(order_score)

                if cvd_trend > 0: long_score += 1
                elif cvd_trend < 0: short_score += 1

                best_score = max(long_score, short_score)
                # Eşik çok düşük (vol_factor 0.3)
                signal_type = classify_signal(best_score, 0.3)
                if not signal_type:
                    continue

                direction = "LONG" if long_score > short_score else "SHORT"
                entry = close_price

                if direction == "LONG":
                    tp = entry + atr_val * 2.0
                    sl = entry - atr_val * 1.5
                else:
                    tp = entry - atr_val * 2.0
                    sl = entry + atr_val * 1.5

                if direction == "LONG":
                    entry_real = entry * (1 + slippage + commission)
                else:
                    entry_real = entry * (1 - slippage - commission)

                future_prices = [float(k[4]) for k in klines[i+1:i+31]]
                exit_price = None
                for price in future_prices:
                    if direction == "LONG":
                        if price >= tp:
                            exit_price = tp * (1 - commission - slippage)
                            wins += 1
                            break
                        elif price <= sl:
                            exit_price = sl * (1 - commission - slippage)
                            break
                    else:
                        if price <= tp:
                            exit_price = tp * (1 - commission - slippage)
                            wins += 1
                            break
                        elif price >= sl:
                            exit_price = sl * (1 - commission - slippage)
                            break
                if exit_price is None:
                    exit_price = entry_real

                pnl = (exit_price - entry_real) / entry_real * 100
                total_pnl_net += pnl
                total_signals += 1

        win_rate = (wins / total_signals * 100) if total_signals > 0 else 0
        avg_pnl = total_pnl_net / total_signals if total_signals > 0 else 0
        profit_factor = (total_pnl_net + wins) / (abs(total_pnl_net) + (total_signals - wins)) if total_signals > 0 else 0

        msg = (f"📊 DEBUG BACKTEST (gevşek filtreler)\n"
               f"Toplam Sinyal: {total_signals}\n"
               f"Kazanan: {wins} | Kaybeden: {total_signals - wins}\n"
               f"Win Rate: %{win_rate:.1f}\n"
               f"Ort. Net Getiri: %{avg_pnl:.2f}\n"
               f"Kümülatif Net PnL: %{total_pnl_net:.2f}\n"
               f"Kâr Faktörü: {profit_factor:.2f}")
        await send_telegram(msg)
    except Exception as e:
        logging.error(f"Backtest Error: {traceback.format_exc()}")
        print("Backtest Error:", e)

# ==================================================
# ANA DÖNGÜ
# ==================================================
async def main():
    print("🚀 PROFESIONAL BOT (DEBUG BACKTEST)")
    async with aiohttp.ClientSession() as session:
        asyncio.create_task(telegram_worker(session))
        await send_telegram("✅ BOT ONLINE (DEBUG Backtest açık)")
        all_symbols = await get_all_symbols(session)
        print(f"Toplam futures coin: {len(all_symbols)}")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        asyncio.create_task(run_backtest(session))
        last_backtest = time.time()

        while True:
            btc_bias = await get_btc_bias(session)
            tasks = [scan_coin(session, sym, btc_bias, semaphore) for sym in all_symbols]
            await asyncio.gather(*tasks)

            if time.time() - last_backtest > 86400:
                asyncio.create_task(run_backtest(session))
                last_backtest = time.time()
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import aiohttp
import os
import time
import logging
import traceback
from statistics import mean, stdev

# ==================================================
# CONFIG
# ==================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = "https://fapi.binance.com"

SCAN_INTERVAL = 40
COOLDOWN = 600
MAX_CONCURRENT_REQUESTS = 20

last_signal = {}
telegram_queue = asyncio.Queue()

# ==================================================
# LOG
# ==================================================
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ==================================================
# MODE (auto-balanced)
# ==================================================
MODE_MULT = 1.0

# ==================================================
# TELEGRAM
# ==================================================
async def telegram_worker(session):
    while True:
        text = await telegram_queue.get()
        try:
            if not BOT_TOKEN or not CHAT_ID:
                print(text)
            else:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                await session.post(url, json={"chat_id": CHAT_ID, "text": text})
        except:
            logging.error(traceback.format_exc())
        finally:
            telegram_queue.task_done()
        await asyncio.sleep(0.2)

async def send_telegram(t):
    await telegram_queue.put(t)

# ==================================================
# FETCH
# ==================================================
async def fetch(session, endpoint, params=None):
    try:
        async with session.get(BASE_URL + endpoint, params=params, timeout=10) as r:
            if r.status != 200:
                return None
            return await r.json()
    except:
        return None

# ==================================================
# EMA
# ==================================================
def ema(v, p):
    if len(v) < p:
        return None
    m = 2/(p+1)
    e = mean(v[:p])
    for x in v[p:]:
        e = (x-e)*m + e
    return e

# ==================================================
# ATR
# ==================================================
def atr(h,l,c,p=14):
    if len(h) < p+1:
        return None
    tr=[]
    for i in range(1,len(h)):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    return mean(tr[-p:]) if len(tr)>=p else None

# ==================================================
# REGIME (upgrade)
# ==================================================
def regime(closes, vols):
    move = (closes[-1]-closes[0])/closes[0]
    vol = stdev(vols) if len(vols)>1 else 0
    z = (vols[-1]-mean(vols))/vol if vol>0 else 0

    score = 0
    if abs(move) > 0.01: score += 1
    if abs(move) > 0.02: score += 1
    if z > 1: score += 1

    if score >= 2:
        return "TREND"
    if abs(move) < 0.003:
        return "RANGE"
    return "MIXED"

# ==================================================
# SWEEP (improved fake breakout detection)
# ==================================================
def sweep(h,l,c):
    recent_high = max(h[-20:-1])
    recent_low = min(l[-20:-1])

    up = h[-1] > recent_high and c[-1] < h[-1]  # fake breakout
    down = l[-1] < recent_low and c[-1] > l[-1]

    return up, down

# ==================================================
# CVD SLOPE (NEW)
# ==================================================
def cvd_slope(closes, volumes):
    if len(closes) < 10:
        return 0

    cvd = 0
    arr = []

    for i in range(len(closes)):
        delta = volumes[i] * (1 if closes[i] > closes[i-1] else -1)
        cvd += delta
        arr.append(cvd)

    if len(arr) < 5:
        return 0

    x = list(range(5))
    y = arr[-5:]

    n = 5
    sx = sum(x)
    sy = sum(y)
    sxy = sum(x[i]*y[i] for i in range(5))
    sx2 = sum(i*i for i in x)

    denom = (n*sx2 - sx*sx)
    if denom == 0:
        return 0

    slope = (n*sxy - sx*sy) / denom

    if slope > 0:
        return 1
    if slope < 0:
        return -1
    return 0

# ==================================================
# ORDERFLOW (improved but lightweight)
# ==================================================
def orderflow(v, tb):
    if v <= 0:
        return 0

    r = tb/v
    d = (tb - (v-tb))/v

    score = 0
    if r > 0.6: score += 1
    if r < 0.4: score -= 1
    if d > 0.2: score += 1
    if d < -0.2: score -= 1

    return score

# ==================================================
# BTC BIAS
# ==================================================
async def btc(session):
    k = await fetch(session,"/fapi/v1/klines",
                   {"symbol":"BTCUSDT","interval":"15m","limit":50})
    if not k:
        return "NEUTRAL"

    c=[float(x[4]) for x in k]
    e20=ema(c,20)
    e50=ema(c,50)

    if not e20 or not e50:
        return "NEUTRAL"

    if c[-1]>e20>e50:
        return "BULLISH"
    if c[-1]<e20<e50:
        return "BEARISH"
    return "NEUTRAL"

# ==================================================
# CLASSIFIER (smarter)
# ==================================================
def classify(score):
    if score >= 9:
        return "🔥 GÜÇLÜ"
    if score >= 6:
        return "🟡 ORTA"
    if score >= 4:
        return "🟢 ZAYIF"
    return None

# ==================================================
# SYMBOLS
# ==================================================
async def symbols(session):
    d = await fetch(session,"/fapi/v1/exchangeInfo")
    return [s["symbol"] for s in d["symbols"]
            if s["quoteAsset"]=="USDT" and s["status"]=="TRADING"]

# ==================================================
# SCAN ENGINE (UPGRADED CORE)
# ==================================================
async def scan(session, symbol, btc_bias, sem):
    async with sem:
        try:
            k = await fetch(session,"/fapi/v1/klines",
                           {"symbol":symbol,"interval":"5m","limit":80})
            if not k:
                return

            c=[float(x[4]) for x in k]
            h=[float(x[2]) for x in k]
            l=[float(x[3]) for x in k]
            v=[float(x[5]) for x in k]

            change = (c[-1]-c[-2])/c[-2]*100
            vol_z = (v[-1]-mean(v))/(stdev(v) if len(v)>1 else 1)

            if abs(change) < 0.15 and vol_z < 0.6:
                return

            sw_u, sw_d = sweep(h,l,c)
            atrv = atr(h,l,c) or c[-1]*0.005

            of = orderflow(v[-1], float(k[-1][9]))
            cvd = cvd_slope(c,v)

            reg = regime(c,v)

            long=0
            short=0

            if change > 0.7: long += 2
            if change < -0.7: short += 2

            if sw_d: long += 4
            if sw_u: short += 4

            if of > 0: long += 1
            if of < 0: short += 1

            if cvd > 0: long += 2
            if cvd < 0: short += 2

            if reg == "TREND":
                long += 1
                short += 1

            if btc_bias == "BULLISH":
                long += 1
            if btc_bias == "BEARISH":
                short += 1

            score = max(long,short)
            sig = classify(score)
            if not sig:
                return

            direction = "LONG" if long>short else "SHORT"

            if symbol in last_signal and time.time()-last_signal[symbol] < COOLDOWN:
                return

            last_signal[symbol]=time.time()

            tp = c[-1] + atrv*2 if direction=="LONG" else c[-1]-atrv*2
            sl = c[-1] - atrv*1.5 if direction=="LONG" else c[-1]+atrv*1.5

            msg = f"{sig}\n{symbol}\n{direction}\nTP:{tp:.4f}\nSL:{sl:.4f}\nScore:{score}"
            print(msg)
            await send_telegram(msg)

        except:
            logging.error(traceback.format_exc())

# ==================================================
# MAIN LOOP
# ==================================================
async def main():
    async with aiohttp.ClientSession() as s:
        asyncio.create_task(telegram_worker(s))

        syms = await symbols(s)
        sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        await send_telegram("🚀 PRO BOT V2 ONLINE")

        while True:
            b = await btc(s)
            await asyncio.gather(*[scan(s,x,b,sem) for x in syms])
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

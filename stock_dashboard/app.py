from flask import Flask, render_template, jsonify
import threading, time, math, random
from datetime import datetime, timedelta

app = Flask(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache = {}
_cache_lock = threading.Lock()

def _cached(key, fn, ttl=60):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < ttl:
            return entry["data"]
    data = fn()
    with _cache_lock:
        _cache[key] = {"ts": time.time(), "data": data}
    return data

def cache_bust(key):
    with _cache_lock:
        _cache.pop(key, None)

# ── Realistic stock universe ───────────────────────────────────────────────────
# base_price, beta, short_pct, pe, mkt_cap_b, name
STOCK_DB = {
    "ARM":  (177.58,  3.34, 0.111, 236.8,  188.6, "Arm Holdings plc"),
    "AMD":  (289.08,  1.96, 0.022, 107.3,  456.5, "Advanced Micro Devices, Inc."),
    "IONQ": ( 49.13,  2.80, 0.223, None,    17.7, "IonQ, Inc."),
    "NVDA": (875.39,  1.78, 0.009, 68.2,  2156.0, "NVIDIA Corporation"),
    "SMCI": (796.43,  1.94, 0.062, 24.8,    45.2, "Super Micro Computer"),
    "COIN": (211.45,  3.21, 0.085, None,    52.4, "Coinbase Global, Inc."),
    "MSTR": (167.82,  3.89, 0.142, None,    26.1, "MicroStrategy Inc."),
    "PLTR": ( 21.07,  2.45, 0.034, 312.5,   43.8, "Palantir Technologies"),
    "TSLA": (275.30,  2.01, 0.028, 84.7,   883.2, "Tesla, Inc."),
    "GME":  ( 16.42,  1.87, 0.218, None,     5.1, "GameStop Corp."),
    "AMC":  (  3.84,  2.34, 0.261, None,     1.2, "AMC Entertainment"),
    "HOOD": ( 18.75,  3.12, 0.072, None,     4.8, "Robinhood Markets"),
    "SOFI": ( 11.23,  2.56, 0.098, None,    11.2, "SoFi Technologies"),
    "UPST": ( 52.67,  3.45, 0.156, None,     4.3, "Upstart Holdings"),
    "RIVN": ( 11.82,  2.23, 0.134, None,    12.8, "Rivian Automotive"),
    "LCID": (  2.41,  2.67, 0.189, None,     5.6, "Lucid Group, Inc."),
    "NKLA": (  0.82,  3.56, 0.312, None,     0.4, "Nikola Corporation"),
    "FFIE": (  0.31,  4.21, 0.423, None,     0.1, "Faraday Future Intel."),
    "ASTS": ( 21.45,  3.78, 0.087, None,     3.6, "AST SpaceMobile"),
    "RKLB": ( 17.89,  2.89, 0.067, None,     7.4, "Rocket Lab USA"),
    "LUNR": (  8.23,  3.45, 0.112, None,     1.8, "Intuitive Machines"),
    "SPCE": (  1.94,  4.12, 0.267, None,     0.5, "Virgin Galactic"),
    "QUBT": (  8.76,  3.23, 0.098, None,     1.2, "Quantum Computing Inc."),
    "RGTI": (  3.45,  3.67, 0.134, None,     0.9, "Rigetti Computing"),
    "BNTX": (106.23,  1.34, 0.021, 18.4,    24.8, "BioNTech SE"),
    "MRNA": ( 72.45,  1.78, 0.045, None,    28.3, "Moderna, Inc."),
    "SOXL": ( 38.92,  5.12, 0.112, None,     6.8, "Direxion Daily Semi 3X"),
    "TQQQ": ( 52.18,  3.45, 0.089, None,    18.4, "ProShares UltraPro QQQ"),
    "FNGU": ( 34.67,  4.23, 0.045, None,     4.2, "MicroSectors FANG+ 3X"),
    "ARKK": ( 46.23,  1.89, 0.056, None,     7.1, "ARK Innovation ETF"),
    "LABU": ( 12.45,  4.56, 0.134, None,     1.8, "Direxion Daily Biotech 3X"),
    "DPST": ( 18.67,  4.12, 0.098, None,     2.3, "Direxion Daily Bank 3X"),
    "NAIL": ( 24.89,  3.89, 0.078, None,     1.6, "Direxion Daily Homebldr 3X"),
    "CURE": ( 89.45,  2.34, 0.034, None,     1.4, "Direxion Daily Healthcare 3X"),
    "WEBL": ( 14.23,  4.67, 0.123, None,     1.9, "Direxion Daily Internet 3X"),
    "CLOV": (  1.82,  3.12, 0.234, None,     0.6, "Clover Health Investments"),
    "BSBY": (  4.56,  3.78, 0.178, None,     0.8, "Blue Star Israel Tech ETF"),
    "DKNG": ( 41.23,  2.45, 0.089, None,    18.7, "DraftKings Inc."),
    "OPEN": (  2.87,  2.89, 0.198, None,     1.3, "Opendoor Technologies"),
    "UWMC": (  5.34,  1.78, 0.112, 8.2,      2.1, "UWM Holdings"),
    "BBBY": (  0.08,  5.12, 0.567, None,     0.1, "Bed Bath & Beyond"),
    "BYND": (  4.23,  3.45, 0.312, None,     0.7, "Beyond Meat, Inc."),
    "WKHS": (  0.61,  4.23, 0.289, None,     0.2, "Workhorse Group"),
}

# Ticker bar stocks
TICKER_STOCKS = {
    "AAPL":  (218.32,  1.24, "Apple Inc."),
    "TSLA":  (275.30,  2.01, "Tesla, Inc."),
    "NVDA":  (875.39,  1.78, "NVIDIA Corporation"),
    "MSFT":  (432.18,  0.91, "Microsoft Corporation"),
    "AMZN":  (186.52,  1.14, "Amazon.com, Inc."),
    "GOOGL": (178.45,  1.06, "Alphabet Inc."),
    "META":  (506.32,  1.23, "Meta Platforms, Inc."),
    "SPY":   (534.21,  1.00, "SPDR S&P 500 ETF"),
    "QQQ":   (451.67,  1.12, "Invesco QQQ Trust"),
    **{k: (v[0], v[1], v[5]) for k, v in STOCK_DB.items()
       if k in {"ARM","AMD","IONQ","COIN","MSTR","GME","AMC","HOOD"}},
}

INDEX_DB = {
    "DOW":    ("^DJI",   49387.69, 236.93,  0.48),
    "S&P 500":("^GSPC",  7123.62,   59.31,  0.84),
    "NASDAQ": ("^IXIC",  24596.42,  336.46,  1.39),
    "OIL":    ("CL=F",     93.06,    3.81,   4.27),
    "GOLD":   ("GC=F",   4751.40,  -25.60,  -0.54),
    "SILVER": ("SI=F",     77.72,   -0.36,  -0.47),
    "BTC":    ("BTC-USD", 78984.0,  3534.0,  4.68),
    "VIX":    ("^VIX",     19.16,   -0.33,  -1.69),
}

OPTIONS_STOCKS = ["AAPL","TSLA","NVDA","SPY","MSFT","GLD","SLV"]
OPTIONS_DB = {
    "AAPL":  (218.32, "Apple Inc."),
    "TSLA":  (275.30, "Tesla, Inc."),
    "NVDA":  (875.39, "NVIDIA Corp."),
    "SPY":   (534.21, "SPDR S&P 500 ETF"),
    "MSFT":  (432.18, "Microsoft Corp."),
    "GLD":   (242.56, "SPDR Gold Shares"),
    "SLV":   ( 32.18, "iShares Silver Trust"),
}

WSB_POSTS = [
    ("Weekly Earnings Thread 4/28 – 4/24", "Earnings Thread", 1, 148, "44m ago"),
    ("Daily Discussion Thread for April 22, 2026", "Daily Discussion", 249, 10999, "7h ago"),
    ("2026 word of the year: retardmaxxing", "", 4821, 523, "12h ago"),
    ("I sold NVDA at $400 to buy IONQ calls. I'm in shambles.", "Loss", 6823, 1247, "2h ago"),
    ("ARM is going to crash, I feel it in my bones (not financial advice)", "Discussion", 1432, 876, "5h ago"),
    ("🚀 MSTR to $1000 EOY — here's why", "YOLO", 9234, 2341, "1h ago"),
    ("My AMD puts just printed 400%. I can't believe I was right.", "Gain", 11234, 3456, "30m ago"),
    ("Why is everyone sleeping on QUBT right now??", "Discussion", 892, 467, "3h ago"),
],

WHALES_FEED = [
    ("$SPY — MASSIVE put sweep 4,000 contracts 0DTE $530 strike", False, "2m ago"),
    ("$NVDA unusual call activity — 50,000 contracts Jan 2026 $1000 strike", True,  "7m ago"),
    ("Dark pool print $TSLA 1.2M shares @ $274.85", None, "15m ago"),
    ("$AMD bearish sweep — 10,000 puts expiring Friday $280 strike", False, "22m ago"),
    ("$ARM 6,000 calls bought — exp next week $180 strike", True,  "28m ago"),
    ("$QQQ dark pool — 800K shares bullish bias", True,  "34m ago"),
    ("$COIN puts 3,000 contracts — $200 strike, 2 weeks", False, "41m ago"),
    ("$MSTR unusual activity — 2,500 calls $175 strike monthly", True,  "48m ago"),
]

TWITTER_FEED = [
    ("@zerohedge",       "Fed balance sheet hits $7.8T — dollar debasement accelerating",                "4m ago"),
    ("@unusual_whales",  "BREAKING: Congress member bought $500K in NVDA calls before AI hearing",       "9m ago"),
    ("@markets",         "VIX spiking as tech mega-caps roll over — watch $QQQ 450 support",             "12m ago"),
    ("@charliebilello",  "S&P 500 now up 11 of the last 13 days — breadth still concerning",             "18m ago"),
    ("@sentimentrader",  "Retail put/call ratio hits lowest since Jan 2022 top — complacency extreme",   "25m ago"),
    ("@MacroAlf",        "Global liquidity cycle peaking — risk-off in Q3 increasingly likely",          "31m ago"),
    ("@kobeissiletter",  "NVDA gap above $800 is key — if it closes below expect rapid flush to $720",   "38m ago"),
    ("@elerianm",        "This market is priced for perfection when macro is far from perfect",           "45m ago"),
]

# ── Realistic price simulation ─────────────────────────────────────────────────
_rng_seed = int(time.time() // 300)  # refresh seed every 5 min

def _rng(seed_extra=0):
    return random.Random(_rng_seed + seed_extra)

def jitter(base, pct=0.02, rng=None):
    r = rng or random.Random()
    return base * (1 + r.uniform(-pct, pct))

def gen_price_history(base, beta=1.0, days=60, rng=None):
    r = rng or random.Random()
    prices = [base]
    daily_vol = 0.018 * beta
    drift = r.uniform(-0.001, 0.003)
    for _ in range(days - 1):
        chg = r.gauss(drift, daily_vol)
        prices.insert(0, prices[0] / (1 + chg))
    return prices

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)

def calc_ma20(closes):
    if len(closes) < 20:
        return None
    return sum(closes[-20:]) / 20

def calc_ma50(closes):
    if len(closes) < 50:
        return None
    return sum(closes[-50:]) / 50

def vs_ma20_pct(closes):
    ma = calc_ma20(closes)
    if ma is None:
        return None
    return round((closes[-1] - ma) / ma * 100, 1)

def humanize_cap(b):
    if b is None:
        return "N/A"
    if b >= 1000:
        return f"${b/1000:.1f}T"
    return f"${b:.1f}B"

def calc_score(rsi, ma_pct, beta, short_pct):
    rsi = rsi or 60
    ma_pct = ma_pct or 0
    beta = beta or 1
    short_pct = (short_pct or 0) * 100
    s = (
        min(40, max(0, (rsi - 50) * 1.6)) +
        min(30, max(0, ma_pct * 1.5)) +
        min(20, max(0, (beta - 1) * 6.5)) +
        min(10, max(0, short_pct * 0.4))
    )
    return min(100, round(s))

# ── Data generators ───────────────────────────────────────────────────────────
def gen_scanner():
    global _rng_seed
    _rng_seed = int(time.time() // 300)
    results = []
    for sym, (base, beta, short_pct, pe, cap_b, name) in STOCK_DB.items():
        r = _rng(hash(sym) % 1000)
        price = round(jitter(base, 0.03, r), 2)
        closes = gen_price_history(price, beta, 60, r)

        rsi = calc_rsi(closes)
        ma_pct = vs_ma20_pct(closes)

        # Skew high-momentum stocks to be overbought more often
        if beta > 2.5 and r.random() < 0.6:
            rsi = min(95, (rsi or 60) + r.uniform(10, 25))
            ma_pct = (ma_pct or 0) + r.uniform(8, 25)
            rsi = round(rsi, 1)
            ma_pct = round(ma_pct, 1)

        chg_5d = round(r.uniform(-8, 18) * beta / 2, 1)
        score = calc_score(rsi, ma_pct, beta, short_pct)

        signals = []
        if ma_pct and ma_pct > 10:
            signals.append(f"Stretched {ma_pct:+.1f}% above 20-day MA")
        if rsi and rsi > 70:
            signals.append(f"RSI {rsi:.1f} — heavily overbought")
        if short_pct and short_pct > 0.10:
            signals.append(f"High short interest: {short_pct*100:.1f}%")
        if beta > 2:
            signals.append(f"High beta {beta:.2f} — extreme volatility")
        if not signals:
            signals.append("Momentum signal triggered")

        results.append({
            "symbol": sym,
            "name": name,
            "price": price,
            "chg_pct": chg_5d,
            "score": score,
            "rsi": rsi,
            "pe": pe,
            "ma_pct": ma_pct,
            "beta": beta,
            "short_pct": round(short_pct * 100, 1),
            "mkt_cap": humanize_cap(cap_b),
            "high_risk": score >= 70,
            "signals": signals,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    high_risk = sum(1 for r in results if r["high_risk"])
    rsi_vals = [r["rsi"] for r in results if r["rsi"]]
    avg_rsi = round(sum(rsi_vals) / len(rsi_vals)) if rsi_vals else 0

    return {
        "results": results,
        "scanned": len(results),
        "high_risk": high_risk,
        "top_score": results[0]["score"] if results else 0,
        "avg_rsi": avg_rsi,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def gen_market():
    r = _rng(42)
    indices = []
    for label, (sym, base, chg, chg_pct) in INDEX_DB.items():
        price = round(jitter(base, 0.005, r), 2)
        c = round(jitter(chg, 0.1, r), 2)
        p = round(jitter(chg_pct, 0.1, r), 2)
        direction = "up" if c >= 0 else "down"
        if label in ("DOW", "S&P 500", "NASDAQ"):
            price_str = f"{price:,.2f}"
        elif label == "BTC":
            price_str = f"{price:,.0f}"
        else:
            price_str = f"{price:.2f}"
        indices.append({
            "label": label, "symbol": sym,
            "price": price_str,
            "change": f"{c:+,.2f}",
            "change_pct": f"{p:+.2f}%",
            "direction": direction,
        })

    # Performance matrix (realistic 5min/10min/30min/1hr/today/1wk)
    perf = {}
    base_returns = {
        "DOW":    [0.06, 0.00, 0.02, -0.07, 0.24, 1.67],
        "S&P 500":[0.01, 0.02, 0.04, -0.02, 0.29, 1.17],
        "NASDAQ": [0.02, 0.04, 0.04, -0.01, 0.57, 2.05],
    }
    cols = ["5m","10m","30m","1h","Today","1 Week"]
    for idx, vals in base_returns.items():
        noisy = [round(v + r.uniform(-0.03, 0.03), 2) for v in vals]
        perf[idx] = {c: f"{v:+.2f}%" for c, v in zip(cols, noisy)}

    # VIX sentiment
    vix_val = round(jitter(19.16, 0.05, r), 2)
    if vix_val < 15:
        score, label, zone = 72, "GREED — Bulls in control", "CALM"
    elif vix_val < 25:
        score, label, zone = 51, "NEUTRAL — Mixed signals from the crowd", "MODERATE"
    elif vix_val < 35:
        score, label, zone = 32, "FEAR — Caution warranted", "FEAR"
    else:
        score, label, zone = 12, "PANIC — Extreme fear in markets", "PANIC"

    return {
        "indices": indices,
        "perf": perf,
        "sentiment": {"score": score, "label": label},
        "vix": {"value": vix_val, "zone": zone},
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def gen_ticker():
    r = _rng(99)
    out = []
    for sym, (base, beta, name) in TICKER_STOCKS.items():
        price = round(jitter(base, 0.025, r), 2)
        chg = round(r.uniform(-5, 8) * beta / 2.5, 2)
        out.append({"symbol": sym, "price": price, "chg_pct": chg})
    return out

def gen_options():
    r = _rng(77)
    out = []
    for sym in OPTIONS_STOCKS:
        base, name = OPTIONS_DB.get(sym, (100, sym))
        price = round(jitter(base, 0.02, r), 2)
        chg_pct = round(r.uniform(-4, 5), 2)
        closes = gen_price_history(price, 1.2, 60, r)
        rsi = calc_rsi(closes)
        ma_pct = vs_ma20_pct(closes)
        ma20 = round(calc_ma20(closes), 2)
        ma50 = round(calc_ma50(closes) or ma20, 2)

        if rsi and rsi > 72:
            signal = "SELL"
        elif rsi and rsi < 38:
            signal = "BUY"
        elif ma_pct and ma_pct > 12:
            signal = "SELL"
        elif ma_pct and ma_pct < -8:
            signal = "BUY"
        else:
            signal = "HOLD"

        out.append({
            "symbol": sym, "price": price, "chg_pct": chg_pct,
            "signal": signal, "rsi": rsi, "ma_pct": ma_pct,
            "ma20": ma20, "ma50": ma50,
        })
    return out

def gen_reddit():
    posts = WSB_POSTS[0]
    return [
        {"title": t, "flair": f, "score": s, "comments": c, "age": a}
        for t, f, s, c, a in posts
    ]

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def market():
    return render_template("market.html")

@app.route("/scanner")
def scanner():
    return render_template("scanner.html")

@app.route("/options")
def options():
    return render_template("options.html")

@app.route("/portfolio")
def portfolio():
    return render_template("portfolio.html")

@app.route("/api/market")
def api_market():
    return jsonify(_cached("market", gen_market, ttl=30))

@app.route("/api/scan")
def api_scan():
    return jsonify(_cached("scan", gen_scanner, ttl=120))

@app.route("/api/scan/force")
def api_scan_force():
    global _rng_seed
    _rng_seed = int(time.time())
    cache_bust("scan")
    return jsonify(_cached("scan", gen_scanner, ttl=120))

@app.route("/api/options")
def api_options():
    return jsonify(_cached("options", gen_options, ttl=60))

@app.route("/api/reddit")
def api_reddit():
    return jsonify(_cached("reddit", gen_reddit, ttl=300))

@app.route("/api/ticker")
def api_ticker():
    return jsonify(_cached("ticker", gen_ticker, ttl=30))

@app.route("/api/whales")
def api_whales():
    return jsonify([
        {"text": t, "bull": b, "time": ts}
        for t, b, ts in WHALES_FEED
    ])

@app.route("/api/twitter")
def api_twitter():
    return jsonify([
        {"user": u, "text": t, "time": ts}
        for u, t, ts in TWITTER_FEED
    ])

if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")

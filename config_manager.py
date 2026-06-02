#!/usr/bin/env python3
"""
config_manager.py — Manage Binance trading config (ConfigMap in Kubernetes)

Usage:
    # Add ticker to watchlist
    python3 config_manager.py watchlist add TICKER [direction] [entry_zone] [sl] [tp1] [tp2] [tp3]
    
    # Remove ticker from watchlist
    python3 config_manager.py watchlist remove TICKER
    
    # Move ticker from watchlist to open position
    python3 config_manager.py position open TICKER [side] [leverage] [amount] [sl] [tp1] [tp2] [tp3]
    
    # Close position (move from open to closed)
    python3 config_manager.py position close TICKER [close_price]
    
    # List all tickers
    python3 config_manager.py list
    
    # Analyze ticker before adding
    python3 config_manager.py analyze TICKER

Examples:
    python3 config_manager.py watchlist add ZECUSDT LONG 520-540 470 575 600 689
    python3 config_manager.py watchlist add STGUSDT SHORT 0.38-0.42 0.445 0.327 0.280 0.210
    python3 config_manager.py watchlist remove BANANAS31
    python3 config_manager.py position open STGUSDT SHORT 3 10 0.445 0.327 0.280 0.210
    python3 config_manager.py position close ALLO 0.2
    python3 config_manager.py list
    python3 config_manager.py analyze BTCUSDT
"""

import sys
import json
import math
import urllib.request
import urllib.error
import subprocess
import os
import yaml
from datetime import datetime

BASE = "https://fapi.binance.com"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "k8s/config.yaml")
KUBECONFIG = os.path.expanduser("~/Downloads/core-1-4-kubeconfig.yaml")

# ─── Helpers ──────────────────────────────────────────────────────

def api_fetch(url, max_retries=3, retry_delay=300):
    """Fetch URL with retry on rate limit. retry_delay in seconds (default 5 min)."""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=15).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code == 418:  # Rate limit
                if attempt < max_retries - 1:
                    print(f"  Rate limit (HTTP {e.code}), waiting {retry_delay}s... (attempt {attempt+1}/{max_retries})")
                    import time
                    time.sleep(retry_delay)
                    continue
            raise
        except Exception:
            if attempt < max_retries - 1:
                import time
                time.sleep(5)
                continue
            raise

def get_klines(sym):
    kl = api_fetch(f"{BASE}/fapi/v1/klines?symbol={sym}USDT&interval=1d&limit=100")
    return {"close":[float(k[4]) for k in kl],"high":[float(k[2]) for k in kl],"low":[float(k[3]) for k in kl],"volume":[float(k[5]) for k in kl]}

def sma(d, p): return sum(d[-p:]) / p if len(d) >= p else d[-1]

def ema(d, p):
    if len(d) < p: return [d[-1]]
    k = 2 / (p + 1); r = [sum(d[:p]) / p]
    for i in range(p, len(d)): r.append(d[i] * k + r[-1] * (1 - k))
    return r

def calc_rsi(c, p=14):
    if len(c) < p + 1: return 50.0
    ch = [c[i] - c[i-1] for i in range(1, len(c))]
    g = [max(x, 0.0) for x in ch]; l = [max(-x, 0.0) for x in ch]
    ag = float(sum(g[:p])) / p; al = float(sum(l[:p])) / p
    for i in range(p, len(g)): ag = float(ag * (p-1) + g[i]) / p; al = float(al * (p-1) + l[i]) / p
    if al < 1e-10: return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)

def calc_macd(c):
    e12 = ema(c, 12); e26 = ema(c, 26)
    off = len(e12) - len(e26); m = [e12[off+i] - e26[i] for i in range(len(e26))]
    if len(m) < 9: return float(m[-1]), float(m[-1]), 0.0
    sig = float(ema(m, 9)[-1]); return float(m[-1]), sig, float(m[-1] - sig)

def calc_bb(c):
    w = c[-20:]; mid = sum(w) / 20.0; std = math.sqrt(sum((x-mid)**2 for x in w) / 20.0)
    rng = 4 * std
    return ((c[-1] - (mid - 2*std)) / rng * 100.0 if rng > 0 else 50.0)

def calc_atr(h, l, c):
    trs = [max(float(h[i]-l[i]), abs(float(h[i]-c[i-1])), abs(float(l[i]-c[i-1]))) for i in range(1, len(h))]
    return sum(trs[-14:]) / 14.0 if len(trs) >= 14 else 0.0

def phase(c, h, l, v):
    m5 = (c[-1] / c[-6] - 1) * 100 if len(c) >= 6 else 0
    g3 = sum(1 for i in range(-3, 0) if c[i] > c[i-1])
    if m5 > 50: return "PARABOLIC"
    if m5 > 20 and g3 < 2: return "REVERSAL_DOWN"
    if m5 < -20 and g3 >= 2: return "REVERSAL_UP"
    m10 = (c[-1] / c[-11] - 1) * 100 if len(c) >= 11 else 0
    if m10 > 15 and g3 >= 2: return "TREND_UP"
    if m10 < -15 and g3 < 2: return "TREND_DOWN"
    return "SIDEWAYS" if abs(m10) < 10 else "TRANSITION"

def score_ticker(ph, rv, bb_pos, macd, mom7, atr_pct, vol, side):
    ls = 0.0; ss = 0.0; R = []
    if ph == "PARABOLIC": ss += 25; ls -= 30; R += ["PARABOLIC→short +25"]
    elif ph == "REVERSAL_DOWN": ss += 20; ls -= 20
    elif ph == "REVERSAL_UP": ls += 20; ss -= 20
    elif ph == "TREND_UP": ls += 15; ss -= 15
    elif ph == "TREND_DOWN": ss += 15; ls -= 15
    elif ph == "SIDEWAYS":
        if side == "LONG" and bb_pos < 30: ls += 15
        elif side == "SHORT" and bb_pos > 70: ss += 15
    if side == "LONG":
        if rv < 25: ls += 20; R += [f"OS {rv:.0f} +20"]
        elif rv < 35: ls += 15
        elif rv > 70: ls -= 15
    else:
        if rv > 80: ss += 20; R += ["deep OB +20"]
        elif rv > 70: ss += 15
        elif rv < 30: ss -= 15
    if side == "LONG":
        if bb_pos < 15: ls += 20
        elif bb_pos < 30: ls += 12
        elif bb_pos > 80: ls -= 15
    else:
        if bb_pos > 90: ss += 20
        elif bb_pos > 70: ss += 12
        elif bb_pos < 20: ss -= 15
    if side == "LONG":
        if macd > 0: ls += 8
        elif macd < 0: ls -= 10
    else:
        if macd < 0: ss += 8
        elif macd > 0: ss -= 10
    if side == "LONG":
        if mom7 < -20: ls += 15; R += ["mean rev +15"]
        elif mom7 > 25: ls -= 20; R += ["chasing -20"]
        elif mom7 > 15: ls -= 10
    else:
        if mom7 > 30: ss += 15; R += ["parabolic +15"]
        elif mom7 > 15: ss += 8
        elif mom7 < -20: ss -= 10
    if vol > 2: ls += 10; ss += 10
    elif vol < 0.3: ls -= 10; ss -= 10
    if 45 < rv < 55 and 40 < bb_pos < 60 and abs(macd) < 0.001:
        ls -= 15; ss -= 15
    ls = max(0, min(100, int(ls)))
    ss = max(0, min(100, int(ss)))
    if ls >= ss: bd, bs = "LONG", ls
    else: bd, bs = "SHORT", ss
    if bs >= 80: gr = "A"
    elif bs >= 65: gr = "B"
    elif bs >= 50: gr = "C"
    elif bs >= 35: gr = "D"
    else: gr = "F"
    return ls, ss, bd, bs, gr, R

def fmt_price(v):
    """Format price: 4 decimals for <1, 2 decimals for >=1"""
    if isinstance(v, str):
        return v
    return f"${v:.4f}" if abs(v) < 1 else f"${v:.2f}"

def fmt_pct(v):
    return f"{v:+.1f}%"

F = fmt_price  # alias for backward compatibility

def validate_ticker(symbol):
    """Check if ticker exists on Binance Futures. Returns (ok, price, error)."""
    sym = symbol.upper().replace("USDT", "")
    try:
        t = api_fetch(f"{BASE}/fapi/v1/ticker/24hr?symbol={sym}USDT")
        return True, float(t['lastPrice']), None
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return False, 0, f"{sym}USDT not found on Binance Futures (400)"
        return False, 0, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, 0, str(e)

def load_config():
    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f)
    positions_data = json.loads(data['data']['positions.json'])
    return data, positions_data

def save_config(data):
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

def apply_config():
    env = os.environ.copy()
    env['KUBECONFIG'] = KUBECONFIG
    result = subprocess.run(['kubectl', 'apply', '-f', CONFIG_PATH], capture_output=True, text=True, env=env)
    if result.returncode == 0:
        print("✅ Config applied to Kubernetes")
    else:
        print(f"❌ kubectl error: {result.stderr}")
    return result.returncode == 0

def find_in_watchlist(watchlist, symbol):
    symbol = symbol.upper().replace("USDT", "")
    for i, w in enumerate(watchlist):
        if w['symbol'].replace("USDT", "") == symbol:
            return i, w
    return -1, None

def find_in_positions(positions, symbol, status="OPEN"):
    symbol = symbol.upper().replace("USDT", "")
    for i, p in enumerate(positions):
        if p['symbol'].replace("USDT", "") == symbol and p.get('status') == status:
            return i, p
    return -1, None

def get_price(symbol):
    t = api_fetch(f"{BASE}/fapi/v1/ticker/24hr?symbol={symbol.upper()}USDT")
    return float(t['lastPrice']), float(t['priceChangePercent'])

# ─── Commands ─────────────────────────────────────────────────────

def cmd_analyze(args):
    if not args:
        print("Usage: analyze TICKER")
        return
    sym = args[0].upper().replace("USDT", "")
    try:
        t = api_fetch(f"{BASE}/fapi/v1/ticker/24hr?symbol={sym}USDT")
        px = float(t['lastPrice']); ch = float(t['priceChangePercent'])
        d = get_klines(sym); c = d["close"]
        rv = calc_rsi(c); _, _, mh = calc_macd(c); bb_pos = calc_bb(c)
        atr = calc_atr(d["high"], d["low"], c); ap = atr / px * 100 if px > 0 else 0
        m7 = (c[-1] / c[-8] - 1.0) * 100.0
        vol = float(d["volume"][-1]) / (sum(d["volume"][-20:]) / 20.0) if sum(d["volume"][-20:]) > 0 else 1.0
        ph = phase(c, d["high"], d["low"], d["volume"])
        ls, ss, bd, bs, gr, R = score_ticker(ph, rv, bb_pos, mh, m7, ap, vol, "LONG")
        ls2, ss2, bd2, bs2, gr2, R2 = score_ticker(ph, rv, bb_pos, mh, m7, ap, vol, "SHORT")
        R += R2

        print(f"\n  {sym}/USDT — {F(px)} ({fmt_pct(ch)})")
        print(f"  RSI: {rv:.0f}  BB: {bb_pos:.0f}%  MACD: {mh:+.4f}  ATR: {ap:.1f}%")
        print(f"  Mom7d: {fmt_pct(m7)}  Vol: {vol:.1f}x  Phase: {ph}")
        print(f"  LONG: {ls}%  SHORT: {ss}%  BEST: {bd} {bs}% ({gr})")
        for r in R: print(f"    {r}")
    except Exception as e:
        print(f"Error: {e}")

def cmd_watchlist_add(args):
    if not args:
        print("Usage: watchlist add TICKER [direction] [entry_zone] [sl] [tp1] [tp2] [tp3]")
        return
    sym = args[0].upper().replace("USDT", "")
    direction = args[1].upper() if len(args) > 1 else None
    entry_zone = args[2] if len(args) > 2 else "n/a"
    sl = float(args[3]) if len(args) > 3 else 0
    tp1 = float(args[4]) if len(args) > 4 else 0
    tp2 = float(args[5]) if len(args) > 5 else 0
    tp3 = float(args[6]) if len(args) > 6 else 0

    # Validate ticker exists
    ok, px, err = validate_ticker(sym)
    if not ok:
        print(f"❌ {err}")
        print(f"  Add anyway? Use: python3 config_manager.py watchlist add {sym} SKIP")
        return

    # Auto-analyze if no direction given
    if not direction:
        try:
            t = api_fetch(f"{BASE}/fapi/v1/ticker/24hr?symbol={sym}USDT")
            px = float(t['lastPrice']); ch = float(t['priceChangePercent'])
            d = get_klines(sym); c = d["close"]
            rv = calc_rsi(c); _, _, mh = calc_macd(c); bb_pos = calc_bb(c)
            atr = calc_atr(d["high"], d["low"], c); ap = atr / px * 100 if px > 0 else 0
            m7 = (c[-1] / c[-8] - 1.0) * 100.0
            vol = float(d["volume"][-1]) / (sum(d["volume"][-20:]) / 20.0) if sum(d["volume"][-20:]) > 0 else 1.0
            ph = phase(c, d["high"], d["low"], d["volume"])
            ls, ss, bd, bs, gr, R = score_ticker(ph, rv, bb_pos, mh, m7, ap, vol, "LONG")
            ls2, ss2, bd2, bs2, gr2, R2 = score_ticker(ph, rv, bb_pos, mh, m7, ap, vol, "SHORT")
            direction = bd
            print(f"  Auto-analysis: {bd} {bs}% ({gr})")
            for r in R + R2: print(f"    {r}")
        except Exception as e:
            print(f"Auto-analysis failed: {e}")
            direction = "SKIP"

    data, positions_data = load_config()
    watchlist = positions_data['watchlist']

    # Check if already in watchlist
    idx, existing = find_in_watchlist(watchlist, sym)
    if existing:
        print(f"  {sym} already in watchlist: {existing['direction']}")
        print(f"  Updating...")
        watchlist.pop(idx)

    # Check if already in open positions
    idx2, existing_pos = find_in_positions(positions_data['positions'], sym, "OPEN")
    if existing_pos:
        print(f"  ⚠ {sym} already in OPEN positions!")
        print(f"  Close it first: python3 config_manager.py position close {sym}")
        return

    entry = {
        "symbol": f"{sym}USDT",
        "direction": direction,
        "entry_zone": entry_zone,
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "note": f"Added {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    }
    watchlist.insert(0, entry)
    positions_data['watchlist'] = watchlist
    data['data']['positions.json'] = json.dumps(positions_data, indent=2)
    save_config(data)
    apply_config()
    print(f"✅ {sym} added to watchlist as {direction}")

def cmd_watchlist_remove(args):
    if not args:
        print("Usage: watchlist remove TICKER")
        return
    sym = args[0].upper().replace("USDT", "")
    data, positions_data = load_config()
    watchlist = positions_data['watchlist']
    idx, existing = find_in_watchlist(watchlist, sym)
    if existing:
        watchlist.pop(idx)
        positions_data['watchlist'] = watchlist
        data['data']['positions.json'] = json.dumps(positions_data, indent=2)
        save_config(data)
        apply_config()
        print(f"✅ {sym} removed from watchlist")
    else:
        print(f"❌ {sym} not found in watchlist")

def cmd_position_open(args):
    if not args:
        print("Usage: position open TICKER [side] [leverage] [amount] [sl] [tp1] [tp2] [tp3]")
        return
    sym = args[0].upper().replace("USDT", "")
    side = args[1].upper() if len(args) > 1 else "SHORT"
    lev = int(args[2]) if len(args) > 2 else 2
    amount = float(args[3]) if len(args) > 3 else 10
    sl = float(args[4]) if len(args) > 4 else 0
    tp1 = float(args[5]) if len(args) > 5 else 0
    tp2 = float(args[6]) if len(args) > 6 else 0
    tp3 = float(args[7]) if len(args) > 7 else 0

    # Validate ticker exists
    ok, px, err = validate_ticker(sym)
    if not ok:
        print(f"❌ {err}")
        return
    ch = 0
    try:
        _, ch = get_price(sym)
    except:
        pass
    print(f"  Current price: {F(px)} ({fmt_pct(ch)})")

    # Auto-calculate SL/TP if not provided
    if sl == 0:
        d = get_klines(sym); c = d["close"]
        atr = calc_atr(d["high"], d["low"], c)
        if side == "SHORT":
            sl = round(px + atr * 1.5, 6)
            tp1 = round(px - (sl - px) * 1.5, 6)
            tp2 = round(px - (sl - px) * 2.5, 6)
            tp3 = round(px - (sl - px) * 4.0, 6)
        else:
            sl = round(max(px - atr * 1.5, px * 0.85), 6)
            tp1 = round(px + (px - sl) * 1.5, 6)
            tp2 = round(px + (px - sl) * 2.5, 6)
            tp3 = round(px + (px - sl) * 4.0, 6)
        print(f"  Auto SL/TP: SL={F(sl)} TP1={F(tp1)} TP2={F(tp2)} TP3={F(tp3)}")

    data, positions_data = load_config()

    # Check if already in open positions
    idx, existing = find_in_positions(positions_data['positions'], sym, "OPEN")
    if existing:
        print(f"  ⚠ {sym} already in OPEN positions!")
        print(f"  Entry: {F(existing['entry_price'])}  Side: {existing['side']}")
        return

    # Remove from watchlist if there
    wl_idx, wl_entry = find_in_watchlist(positions_data['watchlist'], sym)
    if wl_entry:
        positions_data['watchlist'].pop(wl_idx)
        print(f"  Removed {sym} from watchlist")

    # Add to open positions
    position = {
        "symbol": f"{sym}USDT",
        "side": side,
        "type": "FUTURES",
        "leverage": lev,
        "opened_at": datetime.utcnow().strftime('%Y-%m-%d'),
        "entry_price": px,
        "amount_usdt": amount,
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "status": "OPEN"
    }
    positions_data['positions'].append(position)
    data['data']['positions.json'] = json.dumps(positions_data, indent=2)
    save_config(data)
    apply_config()
    print(f"✅ {sym} {side} {lev}x @ {F(px)} opened")

def cmd_position_close(args):
    if not args:
        print("Usage: position close TICKER [close_price]")
        return
    sym = args[0].upper().replace("USDT", "")
    close_price = float(args[1]) if len(args) > 1 else None

    data, positions_data = load_config()
    idx, existing = find_in_positions(positions_data['positions'], sym, "OPEN")
    if not existing:
        print(f"❌ {sym} not found in open positions")
        return

    # Get current price if not provided
    if not close_price:
        try:
            close_price, _ = get_price(sym)
        except:
            close_price = existing['entry_price']

    # Calculate PnL
    entry = existing['entry_price']
    lev = existing.get('leverage', 2)
    amount = existing.get('amount_usdt', 10)
    side = existing['side']

    if side == "SHORT":
        pnl_usd = (entry / close_price - 1) * 100 * lev * amount / 100
    else:
        pnl_usd = (close_price / entry - 1) * 100 * lev * amount / 100

    # Update position
    existing['status'] = "CLOSED"
    existing['closed_at'] = datetime.utcnow().strftime('%Y-%m-%d')
    existing['close_price'] = close_price
    existing['pnl_usd'] = round(pnl_usd, 2)

    # Add to watchlist
    watchlist = positions_data['watchlist']
    wl_entry = {
        "symbol": f"{sym}USDT",
        "direction": side,
        "entry_zone": f"{float(entry)*0.95:.4f}-{float(entry)*1.05:.4f}" if entry < 1 else f"{entry*0.95:.2f}-{entry*1.05:.2f}",
        "sl": existing['sl'],
        "tp1": existing['tp1'],
        "tp2": existing.get('tp2', 0),
        "tp3": existing.get('tp3', 0),
        "note": f"Closed at {F(close_price)} (PnL ${pnl_usd:+.2f}). Re-entry zone."
    }
    watchlist.insert(0, wl_entry)

    data['data']['positions.json'] = json.dumps(positions_data, indent=2)
    save_config(data)
    apply_config()
    print(f"✅ {sym} closed at {F(close_price)}  PnL: ${pnl_usd:+.2f}")
    print(f"  Added back to watchlist")

def cmd_list(args):
    data, positions_data = load_config()
    positions = positions_data['positions']
    watchlist = positions_data['watchlist']

    def F(v):
        return f"${v:.4f}" if v < 1 else f"${v:.2f}"

    open_pos = [p for p in positions if p.get('status') == "OPEN"]
    closed_pos = [p for p in positions if p.get('status') == "CLOSED"]

    print(f"\n{'='*70}")
    print(f"  OPEN POSITIONS ({len(open_pos)})")
    print(f"{'='*70}")
    for p in open_pos:
        try:
            px, ch = get_price(p['symbol'].replace("USDT", ""))
            if p['side'] == "SHORT":
                pnl = (p['entry_price'] / px - 1) * 100 * p.get('leverage', 2)
            else:
                pnl = (px / p['entry_price'] - 1) * 100 * p.get('leverage', 2)
            pnl_usd = p.get('amount_usdt', 10) * pnl / 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            print(f"  {emoji} {p['symbol'].replace('USDT',''):8s} {p['side']:5s} {p.get('leverage',2)}x  "
                  f"Entry: {F(p['entry_price']):>10s}  Now: {F(px):>10s}  "
                  f"PnL: {fmt_pct(pnl)} (${pnl_usd:+.2f})")
            print(f"       SL: {F(p['sl'])}  TP1: {F(p['tp1'])}  TP2: {F(p.get('tp2',0))}  TP3: {F(p.get('tp3',0))}")
        except:
            print(f"  {p['symbol']} — error fetching price")

    print(f"\n{'='*70}")
    print(f"  WATCHLIST ({len(watchlist)})")
    print(f"{'='*70}")
    for w in watchlist:
        print(f"  {w['symbol'].replace('USDT',''):8s} {w['direction']:5s}  {w.get('entry_zone','n/a'):>15s}  SL: {F(w.get('sl',0))}")

    print(f"\n{'='*70}")
    print(f"  CLOSED POSITIONS ({len(closed_pos)})")
    print(f"{'='*70}")
    for p in closed_pos[-5:]:  # Last 5
        print(f"  {p['symbol'].replace('USDT',''):8s} {p['side']:5s}  "
              f"Entry: {F(p['entry_price'])}  Close: {F(p.get('close_price',0))}  "
              f"PnL: ${p.get('pnl_usd', 0):+.2f}")

    print(f"{'='*70}\n")

# ─── Main ─────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    if cmd == "analyze":
        cmd_analyze(args)
    elif cmd == "watchlist":
        if not args:
            print("Usage: watchlist add|remove TICKER")
            return
        subcmd = args[0].lower()
        if subcmd == "add":
            cmd_watchlist_add(args[1:])
        elif subcmd == "remove":
            cmd_watchlist_remove(args[1:])
        else:
            print(f"Unknown watchlist command: {subcmd}")
    elif cmd == "position":
        if not args:
            print("Usage: position open|close TICKER")
            return
        subcmd = args[0].lower()
        if subcmd == "open":
            cmd_position_open(args[1:])
        elif subcmd == "close":
            cmd_position_close(args[1:])
        else:
            print(f"Unknown position command: {subcmd}")
    elif cmd == "list":
        cmd_list(args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)

if __name__ == "__main__":
    main()

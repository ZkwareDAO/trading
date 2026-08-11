#!/usr/bin/env python3
"""subscribe_websocket.py — 币安 WebSocket 验证 (Phase 5)"""

import argparse, asyncio, json, os, sys, time

async def test_ws(symbol: str, timeframe: str = "1m",
                  ws_url: str = "wss://stream.binance.com:9443/ws", timeout: int = 30) -> dict:
    try: import websockets
    except ImportError: return {"success": False, "error": "pip install websockets", "symbol": symbol}
    stream = f"{symbol.lower()}@kline_{timeframe}"
    url = f"{ws_url}/{stream}"
    result = {"success": False, "symbol": symbol, "timeframe": timeframe, "url": url, "messages_received": 0}
    start = time.time()
    try:
        async with websockets.connect(url, ping_interval=None) as ws:
            result["connected"] = True
            while time.time() - start < timeout:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(msg)
                    result["messages_received"] += 1
                    if "k" in data:
                        k = data["k"]
                        result["success"] = True
                        result["sample"] = {"symbol": k.get("s"), "interval": k.get("i"),
                            "open": k.get("o"), "close": k.get("c"),
                            "high": k.get("h"), "low": k.get("l"), "volume": k.get("v")}
                        break
                except asyncio.TimeoutError: continue
    except asyncio.TimeoutError: result["error"] = f"timeout ({timeout}s)"
    except Exception as e: result["error"] = str(e)
    result["elapsed_seconds"] = round(time.time() - start, 1)
    return result

async def subscribe(symbols: list, streams: list, ws_url: str):
    try: import websockets
    except ImportError: print("pip install websockets"); return
    names = [f"{s.lower()}@{st}" for s in symbols for st in streams]
    url = f"{ws_url}/{'/'.join(names)}"
    print(f"Connected: {url}\n{len(names)} streams, Ctrl+C to stop")
    try:
        async with websockets.connect(url, ping_interval=180) as ws:
            async for msg in ws:
                data = json.loads(msg)
                if "data" in data: print(f"[{data.get('data',{}).get('e','?')}] {json.dumps(data,ensure_ascii=False)[:200]}")
                elif "result" in data: print(f"[response] id={data.get('id')}")
                else: print(f"[stream] {json.dumps(data,ensure_ascii=False)[:200]}")
    except KeyboardInterrupt: print("\nDisconnected")

def main():
    p = argparse.ArgumentParser(description="Binance WebSocket verification")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--symbols", default="")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--streams", default="kline_1m")
    p.add_argument("--ws-url", default="wss://stream.binance.com:9443/ws")
    p.add_argument("--test", action="store_true")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.add_argument("--subscribe", action="store_true")
    args = p.parse_args()
    ws_url = args.ws_url or os.environ.get("WS_URL", "wss://stream.binance.com:9443/ws")
    if args.subscribe:
        syms = [s.strip() for s in args.symbols.split(',')] if args.symbols else [args.symbol]
        strs = [s.strip() for s in args.streams.split(',')]
        asyncio.run(subscribe(syms, strs, ws_url))
        return 0
    if args.test:
        r = asyncio.run(test_ws(args.symbol, args.timeframe, ws_url, args.timeout))
        if args.json: print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        elif r["success"]:
            s = r.get("sample", {})
            print(f"OK WebSocket ({r['elapsed_seconds']}s)")
            print(f"  {s.get('symbol')} {s.get('interval')}: O={s.get('open')} H={s.get('high')} L={s.get('low')} C={s.get('close')}")
        else: print(f"FAIL: {r.get('error')}"); return 1
        return 0
    p.print_help()
    return 0

if __name__ == "__main__": sys.exit(main())

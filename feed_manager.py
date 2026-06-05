"""
Upstox Market Data Feed V3 Manager
Connects to Upstox WS → decodes Protobuf → broadcasts clean JSON to all browser clients
Single connection shared across all subscribers (efficient)
"""
import asyncio, json, ssl, httpx
import websockets
from typing import Set, Dict, Any
from token_manager import get_upstox_token

# ── Instrument keys ────────────────────────────────────────────────────────────
INSTRUMENTS = {
    # Indices
    "SENSEX":    "BSE_INDEX|SENSEX",
    "NIFTY":     "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "VIX":       "NSE_INDEX|India VIX",
    "MIDCPNIFTY":"NSE_INDEX|NIFTY MID SELECT",
}

UPSTOX_WS_AUTH_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
UPSTOX_WS_URL      = "wss://api.upstox.com/v3/feed/market-data-feed"

class FeedManager:
    def __init__(self):
        self.clients: Set[asyncio.Queue] = set()
        self.latest: Dict[str, Any] = {}
        self.running = False
        self._task = None

    def add_client(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self.clients.add(q)
        # send latest snapshot immediately
        if self.latest:
            try:
                q.put_nowait(self.latest.copy())
            except asyncio.QueueFull:
                pass
        return q

    def remove_client(self, q: asyncio.Queue):
        self.clients.discard(q)

    async def _broadcast(self, data: dict):
        self.latest = data
        dead = set()
        for q in self.clients:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.add(q)
        self.clients -= dead

    async def _get_ws_url(self) -> str:
        token = get_upstox_token()
        async with httpx.AsyncClient() as client:
            r = await client.get(
                UPSTOX_WS_AUTH_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "*/*"},
                follow_redirects=False,
            )
            if r.status_code in (200, 302):
                data = r.json()
                return data.get("data", {}).get("authorized_redirect_uri", UPSTOX_WS_URL)
            raise RuntimeError(f"WS auth failed: {r.status_code} {r.text}")

    async def _decode_feed(self, raw: bytes) -> dict | None:
        """
        Decode Upstox V3 Protobuf feed.
        We use the upstox-python-sdk if available, else fallback to raw parse.
        """
        try:
            from upstox_client.feeder.proto import MarketDataFeed_pb2
            feed = MarketDataFeed_pb2.FeedResponse()
            feed.ParseFromString(raw)
            result = {}
            for key, val in feed.feeds.items():
                ff = val.ff
                result[key] = {
                    "ltp":   ff.marketFF.ltpc.ltp   if ff.HasField("marketFF") else 0,
                    "close": ff.marketFF.ltpc.cp    if ff.HasField("marketFF") else 0,
                    "open":  ff.marketFF.ltpc.open  if ff.HasField("marketFF") else 0,
                    "high":  ff.marketFF.eFeedDetails.high52Week if ff.HasField("marketFF") else 0,
                    "low":   ff.marketFF.eFeedDetails.low52Week  if ff.HasField("marketFF") else 0,
                    "vol":   ff.marketFF.eFeedDetails.vtt        if ff.HasField("marketFF") else 0,
                    "oi":    ff.marketFF.eFeedDetails.oi         if ff.HasField("marketFF") else 0,
                    "delta": ff.optionGreeks.delta if ff.HasField("optionGreeks") else None,
                    "iv":    ff.optionGreeks.iv    if ff.HasField("optionGreeks") else None,
                    "theta": ff.optionGreeks.theta if ff.HasField("optionGreeks") else None,
                    "vega":  ff.optionGreeks.vega  if ff.HasField("optionGreeks") else None,
                }
            return result if result else None
        except ImportError:
            # Fallback: try upstox_client v3 decode
            try:
                import upstox_client
                decoded = upstox_client.MarketDataFeed.decode(raw)
                return decoded
            except Exception:
                return None
        except Exception:
            return None

    async def _run(self):
        while True:
            try:
                ws_url = await self._get_ws_url()
                print(f"[FEED] Connecting to Upstox WS: {ws_url[:60]}...")

                ssl_ctx = ssl.create_default_context()
                async with websockets.connect(
                    ws_url,
                    ssl=ssl_ctx,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    print("[FEED] Connected to Upstox V3 feed")

                    # Subscribe to indices
                    sub_msg = json.dumps({
                        "guid": "mtu-feed-001",
                        "method": "sub",
                        "data": {
                            "mode": "full",
                            "instrumentKeys": list(INSTRUMENTS.values()),
                        }
                    }).encode()
                    await ws.send(sub_msg)
                    print(f"[FEED] Subscribed to {len(INSTRUMENTS)} instruments")

                    async for raw in ws:
                        if isinstance(raw, bytes):
                            decoded = await self._decode_feed(raw)
                            if decoded:
                                # Map instrument keys back to friendly names
                                named = {}
                                reverse = {v: k for k, v in INSTRUMENTS.items()}
                                for ikey, data in decoded.items():
                                    name = reverse.get(ikey, ikey)
                                    named[name] = data
                                if named:
                                    await self._broadcast({
                                        "type": "tick",
                                        "data": named,
                                        "ts":   asyncio.get_event_loop().time(),
                                    })
                        elif isinstance(raw, str):
                            # Market status message (JSON)
                            try:
                                msg = json.loads(raw)
                                await self._broadcast({"type": "market_info", "data": msg})
                            except Exception:
                                pass

            except Exception as e:
                print(f"[FEED] Error: {e} — reconnecting in 3s...")
                await asyncio.sleep(3)

    def start(self):
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._run())
            print("[FEED] FeedManager started")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()


# Global singleton
feed_manager = FeedManager()

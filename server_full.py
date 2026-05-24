# ─────────────────────────────────────────────────────────────
#  TradeCopier Pro - السيرفر الكامل (Master + Slave)
#  تشغيل: pip install fastapi uvicorn requests
#          python server_full.py
# ─────────────────────────────────────────────────────────────

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uvicorn, threading, requests, os, uuid

app = FastAPI(title="TradeCopier Pro", version="2.0")
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_SECRET = os.getenv("API_KEY", "YOUR_SECRET_API_KEY")

# ── قواعد البيانات في الذاكرة ────────────────────────────────
masters     = {}  # { master_id: info }
subscribers = {}  # { master_id: [sub, ...] }
open_trades = {}  # { master_id: { ticket: trade } }
trade_log   = []  # كل الأحداث

# صندوق الإشارات لكل slave يعمل بنظام Polling
slave_queues = {}  # { "master_id:slave_name": [signals] }

# ─────────────────────────────────────────────────────────────
# نماذج البيانات
# ─────────────────────────────────────────────────────────────
class TradeSignal(BaseModel):
    action:         str
    master_id:      str
    ticket:         int
    symbol:         str
    type:           Optional[str]   = None
    volume:         Optional[float] = None
    open_price:     Optional[float] = None
    sl:             Optional[float] = None
    tp:             Optional[float] = None
    profit:         Optional[float] = None
    close_price:    Optional[float] = None
    open_time:      Optional[str]   = None
    comment:        Optional[str]   = ""
    lot_multiplier: Optional[float] = 1.0

class Heartbeat(BaseModel):
    master_id:   str
    account:     int
    server:      str
    balance:     float
    equity:      float
    open_trades: int
    timestamp:   str

class SubscriberAdd(BaseModel):
    master_id:   str
    name:        str
    webhook_url: str
    ratio:       float = 1.0

class AckSignal(BaseModel):
    signal_id: str
    slave:     str
    status:    str

# ─────────────────────────────────────────────────────────────
def verify_key(x_api_key: str = Header(None)):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="مفتاح خاطئ")

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def queue_key(master_id, slave_name):
    return f"{master_id}:{slave_name}"

# ─────────────────────────────────────────────────────────────
# 1. استقبال إشارة من EA المعلم
# ─────────────────────────────────────────────────────────────
@app.post("/api/trades/signal")
async def receive_signal(signal: TradeSignal, x_api_key: str = Header(None)):
    verify_key(x_api_key)

    mid = signal.master_id
    sig_id = "sig_" + uuid.uuid4().hex[:10]

    log_entry = {**signal.dict(), "id": sig_id, "received_at": now()}
    trade_log.append(log_entry)

    if signal.action == "OPEN":
        if mid not in open_trades: open_trades[mid] = {}
        open_trades[mid][signal.ticket] = {**signal.dict(), "opened_at": now()}
        print(f"[OPEN]  {signal.symbol} {signal.type} {signal.volume} @ {signal.open_price}")

    elif signal.action == "CLOSE":
        if mid in open_trades and signal.ticket in open_trades[mid]:
            del open_trades[mid][signal.ticket]
        print(f"[CLOSE] #{signal.ticket} profit={signal.profit}")

    elif signal.action == "MODIFY":
        if mid in open_trades and signal.ticket in open_trades[mid]:
            open_trades[mid][signal.ticket]["sl"] = signal.sl
            open_trades[mid][signal.ticket]["tp"] = signal.tp
        print(f"[MODIFY] #{signal.ticket} SL={signal.sl} TP={signal.tp}")

    # ── وزّع الإشارة على جميع المشتركين ──
    broadcast(mid, sig_id, signal)

    return {"status": "ok", "signal_id": sig_id}

# ─────────────────────────────────────────────────────────────
# 2. Heartbeat من المعلم
# ─────────────────────────────────────────────────────────────
@app.post("/api/master/heartbeat")
async def heartbeat(hb: Heartbeat, x_api_key: str = Header(None)):
    verify_key(x_api_key)
    masters[hb.master_id] = {**hb.dict(), "last_seen": now(), "online": True}
    return {"status": "alive"}

# ─────────────────────────────────────────────────────────────
# 3. إضافة مشترك
# ─────────────────────────────────────────────────────────────
@app.post("/api/subscribers/add")
async def add_subscriber(sub: SubscriberAdd, x_api_key: str = Header(None)):
    verify_key(x_api_key)
    if sub.master_id not in subscribers:
        subscribers[sub.master_id] = []

    # تحقق من التكرار
    for s in subscribers[sub.master_id]:
        if s["name"] == sub.name:
            return {"status": "already_exists"}

    entry = {
        "name": sub.name,
        "webhook_url": sub.webhook_url,
        "ratio": sub.ratio,
        "active": True,
        "joined_at": now(),
        "copies": 0,
        "errors": 0
    }
    subscribers[sub.master_id].append(entry)

    # أنشئ queue للـ slave
    key = queue_key(sub.master_id, sub.name)
    if key not in slave_queues:
        slave_queues[key] = []

    print(f"[SUB+] {sub.name} اشترك في {sub.master_id}")
    return {"status": "ok", "message": f"مرحباً {sub.name}!"}

# ─────────────────────────────────────────────────────────────
# 4. Slave يسحب الإشارات الجديدة (Polling)
# ─────────────────────────────────────────────────────────────
@app.get("/api/slave/signals")
async def get_signals(master_id: str, slave: str, x_api_key: str = Header(None)):
    verify_key(x_api_key)

    key = queue_key(master_id, slave)
    if key not in slave_queues:
        slave_queues[key] = []
        return []

    signals = slave_queues[key].copy()
    return signals  # لا نحذفها حتى يؤكد الـ slave الاستلام

# ─────────────────────────────────────────────────────────────
# 5. Slave يؤكد تنفيذ الإشارة
# ─────────────────────────────────────────────────────────────
@app.post("/api/slave/ack")
async def ack_signal(ack: AckSignal, x_api_key: str = Header(None)):
    verify_key(x_api_key)

    # احذف الإشارة من الـ queue بعد التأكيد
    for master_id in subscribers:
        key = queue_key(master_id, ack.slave)
        if key in slave_queues:
            slave_queues[key] = [
                s for s in slave_queues[key] if s.get("id") != ack.signal_id
            ]

    # تحديث عداد النسخ
    for master_id, subs in subscribers.items():
        for s in subs:
            if s["name"] == ack.slave:
                s["copies"] += 1

    return {"status": "ok"}

# ─────────────────────────────────────────────────────────────
# 6. لوحة التحكم
# ─────────────────────────────────────────────────────────────
@app.get("/api/dashboard/{master_id}")
async def dashboard(master_id: str):
    subs   = subscribers.get(master_id, [])
    trades = list(open_trades.get(master_id, {}).values())
    master = masters.get(master_id, {})

    closed = [t for t in trade_log if t.get("master_id") == master_id and t.get("action") == "CLOSE"]
    wins   = [t for t in closed if (t.get("profit") or 0) > 0]

    return {
        "master":       master,
        "open_trades":  trades,
        "subscribers":  subs,
        "stats": {
            "open_count":          len(trades),
            "subscriber_count":    len(subs),
            "active_subscribers":  len([s for s in subs if s["active"]]),
            "total_closed":        len(closed),
            "win_rate":            round(len(wins)/len(closed)*100,1) if closed else 0,
        }
    }

@app.get("/api/status")
async def status():
    return {
        "status":   "running ✅",
        "masters":  len(masters),
        "subs":     sum(len(v) for v in subscribers.values()),
        "signals":  len(trade_log),
        "time":     now()
    }

# ─────────────────────────────────────────────────────────────
# بث الإشارة لجميع المشتركين
# ─────────────────────────────────────────────────────────────
def broadcast(master_id: str, sig_id: str, signal: TradeSignal):
    subs = [s for s in subscribers.get(master_id, []) if s["active"]]
    if not subs:
        print(f"[BROADCAST] لا يوجد مشتركون نشطون")
        return

    payload = {
        **signal.dict(),
        "id": sig_id,
        "volume": round((signal.volume or 0.01), 2)
    }

    def send(sub):
        key = queue_key(master_id, sub["name"])
        if key not in slave_queues:
            slave_queues[key] = []

        # أضف الإشارة لـ queue الـ slave (نظام Polling)
        slave_queues[key].append(payload)
        sub["copies"] += 1
        print(f"  📬 {sub['name']}: إشارة في الانتظار")

        # إذا كان عنده webhook حقيقي أرسله مباشرة
        if sub["webhook_url"] not in ["poll", "", None]:
            try:
                r = requests.post(sub["webhook_url"], json=payload, timeout=4)
                print(f"  ✅ {sub['name']} webhook: {r.status_code}")
            except Exception as e:
                sub["errors"] += 1
                print(f"  ❌ {sub['name']} webhook: {e}")

    threads = [threading.Thread(target=send, args=(s,)) for s in subs]
    for t in threads: t.start()
    for t in threads: t.join()
    print(f"[BROADCAST] {signal.action} → {len(subs)} مشتركين")

# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  TradeCopier Pro Server - Master + Slave")
    print("  http://localhost:8000")
    print("  API Docs: http://localhost:8000/docs")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8000)

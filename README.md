# TradeCopier Pro — دليل الإعداد الكامل

## الملفات
| الملف | الوصف |
|-------|-------|
| `TradeCopierPro.mq5` | Expert Advisor يُركَّب على MT5 (حساب المعلم) |
| `server.py`           | السيرفر الذي يستقبل الصفقات ويوزعها |
| `forex-trade-copier.html` | لوحة التحكم الويب |

---

## الخطوة 1 — تشغيل السيرفر

```bash
pip install fastapi uvicorn requests
python server.py
```
السيرفر يعمل على: http://localhost:8000
الـ Docs التلقائية: http://localhost:8000/docs

---

## الخطوة 2 — ضبط الـ EA في MT5

1. افتح MT5 → انقر **File > Open Data Folder**
2. اذهب إلى مجلد: `MQL5 > Experts`
3. انسخ ملف `TradeCopierPro.mq5` هناك
4. في MT5: **Tools > Options > Expert Advisors**
   - فعّل: Allow Automated Trading
   - فعّل: Allow WebRequest
   - أضف رابط السيرفر: `http://localhost:8000`
5. اسحب الـ EA على أي شارت وعدّل الإعدادات:
   - `API_URL` = رابط سيرفرك
   - `API_KEY` = نفس المفتاح في `server.py`
   - `MASTER_ID` = معرفك الفريد

---

## الخطوة 3 — ربط المشتركين

أرسل لكل مشترك هذا الطلب (أو اعمل زر في اللوحة):

```bash
curl -X POST http://your-server/api/subscribers/add \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "master_id": "USR-A7X29",
    "name": "أحمد",
    "webhook_url": "http://subscriber-server/receive",
    "ratio": 1.0
  }'
```

---

## الخطوة 4 — رفع السيرفر على الإنترنت

**الخيار المجاني (Railway):**
1. سجّل على railway.app
2. ارفع ملف `server.py`
3. احصل على رابط مثل: `https://tradecopier.railway.app`
4. استخدمه في إعدادات الـ EA

---

## تدفق العمل

```
MT5 (حسابك) 
   ↓ كل 2 ثانية
TradeCopierPro EA
   ↓ HTTP POST
السيرفر (server.py)
   ↓ بث فوري
المشترك 1 ← webhook → MT5 slave
المشترك 2 ← webhook → MT5 slave
المشترك 3 ← webhook → MT5 slave
```

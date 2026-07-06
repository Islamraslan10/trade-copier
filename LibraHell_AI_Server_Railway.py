# ============================================================
#  LibraHell AI Server - Railway Edition
#  Islam Raslan
# ============================================================

from flask import Flask, request, jsonify
import numpy as np
import json
import logging
import os
from datetime import datetime

app = Flask(__name__)

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.72

# ============================================================
def build_features(data: dict) -> np.ndarray:
    signal      = float(data.get("signal", 0))
    quality     = float(data.get("quality", 0))
    s9_angle    = float(data.get("s9_angle", 90))
    entry       = float(data.get("entry", 0))
    sl          = float(data.get("sl", 0))
    tp          = float(data.get("tp", 0))
    lot         = float(data.get("lot", 0.01))
    open_trades = float(data.get("open_trades", 0))
    daily_loss  = float(data.get("daily_loss", 0))
    balance     = float(data.get("balance", 100))

    sl_dist  = abs(entry - sl) / entry if entry > 0 else 0
    tp_dist  = abs(tp - entry) / entry if entry > 0 else 0
    rr_ratio = tp_dist / sl_dist if sl_dist > 0 else 0

    if s9_angle % 360 == 0:   angle_strength = 1.0
    elif s9_angle % 180 == 0: angle_strength = 0.8
    elif s9_angle % 90  == 0: angle_strength = 0.6
    else:                     angle_strength = 0.3

    return np.array([
        signal, quality / 100.0, angle_strength,
        sl_dist, tp_dist, rr_ratio, lot,
        open_trades / 5.0, daily_loss / 10.0, balance / 10000.0
    ], dtype=np.float32)

# ============================================================
def rule_based_predict(data: dict, features: np.ndarray) -> dict:
    confidence = 0.50
    reason     = []

    quality     = features[1] * 100
    rr_ratio    = features[5]
    angle_str   = features[2]
    daily_loss  = features[8] * 10
    open_trades = features[7] * 5

    if quality >= 75:      confidence += 0.12; reason.append("High quality")
    if angle_str >= 0.8:   confidence += 0.10; reason.append("Strong Gann angle")
    if rr_ratio >= 2.0:    confidence += 0.08; reason.append("Good R:R")
    if daily_loss < 1.5:   confidence += 0.06; reason.append("Low daily loss")
    if open_trades <= 1:   confidence += 0.05; reason.append("Few open trades")
    if quality < 65:       confidence -= 0.20; reason.append("Low quality")
    if rr_ratio < 1.5:     confidence -= 0.15; reason.append("Poor R:R")
    if daily_loss >= 2.5:  confidence -= 0.25; reason.append("Near daily limit")

    confidence = max(0.0, min(1.0, confidence))

    return {
        "approved":   confidence >= MIN_CONFIDENCE,
        "confidence": round(confidence, 4),
        "reason":     " | ".join(reason),
        "model":      "rule_based_v1"
    }

# ============================================================
@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data", "approved": False, "confidence": 0.0}), 400

        log.info(f"{data.get('symbol')} | signal={data.get('signal')} | quality={data.get('quality')}")

        features = build_features(data)
        result   = rule_based_predict(data, features)

        result["timestamp"]   = datetime.utcnow().isoformat()
        result["symbol"]      = data.get("symbol", "")
        result["signal_echo"] = data.get("signal", 0)

        log.info(f"approved={result['approved']} conf={result['confidence']}")
        return jsonify(result), 200

    except Exception as e:
        log.error(str(e))
        return jsonify({"error": str(e), "approved": False, "confidence": 0.0}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":  "running",
        "version": "LibraHell AI v1.0",
        "time":    datetime.utcnow().isoformat()
    }), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "LibraHell AI Server is running!"}), 200


# Railway يحدد PORT تلقائياً
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

"""
╔══════════════════════════════════════════════════════════════════╗
║       CTadvanced  —  License Server  v2.0  —  CASTTWEAKS®       ║
║   Backend Flask para Render.com                                   ║
║                                                                   ║
║   NUEVAS FUNCIONES v2:                                            ║
║     - Log de intentos fallidos de verificación                   ║
║     - Blacklist de HWIDs                                         ║
║     - Límite de dispositivos por clave (multi-PC)                ║
║     - Protección anti brute-force por IP                         ║
║     - Modo mantenimiento global                                   ║
║     - Tipos de licencia: Basic / Pro / Lifetime                  ║
║     - Editar nota interna de una licencia                        ║
║                                                                   ║
║   Variables de entorno requeridas en Render:                     ║
║     OWNER_SECRET   → mismo valor que en el cliente               ║
║     OWNER_API_KEY  → clave secreta para rutas de owner           ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os, json, hmac, hashlib, base64, time
from datetime import date, datetime, timedelta
from functools import wraps
from collections import defaultdict
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Configuración desde variables de entorno ─────────────────────
OWNER_SECRET  = os.environ.get("OWNER_SECRET",  "CASTTWEAKS_SECRET_2024_DONT_SHARE")
OWNER_API_KEY = os.environ.get("OWNER_API_KEY", "CHANGE_THIS_IN_RENDER_ENV")
DB_FILE       = "licenses.json"

# ── Tipos de licencia disponibles ────────────────────────────────
LICENSE_TYPES = ["Basic", "Pro", "Lifetime"]

# ── Rate limiting en memoria ──────────────────────────────────────
_rate_limit: dict = defaultdict(list)
RATE_LIMIT_WINDOW = 60    # segundos
RATE_LIMIT_MAX    = 10    # intentos máximos por ventana por IP


# ──══════════════════════════════════════════════════════════════
#  BASE DE DATOS
# ──══════════════════════════════════════════════════════════════

def _load_db() -> dict:
    try:
        with open(DB_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "licenses":       {},
            "hwid_blacklist": {},
            "failed_log":     [],
            "settings": {
                "maintenance":     False,
                "maintenance_msg": "El servicio está en mantenimiento. Vuelve pronto.",
            },
        }


def _save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def _ensure_keys(db: dict) -> dict:
    db.setdefault("licenses",       {})
    db.setdefault("hwid_blacklist", {})
    db.setdefault("failed_log",     [])
    db.setdefault("settings", {
        "maintenance":     False,
        "maintenance_msg": "El servicio está en mantenimiento. Vuelve pronto.",
    })
    return db


# ──══════════════════════════════════════════════════════════════
#  CRIPTOGRAFÍA
# ──══════════════════════════════════════════════════════════════

def _sign(payload: str) -> str:
    return hmac.new(
        OWNER_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def generate_license(username: str, days: int, hwid: str = "") -> str:
    exp     = (date.today() + timedelta(days=days)).isoformat()
    payload = f"{username}|{exp}|{hwid}"
    sig     = _sign(payload)
    raw     = f"{payload}||{sig}"
    key     = base64.b64encode(raw.encode()).decode().rstrip("=")
    return "-".join(key[i:i+8] for i in range(0, len(key), 8))


def decode_key(key: str) -> dict | None:
    try:
        raw = key.replace("-", "").replace(" ", "")
        pad = 4 - len(raw) % 4
        if pad != 4:
            raw += "=" * pad
        decoded      = base64.b64decode(raw).decode()
        payload, sig = decoded.rsplit("||", 1)
        parts        = payload.split("|")
        username, exp_str, hwid = parts[0], parts[1], parts[2]
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        return {"username": username, "expires": exp_str, "hwid": hwid}
    except Exception:
        return None


# ──══════════════════════════════════════════════════════════════
#  HELPERS DE SEGURIDAD
# ──══════════════════════════════════════════════════════════════

def _get_ip() -> str:
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _rate_limit[ip] = [t for t in _rate_limit[ip] if now - t < RATE_LIMIT_WINDOW]
    _rate_limit[ip].append(now)
    return len(_rate_limit[ip]) > RATE_LIMIT_MAX


def _log_failed(db: dict, ip: str, key_fragment: str, reason: str):
    db["failed_log"].append({
        "ts":           datetime.utcnow().isoformat(),
        "ip":           ip,
        "key_fragment": key_fragment[:20] if key_fragment else "",
        "reason":       reason,
    })
    # Mantener solo los últimos 500 registros
    if len(db["failed_log"]) > 500:
        db["failed_log"] = db["failed_log"][-500:]


# ──══════════════════════════════════════════════════════════════
#  DECORADORES
# ──══════════════════════════════════════════════════════════════

def require_owner(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-Owner-Key", "")
        if not hmac.compare_digest(api_key, OWNER_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ──══════════════════════════════════════════════════════════════
#  RUTAS PÚBLICAS
# ──══════════════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def health():
    db = _ensure_keys(_load_db())
    return jsonify({
        "status":      "ok",
        "ts":          datetime.utcnow().isoformat(),
        "maintenance": db["settings"].get("maintenance", False),
    })


@app.route("/api/verify", methods=["POST"])
def verify():
    """
    Verifica una clave con todas las comprobaciones de seguridad.
    Body: { key, hwid }
    """
    ip   = _get_ip()
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    hwid = (data.get("hwid") or "").strip()

    # ── 0. Rate limiting ────────────────────────────────────────
    if _is_rate_limited(ip):
        return jsonify({
            "valid": False,
            "error": "Demasiados intentos. Espera un momento e inténtalo de nuevo."
        }), 429

    db = _ensure_keys(_load_db())

    # ── 1. Modo mantenimiento ───────────────────────────────────
    if db["settings"].get("maintenance"):
        msg = db["settings"].get("maintenance_msg", "Servicio en mantenimiento.")
        return jsonify({"valid": False, "error": f"🔧 {msg}"})

    if not key:
        return jsonify({"valid": False, "error": "Clave vacía."}), 400

    # ── 2. Blacklist de HWID ────────────────────────────────────
    if hwid:
        bl_entry = db["hwid_blacklist"].get(hwid.upper())
        if bl_entry:
            reason = bl_entry.get("reason", "PC bloqueado.")
            _log_failed(db, ip, key, f"HWID bloqueado: {reason}")
            _save_db(db)
            return jsonify({"valid": False, "error": f"Este ordenador ha sido bloqueado: {reason}"})

    # ── 3. Firma criptográfica ──────────────────────────────────
    decoded = decode_key(key)
    if not decoded:
        _log_failed(db, ip, key, "Firma inválida")
        _save_db(db)
        return jsonify({"valid": False, "error": "Firma inválida. Clave incorrecta o modificada."})

    # ── 4. Clave registrada ─────────────────────────────────────
    entry = db["licenses"].get(key)
    if entry is None:
        _log_failed(db, ip, key, "Clave no registrada")
        _save_db(db)
        return jsonify({"valid": False, "error": "Clave no registrada. Contacta al owner."})

    # ── 5. Revocación ───────────────────────────────────────────
    if entry.get("revoked"):
        reason = entry.get("revoke_reason", "Sin motivo.")
        _log_failed(db, ip, key, f"Revocada: {reason}")
        _save_db(db)
        return jsonify({"valid": False, "error": f"Licencia revocada: {reason}"})

    # ── 6. Caducidad ────────────────────────────────────────────
    try:
        exp_date  = date.fromisoformat(decoded["expires"])
        days_left = (exp_date - date.today()).days
        if days_left < 0:
            _log_failed(db, ip, key, "Expirada")
            _save_db(db)
            return jsonify({"valid": False, "error": f"Licencia expirada el {decoded['expires']}."})
    except Exception:
        return jsonify({"valid": False, "error": "Fecha de expiración inválida."})

    # ── 7. HWID binding con soporte multi-dispositivo ───────────
    max_devices   = entry.get("max_devices", 1)
    bound_devices = entry.get("bound_devices", [])
    hwid_in_key   = decoded.get("hwid", "")

    if hwid:
        if hwid_in_key:
            if hwid_in_key.upper() != hwid.upper():
                _log_failed(db, ip, key, "HWID fijo no coincide")
                _save_db(db)
                return jsonify({"valid": False, "error": "Esta clave está registrada en otro ordenador."})
        else:
            hwid_up   = hwid.upper()
            bound_up  = [h.upper() for h in bound_devices]
            if hwid_up not in bound_up:
                if len(bound_devices) >= max_devices:
                    _log_failed(db, ip, key, f"Límite {max_devices} dispositivos")
                    _save_db(db)
                    return jsonify({
                        "valid": False,
                        "error": (
                            f"Esta clave ya está activada en {max_devices} dispositivo(s). "
                            "Contacta al owner para cambiar de PC."
                        )
                    })
                bound_devices.append(hwid)
                entry["bound_devices"] = bound_devices
                if not entry.get("first_use"):
                    entry["first_use"] = datetime.utcnow().isoformat()

    # ── 8. Actualizar metadatos ─────────────────────────────────
    entry["last_seen"] = datetime.utcnow().isoformat()
    entry["last_ip"]   = ip
    entry["uses"]      = entry.get("uses", 0) + 1
    _save_db(db)

    return jsonify({
        "valid":        True,
        "username":     decoded["username"],
        "expires":      decoded["expires"],
        "days_left":    days_left,
        "license_type": entry.get("license_type", "Basic"),
        "max_devices":  max_devices,
    })


# ──══════════════════════════════════════════════════════════════
#  RUTAS OWNER — LICENCIAS
# ──══════════════════════════════════════════════════════════════

@app.route("/api/issue", methods=["POST"])
@require_owner
def issue():
    """Body: { username, days, hwid, note, license_type, max_devices }"""
    data         = request.get_json(silent=True) or {}
    username     = (data.get("username") or "").strip()
    days         = int(data.get("days", 30))
    hwid         = (data.get("hwid") or "").strip()
    note         = (data.get("note") or "").strip()
    license_type = (data.get("license_type") or "Basic").strip()
    max_devices  = int(data.get("max_devices", 1))

    if not username:
        return jsonify({"error": "username requerido"}), 400
    if days <= 0:
        return jsonify({"error": "days debe ser > 0"}), 400
    if license_type not in LICENSE_TYPES:
        license_type = "Basic"
    max_devices = max(1, min(max_devices, 10))

    key = generate_license(username, days, hwid)
    exp = (date.today() + timedelta(days=days)).isoformat()

    db = _ensure_keys(_load_db())
    db["licenses"][key] = {
        "username":      username,
        "expires":       exp,
        "note":          note,
        "license_type":  license_type,
        "max_devices":   max_devices,
        "bound_devices": [hwid] if hwid else [],
        "issued_at":     datetime.utcnow().isoformat(),
        "revoked":       False,
        "revoke_reason": "",
        "uses":          0,
        "last_seen":     "",
        "last_ip":       "",
        "first_use":     "",
    }
    _save_db(db)
    return jsonify({"key": key, "username": username, "expires": exp, "license_type": license_type})


@app.route("/api/revoke", methods=["POST"])
@require_owner
def revoke():
    data   = request.get_json(silent=True) or {}
    key    = (data.get("key") or "").strip()
    reason = (data.get("reason") or "Revocada por el owner.").strip()
    db     = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["revoked"]       = True
    db["licenses"][key]["revoke_reason"] = reason
    db["licenses"][key]["revoked_at"]    = datetime.utcnow().isoformat()
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/unrevoke", methods=["POST"])
@require_owner
def unrevoke():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["revoked"]       = False
    db["licenses"][key]["revoke_reason"] = ""
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/licenses", methods=["GET"])
@require_owner
def list_licenses():
    db = _ensure_keys(_load_db())
    return jsonify({"licenses": db["licenses"]})


@app.route("/api/delete", methods=["POST"])
@require_owner
def delete_license():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    del db["licenses"][key]
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/reset_hwid", methods=["POST"])
@require_owner
def reset_hwid():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["bound_devices"] = []
    db["licenses"][key]["first_use"]     = ""
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/edit_note", methods=["POST"])
@require_owner
def edit_note():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    note = (data.get("note") or "").strip()
    db   = _ensure_keys(_load_db())
    if key not in db["licenses"]:
        return jsonify({"error": "Clave no encontrada"}), 404
    db["licenses"][key]["note"] = note
    _save_db(db)
    return jsonify({"ok": True})


# ──══════════════════════════════════════════════════════════════
#  RUTAS OWNER — BLACKLIST DE HWIDs
# ──══════════════════════════════════════════════════════════════

@app.route("/api/blacklist_hwid", methods=["POST"])
@require_owner
def blacklist_hwid():
    data   = request.get_json(silent=True) or {}
    hwid   = (data.get("hwid") or "").strip().upper()
    reason = (data.get("reason") or "Bloqueado por el owner.").strip()
    if not hwid:
        return jsonify({"error": "hwid requerido"}), 400
    db = _ensure_keys(_load_db())
    db["hwid_blacklist"][hwid] = {
        "reason":   reason,
        "added_at": datetime.utcnow().isoformat(),
    }
    _save_db(db)
    return jsonify({"ok": True, "hwid": hwid})


@app.route("/api/unblacklist_hwid", methods=["POST"])
@require_owner
def unblacklist_hwid():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip().upper()
    db   = _ensure_keys(_load_db())
    db["hwid_blacklist"].pop(hwid, None)
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/hwid_blacklist", methods=["GET"])
@require_owner
def get_hwid_blacklist():
    db = _ensure_keys(_load_db())
    return jsonify({"blacklist": db["hwid_blacklist"]})


# ──══════════════════════════════════════════════════════════════
#  RUTAS OWNER — LOG Y SEGURIDAD
# ──══════════════════════════════════════════════════════════════

@app.route("/api/failed_log", methods=["GET"])
@require_owner
def get_failed_log():
    db = _ensure_keys(_load_db())
    return jsonify({"log": list(reversed(db["failed_log"]))})  # más recientes primero


@app.route("/api/clear_failed_log", methods=["POST"])
@require_owner
def clear_failed_log():
    db = _ensure_keys(_load_db())
    db["failed_log"] = []
    _save_db(db)
    return jsonify({"ok": True})


# ──══════════════════════════════════════════════════════════════
#  RUTAS OWNER — CONFIGURACIÓN
# ──══════════════════════════════════════════════════════════════

@app.route("/api/maintenance", methods=["POST"])
@require_owner
def set_maintenance():
    """Body: { enabled: bool, message: str }"""
    data    = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    msg     = (data.get("message") or "El servicio está en mantenimiento. Vuelve pronto.").strip()
    db      = _ensure_keys(_load_db())
    db["settings"]["maintenance"]     = enabled
    db["settings"]["maintenance_msg"] = msg
    _save_db(db)
    return jsonify({"ok": True, "maintenance": enabled})


@app.route("/api/settings", methods=["GET"])
@require_owner
def get_settings():
    db = _ensure_keys(_load_db())
    return jsonify({"settings": db["settings"]})


# ──══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ──══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(debug=True, port=5000)

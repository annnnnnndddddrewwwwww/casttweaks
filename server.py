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
            "discount_codes": {},
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
    db.setdefault("discount_codes", {})
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
#  RUTAS OWNER — CÓDIGOS DE DESCUENTO
# ──══════════════════════════════════════════════════════════════

@app.route("/api/discount_codes", methods=["GET"])
@require_owner
def list_discount_codes():
    db = _ensure_keys(_load_db())
    return jsonify({"codes": db["discount_codes"]})


@app.route("/api/discount_codes/create", methods=["POST"])
@require_owner
def create_discount_code():
    """
    Body: {
        code        : str   (ej. "VERANO25"),
        discount    : float (porcentaje, ej. 25.0),
        max_uses    : int   (0 = ilimitado),
        expires_at  : str   (ISO date "2025-12-31", vacío = sin expiración),
        plans       : list  (["basic","pro","lifetime"] — vacío = todos),
        description : str   (nota interna)
    }
    """
    data        = request.get_json(silent=True) or {}
    code        = (data.get("code") or "").strip().upper()
    discount    = float(data.get("discount", 0))
    max_uses    = int(data.get("max_uses", 0))
    expires_at  = (data.get("expires_at") or "").strip()
    plans       = data.get("plans") or []
    description = (data.get("description") or "").strip()

    if not code:
        return jsonify({"error": "El código no puede estar vacío."}), 400
    if not (0 < discount <= 100):
        return jsonify({"error": "El descuento debe estar entre 1 y 100."}), 400

    db = _ensure_keys(_load_db())
    if code in db["discount_codes"]:
        return jsonify({"error": f"El código '{code}' ya existe."}), 400

    db["discount_codes"][code] = {
        "discount":    discount,
        "max_uses":    max_uses,
        "uses":        0,
        "expires_at":  expires_at,
        "plans":       [p.lower() for p in plans],
        "description": description,
        "active":      True,
        "created_at":  datetime.utcnow().isoformat(),
    }
    _save_db(db)
    return jsonify({"ok": True, "code": code})


@app.route("/api/discount_codes/delete", methods=["POST"])
@require_owner
def delete_discount_code():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    db   = _ensure_keys(_load_db())
    if code not in db["discount_codes"]:
        return jsonify({"error": "Código no encontrado."}), 404
    del db["discount_codes"][code]
    _save_db(db)
    return jsonify({"ok": True})


@app.route("/api/discount_codes/toggle", methods=["POST"])
@require_owner
def toggle_discount_code():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    db   = _ensure_keys(_load_db())
    if code not in db["discount_codes"]:
        return jsonify({"error": "Código no encontrado."}), 404
    db["discount_codes"][code]["active"] = not db["discount_codes"][code].get("active", True)
    _save_db(db)
    return jsonify({"ok": True, "active": db["discount_codes"][code]["active"]})


# ── Ruta PÚBLICA: validar un código desde el frontend (no consume uso) ──
@app.route("/api/discount_codes/validate", methods=["POST"])
def validate_discount_code():
    """Body: { code: str, plan: str }"""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    plan = (data.get("plan") or "").strip().lower()

    if not code:
        return jsonify({"valid": False, "message": "Código vacío."}), 400

    db    = _ensure_keys(_load_db())
    entry = db["discount_codes"].get(code)

    if not entry:
        return jsonify({"valid": False, "message": "Código no válido."})
    if not entry.get("active", True):
        return jsonify({"valid": False, "message": "Este código está desactivado."})
    if entry["max_uses"] > 0 and entry["uses"] >= entry["max_uses"]:
        return jsonify({"valid": False, "message": "Este código ha alcanzado el límite de usos."})
    if entry.get("expires_at"):
        try:
            if date.fromisoformat(entry["expires_at"]) < date.today():
                return jsonify({"valid": False, "message": "Este código ha expirado."})
        except Exception:
            pass
    if entry.get("plans") and plan and plan not in entry["plans"]:
        return jsonify({"valid": False, "message": f"Código no válido para el plan '{plan}'."})

    return jsonify({
        "valid":    True,
        "discount": entry["discount"],
        "message":  f"✓ {entry['discount']}% de descuento aplicado.",
    })


# ──══════════════════════════════════════════════════════════════
#  EMAIL — Envío de clave al comprador
# ──══════════════════════════════════════════════════════════════

# Variables de entorno para Gmail SMTP:
#   MAIL_USER  → tu cuenta Gmail  (ej: casttweaks@gmail.com)
#   MAIL_PASS  → contraseña de aplicación de Google (16 chars)
#   MAIL_FROM  → remitente visible (opcional, default=MAIL_USER)

def _send_license_email(
    to_email: str,
    username: str,
    key: str,
    plan_name: str,
    expires: str,
    is_free: bool = False,
):
    """Envía la clave de licencia al comprador por email. Falla silenciosamente."""
    import smtplib, ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text      import MIMEText

    mail_user = os.environ.get("MAIL_USER", "")
    mail_pass = os.environ.get("MAIL_PASS", "")
    if not mail_user or not mail_pass:
        return  # no configurado → skip silencioso

    mail_from = os.environ.get("MAIL_FROM", mail_user)

    duracion = "∞ Lifetime" if expires == "9999-12-31" or int(expires[:4]) > 2090 else expires
    tipo_compra = "regalo" if is_free else "compra"

    html_body = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#07000f;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#07000f;padding:40px 0">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#120028;border:1px solid #2a0055;border-radius:20px;overflow:hidden;max-width:560px;width:100%">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#9b30ff,#e040fb);padding:32px 40px;text-align:center">
            <p style="margin:0;font-size:28px;font-weight:900;letter-spacing:4px;color:#fff;text-transform:uppercase">CASTTWEAKS®</p>
            <p style="margin:8px 0 0;font-size:13px;color:rgba(255,255,255,.8);letter-spacing:2px;text-transform:uppercase">Optimización Premium para tu PC</p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 40px">
            <p style="margin:0 0 8px;font-size:22px;font-weight:700;color:#f0e8ff">Hola, {username} 👋</p>
            <p style="margin:0 0 28px;font-size:15px;color:#9980bb;line-height:1.7">
              ¡Gracias por tu {tipo_compra}! Tu licencia <strong style="color:#e040fb">{plan_name}</strong> ya está lista.<br>
              Aquí tienes tu clave de activación:
            </p>

            <!-- Key box -->
            <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(155,48,255,.1);border:1px solid rgba(155,48,255,.4);border-radius:12px;margin-bottom:28px">
              <tr>
                <td style="padding:20px 24px">
                  <p style="margin:0 0 6px;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#9980bb">Tu clave de licencia</p>
                  <p style="margin:0;font-size:13px;font-family:'Courier New',monospace;color:#e040fb;word-break:break-all;font-weight:700;letter-spacing:1px">{key}</p>
                </td>
              </tr>
            </table>

            <!-- Details -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px">
              <tr>
                <td style="padding:10px 0;border-bottom:1px solid #2a0055;font-size:13px;color:#9980bb">Plan</td>
                <td style="padding:10px 0;border-bottom:1px solid #2a0055;font-size:13px;color:#f0e8ff;text-align:right;font-weight:600">{plan_name}</td>
              </tr>
              <tr>
                <td style="padding:10px 0;font-size:13px;color:#9980bb">Válido hasta</td>
                <td style="padding:10px 0;font-size:13px;color:#f0e8ff;text-align:right;font-weight:600">{duracion}</td>
              </tr>
            </table>

            <p style="margin:0 0 28px;font-size:14px;color:#9980bb;line-height:1.7">
              Guarda esta clave en un lugar seguro. Si tienes cualquier problema con la activación, escríbenos y te ayudamos enseguida.
            </p>

            <!-- CTA -->
            <table cellpadding="0" cellspacing="0" style="margin-bottom:32px">
              <tr>
                <td style="background:linear-gradient(135deg,#9b30ff,#e040fb);border-radius:10px;padding:14px 28px">
                  <a href="mailto:casttweaks@gmail.com" style="color:#fff;text-decoration:none;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase">Contactar soporte</a>
                </td>
              </tr>
            </table>

            <p style="margin:0;font-size:13px;color:#9980bb;line-height:1.7">
              Un saludo,<br>
              <strong style="color:#e040fb">El equipo de CastTweaks®</strong>
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#0d0020;padding:20px 40px;border-top:1px solid #2a0055;text-align:center">
            <p style="margin:0;font-size:11px;color:#4a3366;letter-spacing:1px">© {datetime.utcnow().year} CastTweaks® · Todos los derechos reservados</p>
            <p style="margin:6px 0 0;font-size:11px;color:#4a3366">casttweaks@gmail.com</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎮 Tu licencia CastTweaks® {plan_name} — Clave de activación"
    msg["From"]    = f"CastTweaks® <{mail_from}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
            srv.login(mail_user, mail_pass)
            srv.sendmail(mail_from, to_email, msg.as_string())
    except Exception as e:
        # Log pero no interrumpir el flujo principal
        print(f"[MAIL ERROR] {e}", flush=True)


# ──══════════════════════════════════════════════════════════════
#  RUTA PÚBLICA — Emitir licencia gratuita con código 100% dto
# ──══════════════════════════════════════════════════════════════

@app.route("/api/issue_free", methods=["POST"])
def issue_free():
    """
    Emite una licencia cuando el código de descuento deja el precio en €0.

    Body: {
        username      : str,
        email         : str,
        days          : int,
        license_type  : "Basic" | "Pro" | "Lifetime",
        max_devices   : int,
        plan          : str,
        discount_code : str   ← OBLIGATORIO y debe valer 100%
    }
    """
    ip   = _get_ip()
    data = request.get_json(silent=True) or {}

    username      = (data.get("username")      or "").strip()
    email         = (data.get("email")         or "").strip()
    days          = int(data.get("days", 30))
    license_type  = (data.get("license_type")  or "Basic").strip()
    discount_code = (data.get("discount_code") or "").strip().upper()

    # ── Validaciones básicas ────────────────────────────────────
    if not username:
        return jsonify({"error": "username requerido"}), 400
    if not email:
        return jsonify({"error": "email requerido"}), 400
    if license_type not in LICENSE_TYPES:
        return jsonify({"error": "Tipo de licencia inválido"}), 400
    if days <= 0 or days > 36500:
        return jsonify({"error": "días inválidos"}), 400
    if not discount_code:
        return jsonify({"error": "Se requiere un código de descuento del 100%."}), 400

    # ── Rate limiting ────────────────────────────────────────────
    if _is_rate_limited(ip):
        return jsonify({"error": "Demasiadas peticiones. Espera un momento."}), 429

    db = _ensure_keys(_load_db())

    # ── Modo mantenimiento ──────────────────────────────────────
    if db["settings"].get("maintenance"):
        msg = db["settings"].get("maintenance_msg", "Servicio en mantenimiento.")
        return jsonify({"error": f"🔧 {msg}"}), 503

    # ── Validar que el código exista, esté activo y sea del 100% ─
    dc = db["discount_codes"].get(discount_code)
    if not dc:
        return jsonify({"error": "Código de descuento no válido."}), 400
    if not dc.get("active", True):
        return jsonify({"error": "Este código está desactivado."}), 400
    if dc["max_uses"] > 0 and dc["uses"] >= dc["max_uses"]:
        return jsonify({"error": "Este código ha alcanzado el límite de usos."}), 400
    if dc.get("expires_at"):
        try:
            if date.fromisoformat(dc["expires_at"]) < date.today():
                return jsonify({"error": "Este código ha expirado."}), 400
        except Exception:
            pass
    if dc.get("plans") and license_type.lower() not in dc["plans"]:
        return jsonify({"error": f"Código no válido para el plan '{license_type}'."}), 400

    # ── SEGURIDAD: solo emitir si el descuento es realmente 100% ─
    if int(dc["discount"]) != 100:
        return jsonify({"error": "Este código no cubre el precio completo."}), 400

    # ── Emitir licencia ──────────────────────────────────────────
    # Consumir uso del código
    db["discount_codes"][discount_code]["uses"] += 1

    max_devices = _MAX_DEVICES.get(license_type, 1)
    key         = generate_license(username, days, "")
    exp         = (date.today() + timedelta(days=days)).isoformat()

    db["licenses"][key] = {
        "username":      username,
        "expires":       exp,
        "note":          f"Clave gratuita · email:{email} · Dto:{discount_code}(100%)",
        "license_type":  license_type,
        "max_devices":   max_devices,
        "bound_devices": [],
        "issued_at":     datetime.utcnow().isoformat(),
        "revoked":       False,
        "revoke_reason": "",
        "uses":          0,
        "last_seen":     "",
        "last_ip":       ip,
        "first_use":     "",
        "email":         email,
        "paypal_order":  "FREE",
    }
    _save_db(db)

    # ── Enviar email de confirmación ──────────────────────────────
    _send_license_email(
        to_email  = email,
        username  = username,
        key       = key,
        plan_name = license_type,
        expires   = exp,
        is_free   = True,
    )

    return jsonify({
        "key":          key,
        "username":     username,
        "expires":      exp,
        "license_type": license_type,
    })


# ──══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ──══════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def index():
    """Sirve la landing page."""
    import os
    from flask import send_from_directory
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


# ──══════════════════════════════════════════════════════════════
#  RUTA PÚBLICA — Emitir licencia tras pago PayPal verificado
# ──══════════════════════════════════════════════════════════════

# IDs de pedidos PayPal ya procesados (anti-replay en memoria)
_used_orders: set = set()

# Precio mínimo esperado por plan y duración (validación anti-manipulación)
_PLAN_BASE   = {"Basic": 5.0, "Pro": 10.0, "Lifetime": 15.0}
_PLAN_XPM    = {"Basic": 1.0, "Pro": 1.5,  "Lifetime": 0.0}
_MAX_DEVICES = {"Basic": 1,   "Pro": 2,     "Lifetime": 3}


def _expected_price(license_type: str, days: int) -> float:
    base = _PLAN_BASE.get(license_type, 5.0)
    xpm  = _PLAN_XPM.get(license_type, 1.0)
    if license_type == "Lifetime":
        return base
    extra_months = max(0, (days - 30) // 30)
    return round(base + extra_months * xpm, 2)


@app.route("/api/issue_public", methods=["POST"])
def issue_public():
    """
    Emite una licencia tras un pago PayPal verificado.

    Body: {
        username       : str,
        email          : str,
        days           : int,
        license_type   : "Basic" | "Pro" | "Lifetime",
        max_devices    : int,
        paypal_order_id: str,
        plan           : str   (básicamente el mismo que license_type en minúscula)
    }

    ⚠ IMPORTANTE: Este endpoint verifica el pedido con la API de PayPal.
       Debes añadir la variable de entorno PAYPAL_CLIENT_ID y PAYPAL_SECRET.
    """
    import requests as _req

    ip   = _get_ip()
    data = request.get_json(silent=True) or {}

    username     = (data.get("username") or "").strip()
    email        = (data.get("email") or "").strip()
    days         = int(data.get("days", 30))
    license_type = (data.get("license_type") or "Basic").strip()
    max_devices   = int(data.get("max_devices", 1))
    order_id      = (data.get("paypal_order_id") or "").strip()
    discount_code = (data.get("discount_code") or "").strip().upper()

    # ── Validaciones básicas ────────────────────────────────────
    if not username:
        return jsonify({"error": "username requerido"}), 400
    if not order_id:
        return jsonify({"error": "paypal_order_id requerido"}), 400
    if license_type not in LICENSE_TYPES:
        return jsonify({"error": "Tipo de licencia inválido"}), 400
    if days <= 0 or days > 36500:
        return jsonify({"error": "días inválidos"}), 400

    # ── Anti-replay: el mismo pedido no puede usarse dos veces ──
    if order_id in _used_orders:
        return jsonify({"error": "Este pedido ya fue procesado."}), 400

    # ── Rate limiting ────────────────────────────────────────────
    if _is_rate_limited(ip):
        return jsonify({"error": "Demasiadas peticiones. Espera un momento."}), 429

    # ── Cargar DB y validar código de descuento ──────────────────
    db               = _ensure_keys(_load_db())
    applied_discount = 0.0
    valid_code       = None

    if discount_code:
        dc = db["discount_codes"].get(discount_code)
        if dc and dc.get("active", True):
            plan_ok = not dc.get("plans") or license_type.lower() in dc["plans"]
            uses_ok = dc["max_uses"] == 0 or dc["uses"] < dc["max_uses"]
            exp_ok  = True
            if dc.get("expires_at"):
                try: exp_ok = date.fromisoformat(dc["expires_at"]) >= date.today()
                except Exception: pass
            if plan_ok and uses_ok and exp_ok:
                applied_discount = dc["discount"]
                valid_code       = discount_code

    # ── Verificación del pago con PayPal ─────────────────────────
    paypal_client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
    paypal_secret    = os.environ.get("PAYPAL_SECRET", "")

    if paypal_client_id and paypal_secret:
        try:
            # 1. Obtener token de acceso
            token_resp = _req.post(
                "https://api-m.paypal.com/v1/oauth2/token",
                auth=(paypal_client_id, paypal_secret),
                data={"grant_type": "client_credentials"},
                timeout=10,
            )
            access_token = token_resp.json().get("access_token", "")

            # 2. Consultar el pedido
            order_resp = _req.get(
                f"https://api-m.paypal.com/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            order_data  = order_resp.json()
            order_status = order_data.get("status", "")

            if order_status != "COMPLETED":
                return jsonify({"error": f"Pago no completado (estado: {order_status})."}), 402

            # 3. Verificar importe
            paid_str = (
                order_data.get("purchase_units", [{}])[0]
                .get("payments", {})
                .get("captures", [{}])[0]
                .get("amount", {})
                .get("value", "0")
            )
            paid       = float(paid_str)
            base_price = _expected_price(license_type, days)
            expected   = round(base_price * (1 - applied_discount / 100), 2)

            if paid < expected - 0.01:
                return jsonify({"error": f"Importe insuficiente (recibido €{paid:.2f}, esperado €{expected:.2f})."}), 402

        except Exception as e:
            # Si no podemos verificar, rechazamos por seguridad
            return jsonify({"error": f"No se pudo verificar el pago con PayPal: {str(e)}"}), 500
    else:
        # Sin credenciales de PayPal configuradas → modo desarrollo (no usar en producción)
        pass

    # ── Emitir licencia ──────────────────────────────────────────
    _used_orders.add(order_id)

    # Consumir uso del código de descuento
    if valid_code and valid_code in db["discount_codes"]:
        db["discount_codes"][valid_code]["uses"] += 1

    max_devices   = _MAX_DEVICES.get(license_type, 1)
    key           = generate_license(username, days, "")
    exp           = (date.today() + timedelta(days=days)).isoformat()
    note_discount = f" · Dto:{valid_code}({applied_discount}%)" if valid_code else ""

    db["licenses"][key] = {
        "username":      username,
        "expires":       exp,
        "note":          f"Compra web · email:{email} · PayPal:{order_id[:16]}{note_discount}",
        "license_type":  license_type,
        "max_devices":   max_devices,
        "bound_devices": [],
        "issued_at":     datetime.utcnow().isoformat(),
        "revoked":       False,
        "revoke_reason": "",
        "uses":          0,
        "last_seen":     "",
        "last_ip":       ip,
        "first_use":     "",
        "email":         email,
        "paypal_order":  order_id,
    }
    _save_db(db)

    # ── Enviar email de confirmación ──────────────────────────────
    _send_license_email(
        to_email  = email,
        username  = username,
        key       = key,
        plan_name = {"basic":"Basic","pro":"Pro","lifetime":"Lifetime"}.get(data.get("plan","").lower(), license_type),
        expires   = exp,
        is_free   = False,
    )

    return jsonify({
        "key":          key,
        "username":     username,
        "expires":      exp,
        "license_type": license_type,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)

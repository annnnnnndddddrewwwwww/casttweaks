"""
CTadvanced - License Server v4.1 - CASTTWEAKS(R)
Backend Flask para Vercel (Serverless)

BASE DE DATOS: Supabase (PostgreSQL)

Variables de entorno requeridas en Vercel:
  OWNER_SECRET  -> mismo valor que en el cliente
  OWNER_API_KEY -> clave secreta para rutas de owner
  SUPABASE_URL  -> https://<project>.supabase.co
  SUPABASE_KEY  -> service_role key (no anon key)
  MAIL_USER     -> cuenta Gmail remitente
  MAIL_PASS     -> contrasena de aplicacion de Google

CAMBIOS v4.1 (Vercel / Stateless):
  - Sin estado en memoria: _hwid_ban, _hwid_fail_log,
    _rate_limit eliminados -> todo persiste en Supabase
  - hwid_temp_bans y rate_limit_log usan SOLO Supabase
  - _load_temp_bans_from_db() eliminado (sin arranque global)
  - threading.Thread para escrituras asincronas eliminado
    (Vercel corta el proceso tras la respuesta HTTP)
    -> escrituras criticas son sincronas
"""

import os, json, hmac, hashlib, base64, time, secrets, sys
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, Response, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

# ==================================================================
# VALIDACION DE VARIABLES DE ENTORNO CRITICAS
# ==================================================================

_REQUIRED_ENV_VARS = [
    "OWNER_SECRET",
    "OWNER_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "MAIL_USER",
    "MAIL_PASS",
]

def _validate_env():
    missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print(
            f"[STARTUP ERROR] Faltan variables de entorno: {', '.join(missing)}",
            flush=True,
        )
        sys.exit(1)

_validate_env()

# -- Carga de secretos -----------------------------------------------

OWNER_SECRET = os.environ["OWNER_SECRET"]
OWNER_API_KEY = os.environ["OWNER_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
PAYPAL_CURRENCY = os.environ.get("PAYPAL_CURRENCY", "EUR").upper()
MIN_CLIENT_VERSION = os.environ.get("MIN_CLIENT_VERSION", "1.0.0")
UPDATE_URL = os.environ.get("UPDATE_URL", "https://drive.google.com/uc?export=download")

# ==================================================================
# INICIALIZACION DE LA APP
# ==================================================================

app = Flask(__name__, static_folder="../public", static_url_path="/")
app.config["DEBUG"] = False
app.config["PROPAGATE_EXCEPTIONS"] = False
app.config["TRAP_HTTP_EXCEPTIONS"] = False
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# ==================================================================
# MANEJADORES DE ERROR GLOBALES
# ==================================================================

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    import traceback
    print(f"[UNHANDLED ERROR] {type(e).__name__}: {e}", flush=True)
    print(traceback.format_exc(), flush=True)
    return jsonify({"error": "Error interno del servidor. Contacta al soporte."}), 500

@app.errorhandler(400)
def handle_400(e): return jsonify({"error": "Peticion incorrecta."}), 400
@app.errorhandler(401)
def handle_401(e): return jsonify({"error": "No autorizado."}), 401
@app.errorhandler(403)
def handle_403(e): return jsonify({"error": "Acceso denegado."}), 403
@app.errorhandler(404)
def handle_404(e): return jsonify({"error": "Recurso no encontrado."}), 404
@app.errorhandler(405)
def handle_405(e): return jsonify({"error": "Metodo no permitido."}), 405
@app.errorhandler(429)
def handle_429(e): return jsonify({"error": "Demasiadas peticiones. Espera un momento."}), 429
@app.errorhandler(500)
def handle_500(e): return jsonify({"error": "Error interno del servidor. Contacta al soporte."}), 500

# -- Proxy/VPN block -------------------------------------------------
# Solo cabeceras que indican un proxy autenticado real.
# Se eliminaron "Proxy-Connection" y "X-ProxyUser-Ip" porque generan
# falsos positivos: infraestructuras CDN/Vercel y algunos clientes HTTP
# las inyectan aunque el usuario no tenga VPN ni proxy activo.

_PROXY_HEADERS = {
    "Proxy-Authenticate",
    "Proxy-Authorization",
}

def block_proxy(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        for header in _PROXY_HEADERS:
            val = request.headers.get(header)
            if val:
                ip = _get_ip()
                print(f"[PROXY BLOCK] IP={ip} header={header} value={val!r}", flush=True)
                return jsonify({
                    "error": "Conexion a traves de proxy o VPN detectada. "
                             "Desactiva tu VPN/proxy e intenta de nuevo."
                }), 403
        return f(*args, **kwargs)
    return decorated

# ==================================================================
# SUPABASE - CAPA DE ACCESO A DATOS
# ==================================================================

import requests as _http

_SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# -- Helpers genericos PostgREST -------------------------------------

def _sb_get(table: str, filters: dict = None, single: bool = False):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {}
    if filters:
        for k, v in filters.items():
            params[k] = f"eq.{v}"
    headers = {**_SB_HEADERS, "Accept": "application/vnd.pgrst.object+json"} if single else _SB_HEADERS
    try:
        r = _http.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 406:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SUPABASE GET] {table} {e}", flush=True)
        return None if single else []

def _sb_upsert(table: str, data: dict, on_conflict: str = "key"):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {**_SB_HEADERS, "Prefer": f"resolution=merge-duplicates,return=representation"}
    try:
        r = _http.post(url, headers=headers, json=data, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SUPABASE UPSERT] {table} {e}", flush=True)
        return None

def _sb_update(table: str, filters: dict, data: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {k: f"eq.{v}" for k, v in filters.items()}
    try:
        r = _http.patch(url, headers=_SB_HEADERS, params=params, json=data, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[SUPABASE UPDATE] {table} {e}", flush=True)
        return False

def _sb_delete(table: str, filters: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {k: f"eq.{v}" for k, v in filters.items()}
    try:
        r = _http.delete(url, headers=_SB_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[SUPABASE DELETE] {table} {e}", flush=True)
        return False

def _sb_insert(table: str, data: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        r = _http.post(url, headers=_SB_HEADERS, json=data, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SUPABASE INSERT] {table} {e}", flush=True)
        return None

# ==================================================================
# CAPA DE DOMINIO
# ==================================================================

# -- LICENSES -------------------------------------------------------

def db_license_get(key: str) -> dict | None:
    return _sb_get("licenses", {"key": key}, single=True)

def db_license_upsert(key: str, data: dict):
    data["key"] = key
    _sb_upsert("licenses", data, on_conflict="key")

def db_license_update(key: str, data: dict):
    _sb_update("licenses", {"key": key}, data)

def db_license_delete(key: str):
    _sb_delete("licenses", {"key": key})

def db_licenses_all() -> dict:
    rows = _sb_get("licenses") or []
    return {r["key"]: r for r in rows}

# -- HWID BLACKLIST -------------------------------------------------

def db_hwid_blacklisted(hwid: str) -> dict | None:
    return _sb_get("hwid_blacklist", {"hwid": hwid}, single=True)

def db_hwid_blacklist_add(hwid: str, reason: str):
    _sb_upsert("hwid_blacklist", {
        "hwid": hwid, "reason": reason,
        "added_at": datetime.utcnow().isoformat(),
    }, on_conflict="hwid")

def db_hwid_blacklist_remove(hwid: str):
    _sb_delete("hwid_blacklist", {"hwid": hwid})

def db_hwid_blacklist_all() -> dict:
    rows = _sb_get("hwid_blacklist") or []
    return {r["hwid"]: r for r in rows}

# -- HWID TEMP BANS - 100% Supabase (sin memoria) -------------------

HWID_FAIL_WINDOW = 600
HWID_FAIL_MAX = 3
HWID_BAN_DURATION = 3600

def _hwid_is_banned(hwid: str) -> tuple[bool, int]:
    if not hwid:
        return False, 0
    row = _sb_get("hwid_temp_bans", {"hwid": hwid}, single=True)
    if not row:
        return False, 0
    try:
        expires = float(row["expires"])
        remaining = int(expires - time.time())
    except (TypeError, ValueError):
        return False, 0
    if remaining <= 0:
        _sb_delete("hwid_temp_bans", {"hwid": hwid})
        return False, 0
    return True, remaining

def _hwid_record_fail(hwid: str) -> bool:
    if not hwid:
        return False
    now = time.time()
    window_start = now - HWID_FAIL_WINDOW

    _sb_insert("hwid_fail_log", {"hwid": hwid, "ts": now})

    url = f"{SUPABASE_URL}/rest/v1/hwid_fail_log"
    params = {"hwid": f"eq.{hwid}", "ts": f"gte.{window_start}", "select": "id"}
    try:
        r = _http.get(url, headers=_SB_HEADERS, params=params, timeout=5)
        r.raise_for_status()
        count = len(r.json())
    except Exception:
        count = 0

    if count >= HWID_FAIL_MAX:
        ban_expires = now + HWID_BAN_DURATION
        _sb_upsert("hwid_temp_bans", {"hwid": hwid, "expires": ban_expires}, on_conflict="hwid")
        _sb_delete("hwid_fail_log", {"hwid": hwid})
        return True
    return False

def _hwid_clear_fails(hwid: str):
    if hwid:
        _sb_delete("hwid_fail_log", {"hwid": hwid})

# -- RATE LIMIT - 100% Supabase -------------------------------------

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10

def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    _sb_insert("rate_limit_log", {"ip": ip, "ts": now})

    url = f"{SUPABASE_URL}/rest/v1/rate_limit_log"
    params = {"ip": f"eq.{ip}", "ts": f"gte.{window_start}", "select": "id"}
    try:
        r = _http.get(url, headers=_SB_HEADERS, params=params, timeout=5)
        r.raise_for_status()
        count = len(r.json())
    except Exception:
        return False

    return count > RATE_LIMIT_MAX

# -- FAILED LOG -----------------------------------------------------

def db_log_failed(ip: str, key_fragment: str, reason: str):
    _sb_insert("failed_log", {
        "ts": datetime.utcnow().isoformat(),
        "ip": ip,
        "key_fragment": (key_fragment or "")[:20],
        "reason": reason,
    })
    try:
        _http.post(
            f"{SUPABASE_URL}/rest/v1/rpc/trim_failed_log",
            headers=_SB_HEADERS,
            json={"max_rows": 500},
            timeout=5,
        )
    except Exception:
        pass

def db_failed_log_all() -> list:
    url = f"{SUPABASE_URL}/rest/v1/failed_log"
    params = {"order": "ts.desc", "limit": "500"}
    try:
        r = _http.get(url, headers=_SB_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SUPABASE] failed_log_all: {e}", flush=True)
        return []

def db_failed_log_clear():
    try:
        _http.post(
            f"{SUPABASE_URL}/rest/v1/rpc/truncate_failed_log",
            headers=_SB_HEADERS, timeout=5,
        )
    except Exception as e:
        print(f"[SUPABASE] failed_log_clear: {e}", flush=True)

# -- DISCOUNT CODES -------------------------------------------------

def db_discount_get(code: str) -> dict | None:
    return _sb_get("discount_codes", {"code": code}, single=True)

def db_discount_upsert(code: str, data: dict):
    data["code"] = code
    _sb_upsert("discount_codes", data, on_conflict="code")

def db_discount_delete(code: str):
    _sb_delete("discount_codes", {"code": code})

def db_discounts_all() -> dict:
    rows = _sb_get("discount_codes") or []
    return {r["code"]: r for r in rows}

def db_discount_increment_uses(code: str):
    try:
        _http.post(
            f"{SUPABASE_URL}/rest/v1/rpc/increment_discount_uses",
            headers=_SB_HEADERS,
            json={"p_code": code},
            timeout=5,
        )
    except Exception as e:
        print(f"[SUPABASE] increment_discount_uses: {e}", flush=True)

# -- PROCESSED ORDERS -----------------------------------------------

def db_order_exists(order_id: str) -> bool:
    row = _sb_get("processed_orders", {"order_id": order_id}, single=True)
    return row is not None

def db_order_insert(order_id: str, username: str, ip: str, license_type: str):
    _sb_upsert("processed_orders", {
        "order_id": order_id,
        "processed_at": datetime.utcnow().isoformat(),
        "username": username,
        "ip": ip,
        "license_type": license_type,
    }, on_conflict="order_id")

# -- HEARTBEATS -----------------------------------------------------

def db_heartbeat_upsert(key: str, hwid: str, ip: str):
    _sb_upsert("heartbeats", {
        "key": key,
        "hwid": hwid,
        "ip": ip,
        "ts": time.time(),
    }, on_conflict="key,hwid")

def db_heartbeats_for_key(key: str, window: int) -> list:
    cutoff = time.time() - window
    url = f"{SUPABASE_URL}/rest/v1/heartbeats"
    params = {"key": f"eq.{key}", "ts": f"gte.{cutoff}"}
    try:
        r = _http.get(url, headers=_SB_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SUPABASE] heartbeats_for_key: {e}", flush=True)
        return []

def db_heartbeat_delete_key(key: str):
    _sb_delete("heartbeats", {"key": key})

# -- SETTINGS -------------------------------------------------------

def db_settings_get() -> dict:
    rows = _sb_get("settings") or []
    s = {r["key"]: r["value"] for r in rows}
    s.setdefault("maintenance", False)
    s.setdefault("maintenance_msg", "El servicio esta en mantenimiento. Vuelve pronto.")
    s.setdefault("min_version", MIN_CLIENT_VERSION)
    s.setdefault("update_url", UPDATE_URL)
    return s

def db_settings_set(key: str, value):
    _sb_upsert("settings", {"key": key, "value": value}, on_conflict="key")

# -- AUDIT LOG ------------------------------------------------------

def _audit(
    action: str,
    result: str,
    ip: str = "",
    hwid: str = "",
    key_frag: str = "",
    detail: str = "",
    actor: str = "client",
):
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "action": action,
        "result": result,
        "ip": (ip or "")[:45],
        "hwid": (hwid or "")[:96],
        "key_frag": (key_frag or "")[:20],
        "detail": (detail or "")[:300],
        "actor": actor,
    }
    try:
        _sb_insert("audit_logs", entry)
    except Exception as exc:
        print(f"[AUDIT ERROR] {exc}", flush=True)

# ==================================================================
# CONFIGURACION / CONSTANTES
# ==================================================================

def _version_tuple(v: str) -> tuple:
    try:
        parts = [int(x) for x in str(v).strip().split(".")]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)

LICENSE_TYPES = ["Basic", "Pro", "Lifetime"]

# Mapa de normalización: acepta cualquier capitalización y devuelve el tipo canónico
_LICENSE_TYPE_NORMALIZE = {t.lower(): t for t in ["Basic", "Pro", "Lifetime"]}

def _normalize_license_type(raw: str) -> str:
    """Normaliza el tipo de licencia al valor canónico (Basic/Pro/Lifetime)
    sin importar la capitalización recibida del cliente."""
    if not raw:
        return "Basic"
    return _LICENSE_TYPE_NORMALIZE.get(raw.strip().lower(), "")
RESPONSE_TS_TOLERANCE = 30
REQUEST_TS_TOLERANCE = 120
HEARTBEAT_WINDOW = 360
HEARTBEAT_BAN_MSG = (
    "Account Sharing detectado: licencia usada desde multiples IPs simultaneamente."
)

_PLAN_BASE = {"Basic": 5.0, "Pro": 10.0, "Lifetime": 39.99}
_PLAN_XPM  = {"Basic": 2.0, "Pro": 3.5,  "Lifetime": 0.0}
_MAX_DEVICES = {"Basic": 1, "Pro": 3, "Lifetime": 5}

# ==================================================================
# CIFRADO DE RESPUESTAS
# ==================================================================

def _aes_key() -> bytes:
    return hashlib.sha256(OWNER_SECRET.encode()).digest()

def _aes_ctr_crypt(data: bytes, nonce: bytes) -> bytes:
    key = _aes_key()
    result = bytearray(len(data))
    block = 16
    for i in range(0, len(data), block):
        counter = (i // block).to_bytes(8, "big")
        stream = hashlib.sha256(key + nonce + counter).digest()
        chunk = data[i : i + block]
        for j, b in enumerate(chunk):
            result[i + j] = b ^ stream[j]
    return bytes(result)

def secure_response(payload: dict, status: int = 200):
    raw_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    nonce = secrets.token_bytes(16)
    ts = int(time.time())
    cipher = _aes_ctr_crypt(raw_json, nonce)
    nonce_hex = nonce.hex()
    cipher_b64 = base64.b64encode(cipher).decode()
    mac_input = f"{nonce_hex}:{ts}:{cipher_b64}".encode()
    signature = hmac.new(OWNER_SECRET.encode(), mac_input, hashlib.sha256).hexdigest()
    envelope = {"p": cipher_b64, "n": nonce_hex, "ts": ts, "s": signature}
    return Response(
        json.dumps(envelope, separators=(",", ":")),
        status=status,
        mimetype="application/json",
    )

# ==================================================================
# SANITIZACION / HELPERS
# ==================================================================

import re as _re

_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "\n")
_FORBIDDEN_CHARS = _re.compile(r'[\x00-\x1f\x7f|<>"`]')
_MAX_LEN = {
    "username": 48, "email": 120, "hwid": 96,
    "note": 200, "reason": 200, "generic": 128,
}

def _sanitize(value: str, field: str = "generic") -> str:
    if not isinstance(value, str):
        value = str(value)
    value = value[: _MAX_LEN.get(field, 128)]
    value = _FORBIDDEN_CHARS.sub("", value)
    if value.startswith(_FORMULA_TRIGGERS):
        value = "'" + value
    return value.strip()

def _sanitize_hwid(hwid: str) -> str:
    cleaned = _re.sub(r"[^A-Fa-f0-9-:]", "", hwid.upper())
    return cleaned[:_MAX_LEN["hwid"]]

def _sign(payload: str) -> str:
    return hmac.new(OWNER_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()

def _get_ip() -> str:
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )

def _check_replay(data: dict, use_secure: bool = True):
    ts_raw = data.get("ts")
    if ts_raw is None:
        err = {"valid": False, "error": "Falta campo 'ts' (timestamp anti-replay)."}
        return False, (secure_response(err, 400) if use_secure else (jsonify(err), 400))
    try:
        ts = int(ts_raw)
    except (TypeError, ValueError):
        err = {"valid": False, "error": "Campo 'ts' debe ser un entero Unix."}
        return False, (secure_response(err, 400) if use_secure else (jsonify(err), 400))
    drift = abs(time.time() - ts)
    if drift > REQUEST_TS_TOLERANCE:
        err = {
            "valid": False,
            "error": (
                f"Peticion rechazada: timestamp desviado {int(drift)}s "
                f"(maximo permitido: {REQUEST_TS_TOLERANCE}s). "
                "Sincroniza el reloj de tu sistema o evita reutilizar peticiones."
            ),
        }
        return False, (secure_response(err, 408) if use_secure else (jsonify(err), 408))
    return True, None

def _verify_request_hmac(data: dict, payload_fields: list) -> bool:
    client_sig = data.get("sig", "")
    if not client_sig:
        return False
    ts = str(data.get("ts", ""))
    parts = [ts] + [str(data.get(f, "")) for f in payload_fields]
    msg = ":".join(parts).encode()
    expected = hmac.new(OWNER_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(client_sig, expected)

# ==================================================================
# CRIPTOGRAFIA - LICENCIAS
# ==================================================================

def generate_license(username: str, days: int, hwid: str = "") -> str:
    exp = (date.today() + timedelta(days=days)).isoformat()
    payload = f"{username}|{exp}|{hwid}"
    sig = _sign(payload)
    raw = f"{payload}||{sig}"
    key = base64.b64encode(raw.encode()).decode().rstrip("=")
    return "-".join(key[i : i + 8] for i in range(0, len(key), 8))

def decode_key(key: str):
    try:
        raw = key.replace("-", "").replace(" ", "")
        pad = 4 - len(raw) % 4
        if pad != 4:
            raw += "=" * pad
        decoded = base64.b64decode(raw).decode()
        payload, sig = decoded.rsplit("||", 1)
        parts = payload.split("|")
        username, exp_str, hwid = parts[0], parts[1], parts[2]
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        return {"username": username, "expires": exp_str, "hwid": hwid}
    except Exception:
        return None

# ==================================================================
# DECORADORES
# ==================================================================

def require_owner(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-Owner-Key", "")
        if not hmac.compare_digest(api_key, OWNER_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def _expected_price(license_type: str, days: int) -> float:
    base = _PLAN_BASE.get(license_type, 5.0)
    xpm  = _PLAN_XPM.get(license_type, 1.0)
    if license_type == "Lifetime":
        return base
    extra_months = max(0, (days - 30) // 30)
    return round(base + extra_months * xpm, 2)

# ==================================================================
# EMAIL
# ==================================================================

def _send_license_email(to_email, username, key, plan_name, expires, is_free=False):
    import smtplib, ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    mail_user = os.environ.get("MAIL_USER", "")
    mail_pass = os.environ.get("MAIL_PASS", "")
    if not mail_user or not mail_pass:
        return

    mail_from = os.environ.get("MAIL_FROM", mail_user)
    duracion = "Lifetime" if expires and int(expires[:4]) > 2090 else expires
    year = datetime.utcnow().year
    download_url = os.environ.get("UPDATE_URL", "https://drive.google.com/uc?export=download")
    plan_color = {"Basic": "#7c3aed", "Pro": "#9b30ff", "Lifetime": "#e040fb"}.get(plan_name, "#7c3aed")
    plan_icon  = {"Basic": "&#9889;", "Pro": "&#128640;", "Lifetime": "&#9854;"}.get(plan_name, "&#9889;")

    html_body = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#07000f;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#07000f;padding:48px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;border-radius:16px;overflow:hidden;">
<tr>
  <td style="background:linear-gradient(135deg,#5b10c6 0%,#9b30ff 50%,#e040fb 100%);padding:36px 48px;text-align:center;">
    <p style="margin:0;font-size:11px;letter-spacing:6px;color:rgba(255,255,255,0.65);text-transform:uppercase;">CASTTWEAKS</p>
    <p style="margin:10px 0 0;font-size:38px;font-weight:900;letter-spacing:7px;color:#ffffff;">CTadvanced</p>
    <p style="margin:12px 0 0;font-size:12px;color:rgba(255,255,255,0.75);letter-spacing:3px;">LICENSE SERVER</p>
  </td>
</tr>
<tr><td style="background:#0f0022;padding:28px 48px 0;text-align:center;">
  <span style="display:inline-block;background:{plan_color}22;border:1px solid {plan_color};border-radius:20px;padding:6px 18px;font-size:13px;color:{plan_color};font-weight:600;">
    {plan_icon} &nbsp; Licencia {plan_name}
  </span>
</td></tr>
<tr><td style="background:#0f0022;padding:28px 48px 0;">
  <p style="margin:0 0 10px;font-size:24px;font-weight:700;color:#f5edff;">Hola, {username} &#128075;</p>
  <p style="margin:0;font-size:15px;color:#a08cc0;line-height:1.8;">
    {'Gracias por tu confianza!' if not is_free else 'Aqui tienes tu acceso gratuito!'}
    Tu licencia <strong style="color:#e040fb;">{plan_name}</strong> ya esta activa.
  </p>
</td></tr>
<tr><td style="background:#0f0022;padding:24px 48px 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {plan_color};border-radius:12px;overflow:hidden;">
    <tr><td style="padding:14px 24px 6px;"><p style="margin:0;font-size:10px;letter-spacing:4px;color:{plan_color};text-transform:uppercase;">Tu clave de licencia</p></td></tr>
    <tr><td style="padding:4px 24px 18px;"><p style="margin:0;font-size:14px;font-family:monospace;color:#ffffff;word-break:break-all;">{key}</p></td></tr>
    <tr><td style="background:{plan_color}18;padding:10px 24px;border-top:1px solid {plan_color}44;font-size:11px;color:{plan_color};">Copia y pega esta clave en la aplicacion.</td></tr>
  </table>
</td></tr>
<tr><td style="background:#0f0022;padding:20px 48px 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #1e0040;border-radius:12px;overflow:hidden;">
    <tr style="background:#160030;"><td colspan="2" style="padding:12px 20px;font-size:11px;letter-spacing:3px;color:#9b30ff;text-transform:uppercase;">Detalles del Plan</td></tr>
    <tr>
      <td style="padding:14px 20px;font-size:13px;color:#8a6aaa;border-bottom:1px solid #1e0040;">Plan</td>
      <td style="padding:14px 20px;font-size:13px;color:#f0e8ff;text-align:right;font-weight:600;border-bottom:1px solid #1e0040;">{plan_name}</td>
    </tr>
    <tr>
      <td style="padding:14px 20px;font-size:13px;color:#8a6aaa;">Valido hasta</td>
      <td style="padding:14px 20px;font-size:13px;color:#e040fb;text-align:right;font-weight:600;">{duracion}</td>
    </tr>
  </table>
</td></tr>
<tr><td style="background:#0f0022;padding:28px 48px 0;text-align:center;">
  <p style="margin:0 0 16px;font-size:13px;color:#8a6aaa;">Descarga el instalador desde el enlace oficial:</p>
  <table cellpadding="0" cellspacing="0" style="margin:0 auto;"><tr>
    <td style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:2px solid {plan_color};border-radius:12px;padding:14px 32px;">
      <a href="{download_url}" style="color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;">&#11015; &nbsp; Descargar CastTweaks.exe</a>
    </td>
  </tr></table>
</td></tr>
<tr><td style="background:#0f0022;padding:28px 48px 36px;">
  <p style="margin:28px 0 0;font-size:14px;color:#9980bb;line-height:1.8;">
    Un saludo,<br><strong style="color:#e040fb;font-size:15px;">El equipo de CastTweaks</strong>
  </p>
</td></tr>
<tr><td style="background:#080015;padding:20px 48px;border-top:1px solid #1e0040;text-align:center;">
  <p style="margin:0;font-size:11px;color:#3d2560;">&copy; {year} CastTweaks — Todos los derechos reservados.</p>
  <p style="margin:6px 0 0;font-size:11px;color:#3d2560;">casttweaks@gmail.com</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[CastTweaks] Tu licencia {plan_name} + Instalador"
    msg["From"] = f"CastTweaks <{mail_from}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
            srv.login(mail_user, mail_pass)
            srv.sendmail(mail_from, to_email, msg.as_string())
        print(f"[MAIL] Correo enviado a {to_email}", flush=True)
    except Exception as e:
        print(f"[MAIL ERROR] {e}", flush=True)

# ==================================================================
# RUTAS PUBLICAS
# ==================================================================

@app.route("/api/health", methods=["GET"])
def health():
    settings = db_settings_get()
    return jsonify({
        "status": "ok",
        "ts": datetime.utcnow().isoformat(),
        "maintenance": settings.get("maintenance", False),
        "storage": "supabase",
        "runtime": "vercel-serverless",
    })

@app.route("/api/verify", methods=["POST"])
@block_proxy
def verify():
    ip = _get_ip()
    data = request.get_json(silent=True) or {}

    ok, err = _check_replay(data, use_secure=True)
    if not ok:
        return err

    if not _verify_request_hmac(data, ["key", "hwid", "version"]):
        print(f"[ANTI-REPLAY] Firma invalida en /verify IP={ip}", flush=True)
        return secure_response(
            {"valid": False, "error": "Firma de peticion invalida o ausente (sig)."},
            401,
        )

    key     = (data.get("key")     or "").strip()
    hwid    = (data.get("hwid")    or "").strip()
    version = (data.get("version") or "0.0.0").strip()

    if _is_rate_limited(ip):
        return secure_response({"valid": False, "error": "Demasiados intentos. Espera un momento."})

    if hwid:
        hwid_up = hwid.upper()
        banned, secs_left = _hwid_is_banned(hwid_up)
        if banned:
            mins = (secs_left + 59) // 60
            return secure_response({
                "valid": False,
                "error": (
                    f"Demasiados intentos fallidos desde este PC. "
                    f"Bloqueado temporalmente durante {mins} minuto(s)."
                ),
                "retry_after": secs_left,
            }, 429)

    settings = db_settings_get()

    if settings.get("maintenance"):
        msg = settings.get("maintenance_msg", "Servicio en mantenimiento.")
        return secure_response({"valid": False, "error": f"[M] {msg}"})

    min_ver    = settings.get("min_version", MIN_CLIENT_VERSION)
    update_url = settings.get("update_url", UPDATE_URL)
    if _version_tuple(version) < _version_tuple(min_ver):
        return secure_response({
            "valid": False, "update": True,
            "min_version": min_ver, "update_url": update_url,
            "error": f"Version {version} no soportada. Actualiza a {min_ver} o superior.",
        }, 426)

    if not key:
        return secure_response({"valid": False, "error": "Clave vacia."}, 400)

    if hwid:
        bl = db_hwid_blacklisted(hwid.upper())
        if bl:
            reason = bl.get("reason", "PC bloqueado.")
            db_log_failed(ip, key, f"HWID bloqueado: {reason}")
            return secure_response({"valid": False, "error": f"Este ordenador ha sido bloqueado: {reason}"})

    decoded = decode_key(key)
    if not decoded:
        db_log_failed(ip, key, "Firma invalida")
        if hwid:
            _hwid_record_fail(hwid.upper())
        return secure_response({"valid": False, "error": "Firma invalida. Clave incorrecta o manipulada."})

    entry = db_license_get(key)
    if entry is None:
        db_log_failed(ip, key, "Clave no registrada")
        if hwid:
            _hwid_record_fail(hwid.upper())
        return secure_response({"valid": False, "error": "Clave no registrada. Contacta al owner."})

    if entry.get("revoked"):
        reason = entry.get("revoke_reason", "Sin motivo.")
        db_log_failed(ip, key, f"Revocada: {reason}")
        if hwid:
            _hwid_record_fail(hwid.upper())
        return secure_response({"valid": False, "error": f"Licencia revocada: {reason}"})

    try:
        exp_date  = date.fromisoformat(decoded["expires"])
        days_left = (exp_date - date.today()).days
        if days_left < 0:
            db_log_failed(ip, key, "Expirada")
            if hwid:
                _hwid_record_fail(hwid.upper())
            return secure_response({"valid": False, "error": f"Licencia expirada el {decoded['expires']}."})
    except Exception:
        return secure_response({"valid": False, "error": "Fecha de expiracion invalida."})

    max_devices  = entry.get("max_devices", 1)
    bound_devices = entry.get("bound_devices") or []
    hwid_in_key  = decoded.get("hwid", "")

    if hwid:
        if hwid_in_key:
            if hwid_in_key.upper() != hwid.upper():
                db_log_failed(ip, key, "HWID fijo no coincide")
                _hwid_record_fail(hwid.upper())
                return secure_response({"valid": False, "error": "Esta clave esta registrada para otro PC."})
        else:
            hwid_up  = hwid.upper()
            bound_up = [h.upper() for h in bound_devices]
            if hwid_up not in bound_up:
                if len(bound_devices) >= max_devices:
                    db_log_failed(ip, key, f"Limite {max_devices} dispositivos")
                    _hwid_record_fail(hwid_up)
                    return secure_response({
                        "valid": False,
                        "error": (
                            f"Esta clave ya esta activada en {max_devices} dispositivo(s). "
                            "Contacta al owner para cambiar de PC."
                        ),
                    })
                bound_devices.append(hwid)

    if hwid:
        _hwid_clear_fails(hwid.upper())

    update_data = {
        "bound_devices": bound_devices,
        "last_seen": datetime.utcnow().isoformat(),
        "last_ip": ip,
        "uses": (entry.get("uses") or 0) + 1,
    }
    if not entry.get("first_use"):
        update_data["first_use"] = datetime.utcnow().isoformat()
    db_license_update(key, update_data)

    return secure_response({
        "valid": True,
        "username": decoded["username"],
        "expires": decoded["expires"],
        "days_left": days_left,
        "license_type": _normalize_license_type(entry.get("license_type") or "Basic") or "Basic",
        "max_devices": max_devices,
    })

# ==================================================================
# RUTAS OWNER - LICENCIAS
# ==================================================================

@app.route("/api/issue", methods=["POST"])
@require_owner
def issue():
    data = request.get_json(silent=True) or {}
    username     = _sanitize((data.get("username") or "").strip(), "username")
    days         = int(data.get("days", 30))
    hwid         = _sanitize_hwid((data.get("hwid") or "").strip())
    note         = _sanitize((data.get("note") or "").strip(), "note")
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
    db_license_upsert(key, {
        "username": username,
        "expires": exp,
        "note": note,
        "license_type": license_type,
        "max_devices": max_devices,
        "bound_devices": [hwid] if hwid else [],
        "issued_at": datetime.utcnow().isoformat(),
        "revoked": False,
        "revoke_reason": "",
        "uses": 0,
        "last_seen": "",
        "last_ip": "",
        "first_use": "",
    })
    return jsonify({"key": key, "username": username, "expires": exp, "license_type": license_type})

@app.route("/api/revoke", methods=["POST"])
@require_owner
def revoke():
    data   = request.get_json(silent=True) or {}
    key    = (data.get("key") or "").strip()
    reason = _sanitize((data.get("reason") or "Revocada por el owner.").strip(), "reason")
    if not db_license_get(key):
        return jsonify({"error": "Clave no encontrada"}), 404
    db_license_update(key, {
        "revoked": True,
        "revoke_reason": reason,
        "revoked_at": datetime.utcnow().isoformat(),
    })
    return jsonify({"ok": True})

@app.route("/api/unrevoke", methods=["POST"])
@require_owner
def unrevoke():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    if not db_license_get(key):
        return jsonify({"error": "Clave no encontrada"}), 404
    db_license_update(key, {"revoked": False, "revoke_reason": ""})
    return jsonify({"ok": True})

@app.route("/api/licenses", methods=["GET"])
@require_owner
def list_licenses():
    return jsonify({"licenses": db_licenses_all()})

@app.route("/api/delete", methods=["POST"])
@require_owner
def delete_license():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    if not db_license_get(key):
        return jsonify({"error": "Clave no encontrada"}), 404
    db_license_delete(key)
    return jsonify({"ok": True})

@app.route("/api/reset_hwid", methods=["POST"])
@require_owner
def reset_hwid():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    if not db_license_get(key):
        return jsonify({"error": "Clave no encontrada"}), 404
    db_license_update(key, {"bound_devices": [], "first_use": ""})
    return jsonify({"ok": True})

@app.route("/api/edit_note", methods=["POST"])
@require_owner
def edit_note():
    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip()
    note = _sanitize((data.get("note") or "").strip(), "note")
    if not db_license_get(key):
        return jsonify({"error": "Clave no encontrada"}), 404
    db_license_update(key, {"note": note})
    return jsonify({"ok": True})

# ==================================================================
# RUTAS OWNER - HWID BANS TEMPORALES
# ==================================================================

@app.route("/api/hwid_bans", methods=["GET"])
@require_owner
def list_hwid_bans():
    now  = time.time()
    rows = _sb_get("hwid_temp_bans") or []
    bans = {}
    expired_hwids = []
    for r in rows:
        try:
            expires = float(r["expires"])
        except (TypeError, ValueError):
            continue
        remaining = int(expires - now)
        if remaining > 0:
            bans[r["hwid"]] = {
                "expires_at": datetime.utcfromtimestamp(expires).isoformat() + "Z",
                "secs_remaining": remaining,
            }
        else:
            expired_hwids.append(r["hwid"])
    for hwid in expired_hwids:
        _sb_delete("hwid_temp_bans", {"hwid": hwid})
    return jsonify({"hwid_bans": bans, "count": len(bans)})

@app.route("/api/hwid_bans/clear", methods=["POST"])
@require_owner
def clear_hwid_ban():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip().upper()
    if hwid:
        removed = _sb_get("hwid_temp_bans", {"hwid": hwid}, single=True) is not None
        _sb_delete("hwid_temp_bans", {"hwid": hwid})
        _sb_delete("hwid_fail_log",  {"hwid": hwid})
        return jsonify({"ok": True, "hwid": hwid, "was_banned": removed})
    else:
        try:
            _http.post(f"{SUPABASE_URL}/rest/v1/rpc/truncate_hwid_bans",    headers=_SB_HEADERS, timeout=5)
            _http.post(f"{SUPABASE_URL}/rest/v1/rpc/truncate_hwid_fail_log", headers=_SB_HEADERS, timeout=5)
        except Exception as e:
            print(f"[SUPABASE] clear_hwid_bans: {e}", flush=True)
        return jsonify({"ok": True, "cleared": "all"})

# ==================================================================
# RUTAS OWNER - BLACKLIST HWIDs
# ==================================================================

@app.route("/api/blacklist_hwid", methods=["POST"])
@require_owner
def blacklist_hwid():
    data   = request.get_json(silent=True) or {}
    hwid   = _sanitize_hwid((data.get("hwid") or "").strip())
    reason = _sanitize((data.get("reason") or "Bloqueado por el owner.").strip(), "reason")
    if not hwid:
        return jsonify({"error": "hwid requerido"}), 400
    db_hwid_blacklist_add(hwid, reason)
    return jsonify({"ok": True, "hwid": hwid})

@app.route("/api/unblacklist_hwid", methods=["POST"])
@require_owner
def unblacklist_hwid():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip().upper()
    db_hwid_blacklist_remove(hwid)
    return jsonify({"ok": True})

@app.route("/api/hwid_blacklist", methods=["GET"])
@require_owner
def get_hwid_blacklist():
    return jsonify({"blacklist": db_hwid_blacklist_all()})

# ==================================================================
# RUTAS OWNER - LOG Y CONFIGURACION
# ==================================================================

@app.route("/api/failed_log", methods=["GET"])
@require_owner
def get_failed_log():
    return jsonify({"log": db_failed_log_all()})

@app.route("/api/clear_failed_log", methods=["POST"])
@require_owner
def clear_failed_log():
    db_failed_log_clear()
    return jsonify({"ok": True})

@app.route("/api/maintenance", methods=["POST"])
@require_owner
def set_maintenance():
    data    = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    msg     = (data.get("message") or "El servicio esta en mantenimiento. Vuelve pronto.").strip()
    db_settings_set("maintenance", enabled)
    db_settings_set("maintenance_msg", msg)
    return jsonify({"ok": True, "maintenance": enabled})

@app.route("/api/settings", methods=["GET"])
@require_owner
def get_settings():
    return jsonify({"settings": db_settings_get()})

@app.route("/api/set_version", methods=["POST"])
@require_owner
def set_version():
    data    = request.get_json(silent=True) or {}
    new_ver = (data.get("min_version") or "").strip()
    new_url = (data.get("update_url")  or "").strip()
    if not new_ver:
        return jsonify({"error": "min_version requerido (ej: '2.0.0')."}), 400
    if _version_tuple(new_ver) == (0, 0, 0) and new_ver != "0.0.0":
        return jsonify({"error": f"Formato de version invalido: '{new_ver}'."}), 400
    db_settings_set("min_version", new_ver)
    if new_url:
        db_settings_set("update_url", new_url)
    s = db_settings_get()
    return jsonify({"ok": True, "min_version": s["min_version"], "update_url": s["update_url"]})

# ==================================================================
# RUTAS OWNER - CODIGOS DE DESCUENTO
# ==================================================================

@app.route("/api/discount_codes", methods=["GET"])
@require_owner
def list_discount_codes():
    return jsonify({"codes": db_discounts_all()})

@app.route("/api/discount_codes/create", methods=["POST"])
@require_owner
def create_discount_code():
    data        = request.get_json(silent=True) or {}
    code        = (data.get("code") or "").strip().upper()
    discount    = float(data.get("discount", 0))
    max_uses    = int(data.get("max_uses", 0))
    expires_at  = (data.get("expires_at") or "").strip()
    plans       = data.get("plans") or []
    description = (data.get("description") or "").strip()

    if not code:
        return jsonify({"error": "El codigo no puede estar vacio."}), 400
    if not (0 < discount <= 100):
        return jsonify({"error": "El descuento debe estar entre 1 y 100."}), 400
    if db_discount_get(code):
        return jsonify({"error": f"El codigo '{code}' ya existe."}), 400

    db_discount_upsert(code, {
        "discount": discount,
        "max_uses": max_uses,
        "uses": 0,
        "expires_at": expires_at or None,
        "plans": [p.lower() for p in plans],
        "description": description,
        "active": True,
        "created_at": datetime.utcnow().isoformat(),
    })
    return jsonify({"ok": True, "code": code})

@app.route("/api/discount_codes/delete", methods=["POST"])
@require_owner
def delete_discount_code():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    if not db_discount_get(code):
        return jsonify({"error": "Codigo no encontrado."}), 404
    db_discount_delete(code)
    return jsonify({"ok": True})

@app.route("/api/discount_codes/toggle", methods=["POST"])
@require_owner
def toggle_discount_code():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    dc   = db_discount_get(code)
    if not dc:
        return jsonify({"error": "Codigo no encontrado."}), 404
    new_state = not dc.get("active", True)
    db_discount_upsert(code, {**dc, "active": new_state})
    return jsonify({"ok": True, "active": new_state})

@app.route("/api/discount_codes/validate", methods=["POST"])
def validate_discount_code():
    data = request.get_json(silent=True) or {}

    code = (data.get("code") or "").strip().upper()
    plan = (data.get("plan") or "").strip().lower()

    if not code:
        return jsonify({"valid": False, "message": "Codigo vacio."}), 400

    entry = db_discount_get(code)
    if not entry:
        return jsonify({"valid": False, "message": "Codigo no valido."})
    if not entry.get("active", True):
        return jsonify({"valid": False, "message": "Este codigo esta desactivado."})
    if entry["max_uses"] > 0 and entry["uses"] >= entry["max_uses"]:
        return jsonify({"valid": False, "message": "Este codigo ha alcanzado el limite de usos."})
    if entry.get("expires_at"):
        try:
            if date.fromisoformat(entry["expires_at"]) < date.today():
                return jsonify({"valid": False, "message": "Este codigo ha expirado."})
        except Exception:
            pass
    if entry.get("plans") and plan and plan not in entry["plans"]:
        return jsonify({"valid": False, "message": f"Codigo no valido para el plan '{plan}'."})

    return jsonify({
        "valid": True,
        "discount": entry["discount"],
        "message": f"{entry['discount']}% de descuento aplicado.",
    })

# ==================================================================
# RUTA PUBLICA - Clave gratuita (descuento 100%)
# ==================================================================

@app.route("/api/issue_free", methods=["POST"])
@block_proxy
def issue_free():
    ip   = _get_ip()
    data = request.get_json(silent=True) or {}

    ok, err = _check_replay(data, use_secure=False)
    if not ok:
        resp, status = err
        return resp, status

    if not _verify_request_hmac(data, ["username", "email", "discount_code"]):
        return jsonify({"error": "Firma de peticion invalida (sig)."}), 401

    username      = _sanitize((data.get("username")      or "").strip(), "username")
    email         = _sanitize((data.get("email")         or "").strip(), "email")
    days          = int(data.get("days", 30))
    license_type  = _normalize_license_type(data.get("license_type") or "")
    discount_code = (data.get("discount_code") or "").strip().upper()

    if not username:
        return jsonify({"error": "username requerido"}), 400
    if not email:
        return jsonify({"error": "email requerido"}), 400
    if license_type not in LICENSE_TYPES:
        return jsonify({"error": "Tipo de licencia invalido"}), 400
    if days <= 0 or days > 36500:
        return jsonify({"error": "dias invalidos"}), 400
    if not discount_code:
        return jsonify({"error": "Se requiere un codigo de descuento del 100%."}), 400
    if _is_rate_limited(ip):
        return jsonify({"error": "Demasiadas peticiones. Espera un momento."}), 429

    settings = db_settings_get()
    if settings.get("maintenance"):
        msg = settings.get("maintenance_msg", "Servicio en mantenimiento.")
        return jsonify({"error": f"[M] {msg}"}), 503

    dc = db_discount_get(discount_code)
    if not dc:
        return jsonify({"error": "Codigo de descuento no valido."}), 400
    if not dc.get("active", True):
        return jsonify({"error": "Este codigo esta desactivado."}), 400
    if dc["max_uses"] > 0 and dc["uses"] >= dc["max_uses"]:
        return jsonify({"error": "Este codigo ha alcanzado el limite de usos."}), 400
    if dc.get("expires_at"):
        try:
            if date.fromisoformat(dc["expires_at"]) < date.today():
                return jsonify({"error": "Este codigo ha expirado."}), 400
        except Exception:
            pass
    if dc.get("plans") and license_type.lower() not in dc["plans"]:
        return jsonify({"error": f"Codigo no valido para el plan '{license_type}'."}), 400
    if int(dc["discount"]) != 100:
        return jsonify({"error": "Este codigo no cubre el precio completo."}), 400

    db_discount_increment_uses(discount_code)
    max_devices = _MAX_DEVICES.get(license_type, 1)
    key = generate_license(username, days, "")
    exp = (date.today() + timedelta(days=days)).isoformat()
    db_license_upsert(key, {
        "username": username,
        "expires": exp,
        "note": f"Clave gratuita - email:{email} - Dto:{discount_code}(100%)",
        "license_type": license_type,
        "max_devices": max_devices,
        "bound_devices": [],
        "issued_at": datetime.utcnow().isoformat(),
        "revoked": False,
        "revoke_reason": "",
        "uses": 0,
        "last_seen": "",
        "last_ip": ip,
        "first_use": "",
        "email": email,
        "paypal_order": "FREE",
    })
    _send_license_email(
        to_email=email, username=username, key=key,
        plan_name=license_type, expires=exp, is_free=True,
    )
    return jsonify({"key": key, "username": username, "expires": exp, "license_type": license_type})

# ==================================================================
# RUTA PUBLICA - Licencia tras pago PayPal verificado
# ==================================================================

@app.route("/api/issue_public", methods=["POST"])
@block_proxy
def issue_public():
    ip   = _get_ip()
    data = request.get_json(silent=True) or {}

    ok, err = _check_replay(data, use_secure=False)
    if not ok:
        resp, status = err
        return resp, status

    if not _verify_request_hmac(data, ["username", "email", "paypal_order_id"]):
        return jsonify({"error": "Firma de peticion invalida (sig)."}), 401

    username     = _sanitize((data.get("username")       or "").strip(), "username")
    email        = _sanitize((data.get("email")          or "").strip(), "email")
    days         = int(data.get("days", 30))
    license_type = _normalize_license_type(data.get("license_type") or "")
    order_id     = (data.get("paypal_order_id") or "").strip()
    discount_code = (data.get("discount_code") or "").strip().upper()

    if not username:
        return jsonify({"error": "username requerido"}), 400
    if not order_id:
        return jsonify({"error": "paypal_order_id requerido"}), 400
    if license_type not in LICENSE_TYPES:
        return jsonify({"error": "Tipo de licencia invalido"}), 400
    if days <= 0 or days > 36500:
        return jsonify({"error": "dias invalidos"}), 400
    if _is_rate_limited(ip):
        return jsonify({"error": "Demasiadas peticiones. Espera un momento."}), 429

    if db_order_exists(order_id):
        print(f"[ANTI-REPLAY] order_id={order_id} IP={ip} bloqueado (ya procesado)", flush=True)
        return jsonify({"error": "Este pedido ya fue procesado. Contacta soporte si crees que es un error."}), 409

    applied_discount = 0.0
    valid_code = None
    if discount_code:
        dc = db_discount_get(discount_code)
        if dc and dc.get("active", True):
            plan_ok = not dc.get("plans") or license_type.lower() in dc["plans"]
            uses_ok = dc["max_uses"] == 0 or dc["uses"] < dc["max_uses"]
            exp_ok  = True
            if dc.get("expires_at"):
                try:
                    exp_ok = date.fromisoformat(dc["expires_at"]) >= date.today()
                except Exception:
                    pass
            if plan_ok and uses_ok and exp_ok:
                applied_discount = dc["discount"]
                valid_code = discount_code

    paypal_client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
    paypal_secret    = os.environ.get("PAYPAL_SECRET", "")

    if paypal_client_id and paypal_secret:
        try:
            token_resp = _http.post(
                "https://api-m.paypal.com/v1/oauth2/token",
                auth=(paypal_client_id, paypal_secret),
                data={"grant_type": "client_credentials"}, timeout=10,
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token", "")
            if not access_token:
                return jsonify({"error": "No se pudo autenticar con PayPal."}), 500

            order_resp = _http.get(
                f"https://api-m.paypal.com/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
            )
            order_resp.raise_for_status()
            order_data = order_resp.json()

            if order_data.get("status") != "COMPLETED":
                return jsonify({
                    "error": f"Pago no completado. Estado: '{order_data.get('status')}'."
                }), 402

            try:
                capture = order_data["purchase_units"][0]["payments"]["captures"][0]
            except (KeyError, IndexError):
                return jsonify({"error": "Estructura de pago PayPal inesperada."}), 402

            if capture.get("status") != "COMPLETED":
                return jsonify({"error": "La captura del pago no esta completada."}), 402

            amount        = capture.get("amount", {})
            paid_currency = amount.get("currency_code", "").upper()
            if paid_currency != PAYPAL_CURRENCY:
                return jsonify({
                    "error": f"Moneda del pago invalida ({paid_currency} != {PAYPAL_CURRENCY})."
                }), 402

            try:
                paid = float(amount.get("value", "0"))
            except ValueError:
                return jsonify({"error": "Importe del pago no es un numero valido."}), 402

            expected = round(_expected_price(license_type, days) * (1 - applied_discount / 100), 2)
            if paid < expected - 0.01:
                return jsonify({
                    "error": f"Importe insuficiente (recibido {PAYPAL_CURRENCY} {paid:.2f}, "
                             f"esperado {PAYPAL_CURRENCY} {expected:.2f})."
                }), 402

        except _http.exceptions.Timeout:
            return jsonify({"error": "PayPal no respondio a tiempo. Intenta de nuevo."}), 502
        except _http.exceptions.HTTPError as e:
            return jsonify({"error": f"Error HTTP al contactar PayPal: {e.response.status_code}."}), 502
        except Exception:
            return jsonify({"error": "No se pudo verificar el pago con PayPal."}), 502

    db_order_insert(order_id, username, ip, license_type)
    if valid_code:
        db_discount_increment_uses(valid_code)

    max_devices   = _MAX_DEVICES.get(license_type, 1)
    key = generate_license(username, days, "")
    exp = (date.today() + timedelta(days=days)).isoformat()
    note_discount = f" - Dto:{valid_code}({applied_discount}%)" if valid_code else ""
    db_license_upsert(key, {
        "username": username,
        "expires": exp,
        "note": f"Compra web - email:{email} - PayPal:{order_id[:16]}{note_discount}",
        "license_type": license_type,
        "max_devices": max_devices,
        "bound_devices": [],
        "issued_at": datetime.utcnow().isoformat(),
        "revoked": False,
        "revoke_reason": "",
        "uses": 0,
        "last_seen": "",
        "last_ip": ip,
        "first_use": "",
        "email": email,
        "paypal_order": order_id,
    })
    _send_license_email(
        to_email=email, username=username, key=key,
        plan_name=license_type, expires=exp, is_free=False,
    )
    return jsonify({"key": key, "username": username, "expires": exp, "license_type": license_type})

# ==================================================================
# HEARTBEAT
# ==================================================================

@app.route("/api/heartbeat", methods=["POST"])
@block_proxy
def heartbeat():
    ip   = _get_ip()
    data = request.get_json(silent=True) or {}

    ok, err = _check_replay(data, use_secure=True)
    if not ok:
        return err

    if not _verify_request_hmac(data, ["key", "hwid", "version"]):
        return secure_response(
            {"ok": False, "error": "Firma de peticion invalida o ausente (sig)."}, 401
        )

    key     = (data.get("key")     or "").strip()
    hwid    = (data.get("hwid")    or "").strip().upper()
    version = (data.get("version") or "0.0.0").strip()

    if not key:
        return secure_response({"ok": False, "error": "Clave vacia."}, 400)
    if _is_rate_limited(ip):
        return secure_response({"ok": False, "error": "Demasiadas peticiones."}, 429)

    settings   = db_settings_get()
    min_ver    = settings.get("min_version", MIN_CLIENT_VERSION)
    update_url = settings.get("update_url", UPDATE_URL)
    if _version_tuple(version) < _version_tuple(min_ver):
        return secure_response({
            "ok": False, "update": True,
            "min_version": min_ver, "update_url": update_url,
            "error": f"Version {version} no soportada. Actualiza a {min_ver} o superior.",
        }, 426)

    entry = db_license_get(key)
    if not entry:
        return secure_response({"ok": False, "error": "Licencia no encontrada."}, 404)
    if entry.get("revoked"):
        reason = entry.get("revoke_reason", "Revocada.")
        return secure_response({"ok": False, "error": f"Licencia revocada: {reason}"}, 403)

    db_heartbeat_upsert(key, hwid, ip)
    active_rows = db_heartbeats_for_key(key, HEARTBEAT_WINDOW)
    active_ips  = {r["ip"] for r in active_rows}

    if len(active_ips) > 1:
        print(f"[HEARTBEAT AUTO-BAN] key={key[:20]}... IPs={active_ips}", flush=True)
        db_license_update(key, {
            "revoked": True,
            "revoke_reason": HEARTBEAT_BAN_MSG,
        })
        db_log_failed(ip, key, f"AUTO-BAN Account Sharing IPs={active_ips}")
        db_heartbeat_delete_key(key)
        return secure_response({
            "ok": False, "error": HEARTBEAT_BAN_MSG, "banned": True,
        }, 403)

    db_license_update(key, {
        "last_seen": datetime.utcnow().isoformat(),
        "last_ip": ip,
    })
    return secure_response({"ok": True})

# ==================================================================
# RUTA RAIZ - sirve index.html desde /public
# ==================================================================

@app.route("/", methods=["GET"])
def index():
    return app.send_static_file("index.html")

# ==================================================================
# ENTRY POINT - local dev solamente
# En Vercel el objeto `app` es importado directamente por el runtime.
# ==================================================================

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

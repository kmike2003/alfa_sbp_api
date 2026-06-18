"""
СБП Рекуррентные платежи — Сервер
==================================
Запуск:  python3 server.py
Требует: pip3 install flask requests python-dotenv apscheduler pymysql
"""

from dotenv import load_dotenv
load_dotenv()

import os, json, time, hmac, hashlib, logging, functools, threading
import uuid
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from logging.handlers import RotatingFileHandler
from apscheduler.schedulers.background import BackgroundScheduler

import pymysql
import pymysql.cursors
import requests
from flask import Flask, request, jsonify, session, send_from_directory, g

# ── ENV ────────────────────────────────────────────────────────
ALFA_BASE    = os.getenv("ALFA_BASE", "https://alfa.rbsuat.com/payment/rest")
ALFA_USER    = os.getenv("ALFA_USER", "")
ALFA_PASS    = os.getenv("ALFA_PASS", "")
PANEL_USER   = os.getenv("PANEL_USER", "admin")
PANEL_PASS   = os.getenv("PANEL_PASS", "")
CALLBACK_KEY = os.getenv("CALLBACK_KEY", "")
PORT         = int(os.getenv("PORT", 8787))
LOG_LEVEL    = os.getenv("LOG_LEVEL", "INFO").upper()  # DEBUG для тела запросов

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY не задан в .env! "
        "Сгенерируйте: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "sbp")
DB_USER = os.getenv("DB_USER", "sbp_user")
DB_PASS = os.getenv("DB_PASS", "")

RETURN_URL = os.getenv("RETURN_URL", "shop.ip-cam.club")

# ── FLASK ──────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

# ── LOGGING ────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

_numeric_level = getattr(logging, LOG_LEVEL, logging.INFO)

_file_handler = RotatingFileHandler(
    "logs/server.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setLevel(_numeric_level)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(_numeric_level)

logging.basicConfig(
    level=_numeric_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_file_handler, _console_handler],
)
log = logging.getLogger("sbp")
log.info(f"Логирование запущено, уровень: {LOG_LEVEL}")

# ── ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ ЛОГИРОВАНИЯ ───────────────────────

def _req_id() -> str:
    """Возвращает request-id текущего запроса (хранится в g)."""
    return getattr(g, "req_id", "--------")

def _mask(d: dict, keys=("password", "ALFA_PASS")) -> dict:
    """Маскирует чувствительные поля для логирования."""
    return {k: ("***" if k in keys else v) for k, v in d.items()}

def _short(s, n=200) -> str:
    """Обрезает длинные строки для лога."""
    s = str(s)
    return s if len(s) <= n else s[:n] + f"…[+{len(s)-n}]"

# ── REQUEST / RESPONSE HOOKS ───────────────────────────────────

@app.before_request
def _before():
    """Назначает request-id, фиксирует время, логирует входящий запрос."""
    g.req_id    = uuid.uuid4().hex[:8].upper()
    g.req_start = time.monotonic()

    # Статику не логируем — замусоривает лог
    if request.path.startswith("/static") or request.path in ("/favicon.ico",):
        return

    ip      = request.remote_addr or "?"
    method  = request.method
    path    = request.path
    qs      = f"?{request.query_string.decode()}" if request.query_string else ""
    ua      = request.headers.get("User-Agent", "")[:80]
    auth    = "✓auth" if session.get("authenticated") else "✗anon"

    log.info(f"[{g.req_id}] ▶ {method} {path}{qs}  ip={ip}  {auth}  ua={ua!r}")

    # Тело запроса — только на DEBUG
    if log.isEnabledFor(logging.DEBUG) and request.is_json:
        try:
            body = request.get_json(silent=True, force=True) or {}
            log.debug(f"[{g.req_id}]   body={_short(_mask(body))}")
        except Exception:
            pass


@app.after_request
def _after(response):
    """Логирует итог запроса со временем выполнения."""
    if request.path.startswith("/static") or request.path in ("/favicon.ico",):
        return response

    elapsed_ms = int((time.monotonic() - getattr(g, "req_start", time.monotonic())) * 1000)
    status     = response.status_code
    level      = logging.WARNING if status >= 400 else logging.INFO

    log.log(level, f"[{_req_id()}] ◀ {status}  {elapsed_ms}ms  {request.method} {request.path}")

    # Тело ответа JSON — только на DEBUG и только для API
    if log.isEnabledFor(logging.DEBUG) and request.path.startswith("/api"):
        try:
            data = response.get_json(silent=True, force=True)
            if data is not None:
                log.debug(f"[{_req_id()}]   resp={_short(data)}")
        except Exception:
            pass

    return response

# ── DB ─────────────────────────────────────────────────────────

def get_db() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        database=DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )

def db_execute(sql: str, params=None, fetch: str = None):
    rid = _req_id()
    t0  = time.monotonic()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            else:
                conn.commit()
                result = cur.rowcount
        elapsed = int((time.monotonic() - t0) * 1000)
        short_sql = _short(sql.strip().replace("\n", " "), 120)
        log.debug(f"[{rid}]   db {elapsed}ms  {short_sql}  → {type(result).__name__}")
        return result
    except Exception as e:
        conn.rollback()
        log.error(f"[{rid}] DB ERROR: {e}  sql={_short(sql)}")
        raise
    finally:
        conn.close()

def db_insert(sql: str, params=None) -> int:
    rid = _req_id()
    t0  = time.monotonic()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
            last_id = cur.lastrowid
        elapsed = int((time.monotonic() - t0) * 1000)
        short_sql = _short(sql.strip().replace("\n", " "), 120)
        log.debug(f"[{rid}]   db INSERT {elapsed}ms  lastrowid={last_id}  {short_sql}")
        return last_id
    except Exception as e:
        conn.rollback()
        log.error(f"[{rid}] DB INSERT ERROR: {e}  sql={_short(sql)}")
        raise
    finally:
        conn.close()

# ── RATE LIMITER ───────────────────────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()

def rate_limit(max_per_minute: int = 20):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            ip  = request.remote_addr or "unknown"
            now = time.time()
            with _rate_lock:
                _rate_store[ip] = [t for t in _rate_store[ip] if now - t < 60]
                count = len(_rate_store[ip])
                if count >= max_per_minute:
                    log.warning(
                        f"[{_req_id()}] RATE LIMIT: ip={ip}  "
                        f"endpoint={request.path}  hits={count}/{max_per_minute}"
                    )
                    return jsonify({"error": "Too many requests"}), 429
                _rate_store[ip].append(now)
                log.debug(f"[{_req_id()}]   rate: ip={ip}  hits={count+1}/{max_per_minute}")
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ── AUTH ───────────────────────────────────────────────────────

def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            log.warning(f"[{_req_id()}] UNAUTHORIZED: {request.method} {request.path}  ip={request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

# ── ALFA API ───────────────────────────────────────────────────

def alfa_post(path: str, extra: dict) -> dict:
    if not ALFA_USER or not ALFA_PASS:
        raise ValueError("ALFA_USER и ALFA_PASS не заданы в .env")

    rid  = _req_id()
    safe = {k: v for k, v in extra.items() if k not in ("password",)}
    t0   = time.monotonic()

    log.info(f"[{rid}] → Alfa {path}  params={_short(safe)}")

    payload = {"userName": ALFA_USER, "password": ALFA_PASS, **extra}
    try:
        resp = requests.post(ALFA_BASE + path, data=payload, timeout=15)
        elapsed = int((time.monotonic() - t0) * 1000)

        # Логируем сырой HTTP-статус всегда
        log.info(f"[{rid}] ← Alfa {path}  http={resp.status_code}  {elapsed}ms")

        resp.raise_for_status()
        result = resp.json()

        # Краткий итог — всегда; полный — на DEBUG
        error_code = result.get("errorCode")
        error_msg  = result.get("errorMessage", "")
        log.info(
            f"[{rid}]   Alfa result: errorCode={error_code!r}  "
            f"errorMessage={error_msg!r}  keys={list(result.keys())}"
        )
        log.debug(f"[{rid}]   Alfa full response: {_short(result, 500)}")

        return result

    except requests.Timeout:
        elapsed = int((time.monotonic() - t0) * 1000)
        log.error(f"[{rid}] Alfa TIMEOUT after {elapsed}ms  path={path}")
        raise RuntimeError("Таймаут запроса к банку (>15 с)")
    except requests.HTTPError as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        log.error(
            f"[{rid}] Alfa HTTP ERROR {e.response.status_code}  "
            f"{elapsed}ms  path={path}  body={e.response.text[:300]}"
        )
        raise RuntimeError(f"HTTP {e.response.status_code} от банка: {e.response.text[:300]}")
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        log.error(f"[{rid}] Alfa REQUEST ERROR {elapsed}ms  path={path}  err={e}")
        raise RuntimeError(f"Ошибка запроса к банку: {e}")

# ── ВАЛИДАЦИЯ ──────────────────────────────────────────────────

def validate_amount(amount_kopecks) -> str | None:
    try:
        amt = int(amount_kopecks)
    except (TypeError, ValueError):
        return "Некорректная сумма"
    if amt <= 0:
        return "Сумма должна быть больше нуля"
    if amt > 999_999_99:
        return "Сумма превышает допустимый лимит"
    return None

def validate_description(desc: str) -> str | None:
    if not desc:
        return "Назначение платежа обязательно"
    if any(c in desc for c in ["%", "+", "\n", "\r"]):
        return "Недопустимые символы в назначении: % + и переносы строк"
    if len(desc) > 99:
        return "Назначение — не более 99 символов"
    return None

def validate_order_number(order_number: str) -> str | None:
    if not order_number:
        return "orderNumber обязателен"
    if len(order_number) > 32:
        return "orderNumber не должен превышать 32 символа"
    return None

# ── ВСПОМОГАТЕЛЬНАЯ: извлечь bindingId из ответа банка ─────────

def _extract_binding_from_status(r: dict) -> tuple[str, str, str]:
    binding_info = r.get("bindingInfo") or {}
    binding_id   = binding_info.get("bindingId", "")
    client_id    = binding_info.get("clientId", "") or r.get("clientId", "")

    member_id = ""
    for attr in r.get("transactionAttributes", []):
        if attr.get("name") == "memberId":
            member_id = attr.get("value", "")
            break

    return binding_id, client_id, member_id

# ════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ════════════════════════════════════════════════════════════════

@app.route("/api/login", methods=["POST"])
@rate_limit(10)
def api_login():
    rid  = _req_id()
    body = request.get_json(silent=True) or {}
    username = body.get("username", "").strip()
    password = body.get("password", "")

    log.info(f"[{rid}] LOGIN attempt: username={username!r}  ip={request.remote_addr}")

    if not PANEL_PASS:
        log.error(f"[{rid}] LOGIN aborted: PANEL_PASS не задан")
        return jsonify({"error": "PANEL_PASS не задан на сервере"}), 500

    user_ok = hmac.compare_digest(username, PANEL_USER)
    pass_ok  = hmac.compare_digest(password, PANEL_PASS)

    try:
        db_insert("INSERT INTO auth_log (ip, success) VALUES (%s, %s)",
                  (request.remote_addr, 1 if (user_ok and pass_ok) else 0))
    except Exception as e:
        log.warning(f"[{rid}] auth_log INSERT failed: {e}")

    if user_ok and pass_ok:
        session.permanent = True
        session["authenticated"] = True
        log.info(f"[{rid}] LOGIN OK: username={username!r}  ip={request.remote_addr}")
        return jsonify({"ok": True})

    log.warning(
        f"[{rid}] LOGIN FAIL: username={username!r}  ip={request.remote_addr}  "
        f"user_ok={user_ok}  pass_ok={pass_ok}"
    )
    time.sleep(1)
    return jsonify({"error": "Неверный логин или пароль"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    log.info(f"[{_req_id()}] LOGOUT: ip={request.remote_addr}")
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    authenticated = bool(session.get("authenticated"))
    log.debug(f"[{_req_id()}] /api/me → authenticated={authenticated}")
    return jsonify({"authenticated": authenticated})

# ════════════════════════════════════════════════════════════════
# ALFA API PROXY
# ════════════════════════════════════════════════════════════════

@app.route("/api/register", methods=["POST"])
@require_auth
@rate_limit(30)
def api_register():
    rid  = _req_id()
    body = request.get_json(silent=True) or {}

    log.info(
        f"[{rid}] REGISTER: orderNumber={body.get('orderNumber')!r}  "
        f"amount={body.get('amount')}  clientId={body.get('clientId')!r}  "
        f"desc={body.get('description','')[:40]!r}"
    )

    required = ["orderNumber", "amount", "returnUrl", "description", "clientId"]
    missing  = [k for k in required if not body.get(k)]
    if missing:
        log.warning(f"[{rid}] REGISTER validation: missing fields={missing}")
        return jsonify({"error": f"Не переданы поля: {', '.join(missing)}"}), 400

    for check_fn, field in [(validate_amount, "amount"),
                            (validate_description, "description"),
                            (validate_order_number, "orderNumber")]:
        err = check_fn(body[field])
        if err:
            log.warning(f"[{rid}] REGISTER validation error: {field} → {err}")
            return jsonify({"error": err}), 400

    if len(str(body["clientId"])) > 255:
        log.warning(f"[{rid}] REGISTER validation: clientId too long")
        return jsonify({"error": "clientId слишком длинный"}), 400

    desc = body["description"]
    params = {
        "orderNumber": body["orderNumber"],
        "amount":      int(body["amount"]),
        "returnUrl":   body["returnUrl"],
        "description": desc,
        "clientId":    body["clientId"],
        "features":    body.get("features", "FORCE_CREATE_BINDING"),
        "language":    "ru",
    }
    if body.get("phone"):   params["phone"]   = body["phone"]
    if body.get("email"):   params["email"]   = body["email"]
    if body.get("failUrl"): params["failUrl"] = body["failUrl"]

    jp = {}
    if body.get("sbpSenderFIO"):        jp["sbpSenderFIO"]        = body["sbpSenderFIO"]
    if body.get("subscriptionPurpose"): jp["subscriptionPurpose"] = body["subscriptionPurpose"][:255]
    if jp:
        params["jsonParams"] = json.dumps(jp, ensure_ascii=False)
        log.debug(f"[{rid}]   jsonParams={jp}")

    try:
        result = alfa_post("/register.do", params)
        order_id = result.get("orderId", "")
        ec       = result.get("errorCode")
        if ec and str(ec) != "0":
            log.warning(f"[{rid}] REGISTER bank error: errorCode={ec}  msg={result.get('errorMessage')}")
        else:
            log.info(f"[{rid}] REGISTER OK: orderId={order_id}")
        return jsonify(result)
    except Exception as e:
        log.error(f"[{rid}] REGISTER exception: {e}")
        return jsonify({"error": str(e)}), 502


@app.route("/api/qr", methods=["POST"])
@require_auth
@rate_limit(30)
def api_qr():
    rid  = _req_id()
    body = request.get_json(silent=True) or {}

    log.info(f"[{rid}] QR: mdOrder={body.get('mdOrder')!r}  purpose={body.get('paymentPurpose','')[:40]!r}")

    if not body.get("mdOrder"):
        log.warning(f"[{rid}] QR validation: mdOrder missing")
        return jsonify({"error": "mdOrder обязателен"}), 400

    params = {
        "mdOrder":            body["mdOrder"],
        "createSubscription": "true",
        "qrFormat":           "image",
        "qrHeight":           "300",
        "qrWidth":            "300",
    }
    if body.get("redirectUrl"):    params["redirectUrl"]    = body["redirectUrl"]
    if body.get("paymentPurpose"): params["paymentPurpose"] = body["paymentPurpose"][:140]

    try:
        result = alfa_post("/sbp/c2b/qr/dynamic/get.do", params)
        has_qr     = bool(result.get("renderedQr"))
        has_payload = bool(result.get("payload"))
        ec          = result.get("errorCode")
        if ec and str(ec) != "0":
            log.warning(f"[{rid}] QR bank error: errorCode={ec}  msg={result.get('errorMessage')}")
        else:
            log.info(f"[{rid}] QR OK: hasImage={has_qr}  hasPayload={has_payload}")
        return jsonify(result)
    except Exception as e:
        log.error(f"[{rid}] QR exception: {e}")
        return jsonify({"error": str(e)}), 502


@app.route("/api/charge", methods=["POST"])
@require_auth
@rate_limit(20)
def api_charge():
    rid  = _req_id()
    body = request.get_json(silent=True) or {}

    log.info(
        f"[{rid}] CHARGE: bindingId={body.get('bindingId','')[:16]!r}  "
        f"amount={body.get('amount')}  orderNumber={body.get('orderNumber')!r}  "
        f"clientId={body.get('clientId')!r}"
    )

    required = ["bindingId", "orderNumber", "amount", "returnUrl", "description", "clientId"]
    missing  = [k for k in required if not body.get(k)]
    if missing:
        log.warning(f"[{rid}] CHARGE validation: missing={missing}")
        return jsonify({"error": f"Не переданы: {', '.join(missing)}"}), 400

    for check_fn, field in [(validate_amount, "amount"),
                            (validate_description, "description"),
                            (validate_order_number, "orderNumber")]:
        err = check_fn(body[field])
        if err:
            log.warning(f"[{rid}] CHARGE validation error: {field} → {err}")
            return jsonify({"error": err}), 400

    desc = body["description"]

    binding = db_execute(
        "SELECT * FROM bindings WHERE binding_id = %s AND status = 'ACTIVE' LIMIT 1",
        (body["bindingId"],), fetch="one"
    )
    if not binding:
        log.warning(f"[{rid}] CHARGE: binding not found or inactive  bindingId={body['bindingId']!r}")
        return jsonify({"error": "Привязка не найдена или неактивна"}), 404

    log.info(f"[{rid}] CHARGE: binding found  name={binding.get('name')!r}  id={binding.get('id')}")

    try:
        # ── Шаг 1: register.do ──────────────────────
        log.info(f"[{rid}] CHARGE step 1/3: register.do")
        r1 = alfa_post("/register.do", {
            "orderNumber": body["orderNumber"],
            "amount":      int(body["amount"]),
            "returnUrl":   body["returnUrl"],
            "description": desc,
            "clientId":    body["clientId"],
            "bindingId":   body["bindingId"],
            "features":    "AUTO_PAYMENT",
            "language":    "ru",
        })
        if r1.get("errorCode") and str(r1["errorCode"]) != "0":
            log.warning(f"[{rid}] CHARGE register.do failed: {r1.get('errorCode')} {r1.get('errorMessage')}")
            return jsonify({"error": f"register.do ошибка {r1['errorCode']}: {r1.get('errorMessage','')}", "raw": r1}), 400
        if not r1.get("orderId"):
            log.error(f"[{rid}] CHARGE: bank did not return orderId  r1={r1}")
            return jsonify({"error": "Банк не вернул orderId", "raw": r1}), 502

        order_id = r1["orderId"]
        log.info(f"[{rid}] CHARGE step 1 OK: orderId={order_id}")

        # ── Шаг 2: paymentOrderBinding.do ───────────
        log.info(f"[{rid}] CHARGE step 2/3: paymentOrderBinding.do  orderId={order_id}")
        r2 = alfa_post("/paymentOrderBinding.do", {
            "mdOrder":   order_id,
            "bindingId": body["bindingId"],
            "ip":        request.remote_addr or "127.0.0.1",
            "language":  "ru",
        })
        if r2.get("errorCode") and str(r2["errorCode"]) != "0":
            log.warning(
                f"[{rid}] CHARGE paymentOrderBinding failed: "
                f"{r2.get('errorCode')} {r2.get('errorMessage')}"
            )
            return jsonify({
                "error": f"paymentOrderBinding ошибка {r2['errorCode']}: {r2.get('errorMessage','')}",
                "raw": r2
            }), 400
        log.info(f"[{rid}] CHARGE step 2 OK")

        # ── Шаг 3: polling статуса ───────────────────
        log.info(f"[{rid}] CHARGE step 3/3: polling order status  orderId={order_id}")
        r3   = _poll_order_status(order_id, attempts=10, delay=1.5, rid=rid)
        paid = str(r3.get("orderStatus")) == "2"

        log.info(
            f"[{rid}] CHARGE complete: orderId={order_id}  "
            f"paid={paid}  orderStatus={r3.get('orderStatus')}  "
            f"actionCode={r3.get('actionCode')}"
        )

        db_insert(
            """INSERT INTO charge_history
               (binding_id_fk, order_id, order_number, amount, description, status, order_status)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (binding["id"], order_id, body["orderNumber"],
             body["amount"] / 100, desc,
             "SUCCESS" if paid else "PENDING",
             r3.get("orderStatus"))
        )
        db_execute("UPDATE bindings SET last_charge_date = CURDATE() WHERE id = %s", (binding["id"],))

        return jsonify({"ok": True, "orderId": order_id, "paid": paid, "status": r3.get("orderStatus")})

    except Exception as e:
        log.error(f"[{rid}] CHARGE exception: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 502


def _poll_order_status(order_id: str, attempts: int = 5, delay: float = 1.5,
                       rid: str = "") -> dict:
    """Опрашивает статус заказа с паузами. Возвращает последний ответ банка."""
    result = {}
    for attempt in range(attempts):
        time.sleep(delay)
        try:
            result = alfa_post("/getOrderStatusExtended.do", {"orderId": order_id})
        except Exception as e:
            log.warning(f"[{rid}] _poll_order_status attempt {attempt+1}/{attempts} error: {e}")
            continue

        status = str(result.get("orderStatus", ""))
        log.info(
            f"[{rid}] _poll_order_status: attempt={attempt+1}/{attempts}  "
            f"orderId={order_id}  orderStatus={status}  actionCode={result.get('actionCode')}"
        )
        if status in ("2", "4", "6"):
            log.info(f"[{rid}] _poll_order_status: terminal status={status}, stop polling")
            break
        else:
            log.debug(f"[{rid}] _poll_order_status: non-terminal status={status!r}, continue")

    return result


@app.route("/api/status", methods=["POST"])
@require_auth
@rate_limit(60)
def api_status():
    rid  = _req_id()
    body = request.get_json(silent=True) or {}

    order_id = body.get("orderId", "")
    log.info(f"[{rid}] STATUS: orderId={order_id!r}")

    if not order_id:
        log.warning(f"[{rid}] STATUS: orderId missing")
        return jsonify({"error": "orderId обязателен"}), 400
    try:
        result = alfa_post("/getOrderStatusExtended.do", {"orderId": order_id})
        log.info(
            f"[{rid}] STATUS result: orderStatus={result.get('orderStatus')}  "
            f"actionCode={result.get('actionCode')}  "
            f"bindingId={((result.get('bindingInfo') or {}).get('bindingId',''))!r}"
        )
        return jsonify(result)
    except Exception as e:
        log.error(f"[{rid}] STATUS exception: {e}")
        return jsonify({"error": str(e)}), 502

# ════════════════════════════════════════════════════════════════
# AWAIT BINDING
# ════════════════════════════════════════════════════════════════

@app.route("/api/await-binding", methods=["POST"])
@require_auth
@rate_limit(10)
def api_await_binding():
    """
    Двухфазное ожидание:
      Фаза A — ждём, пока клиент оплатит (orderStatus становится 2/4/6).
      Фаза B — оплата подтверждена (orderStatus=2), но bindingInfo ещё не
                заполнен банком — это отдельный, более медленный процесс.
                Ждём его отдельно, с собственным таймаутом и логированием,
                чтобы не путать "клиент не платит" с "банк не привязывает".
    """
    rid      = _req_id()
    body     = request.get_json(silent=True) or {}
    order_id = body.get("orderId", "").strip()
    db_id    = body.get("dbId")

    log.info(f"[{rid}] AWAIT-BINDING start: orderId={order_id!r}  dbId={db_id}")

    if not order_id:
        log.warning(f"[{rid}] AWAIT-BINDING: orderId missing")
        return jsonify({"ok": False, "error": "orderId обязателен"}), 400

    # ── Фаза A: ждём оплату ─────────────────────────────────────
    PAY_ATTEMPTS = 1440
    POLL_DELAY   = 10.0

    payment_confirmed = False
    last_response      = {}

    for attempt in range(PAY_ATTEMPTS):
        time.sleep(POLL_DELAY)
        elapsed_total = int((attempt + 1) * POLL_DELAY)

        try:
            r = alfa_post("/getOrderStatusExtended.do", {"orderId": order_id})
        except Exception as e:
            log.warning(
                f"[{rid}] AWAIT-BINDING[payment] poll error: "
                f"attempt={attempt+1}/{PAY_ATTEMPTS}  elapsed={elapsed_total}s  err={e}"
            )
            continue

        last_response = r
        order_status  = str(r.get("orderStatus", ""))
        binding_id, client_id, member_id = _extract_binding_from_status(r)

        log.info(
            f"[{rid}] AWAIT-BINDING[payment] poll: attempt={attempt+1}/{PAY_ATTEMPTS}  "
            f"elapsed={elapsed_total}s  orderStatus={order_status}  "
            f"bindingId={binding_id!r}  clientId={client_id!r}"
        )

        if order_status == "2":
            log.info(
                f"[{rid}] AWAIT-BINDING[payment] CONFIRMED: orderId={order_id}  "
                f"elapsed={elapsed_total}s  bindingId_already_present={bool(binding_id)}"
            )
            payment_confirmed = True
            # Если bindingId уже пришёл одновременно с оплатой — отдаём сразу,
            # не теряя время на отдельную фазу B.
            if binding_id:
                _save_binding(order_id, binding_id, client_id, member_id, db_id, rid=rid)
                return jsonify({
                    "ok":          True,
                    "bindingId":   binding_id,
                    "clientId":    client_id,
                    "memberId":    member_id,
                    "orderStatus": order_status,
                })
            break

        if order_status in ("4", "6"):
            log.info(
                f"[{rid}] AWAIT-BINDING[payment] REJECTED: orderId={order_id}  "
                f"orderStatus={order_status}  actionCode={r.get('actionCode')}  "
                f"elapsed={elapsed_total}s"
            )
            return jsonify({
                "ok":                    False,
                "orderStatus":           order_status,
                "error":                 "Платёж отклонён или истёк",
                "actionCode":            r.get("actionCode"),
                "actionCodeDescription": r.get("actionCodeDescription", ""),
            })

        log.debug(
            f"[{rid}] AWAIT-BINDING[payment] in-progress orderStatus={order_status!r}  "
            f"attempt={attempt+1}/{PAY_ATTEMPTS}"
        )

    if not payment_confirmed:
        log.warning(
            f"[{rid}] AWAIT-BINDING[payment] TIMEOUT: orderId={order_id}  "
            f"клиент не оплатил за {int(PAY_ATTEMPTS * POLL_DELAY)}s  "
            f"lastOrderStatus={last_response.get('orderStatus')!r}"
        )
        return jsonify({
            "ok":    False,
            "error": "Клиент пока не оплатил (таймаут 90с). QR остаётся активным — можно подождать ещё.",
        })

    # ── Фаза B: оплата подтверждена, ждём bindingInfo отдельно ──
    # Банк формирует привязку асинхронно после депозита, это может занять
    # больше времени, чем сама оплата. Ждём дольше и логируем явно как
    # отдельную фазу, чтобы не путать с "клиент не платит".
    BIND_ATTEMPTS = 360
    log.info(
        f"[{rid}] AWAIT-BINDING[bind] entering phase B: orderId={order_id}  "
        f"will poll up to {int(BIND_ATTEMPTS * POLL_DELAY)}s for bindingInfo"
    )

    for attempt in range(BIND_ATTEMPTS):
        time.sleep(POLL_DELAY)
        elapsed_total = int((attempt + 1) * POLL_DELAY)

        try:
            r = alfa_post("/getOrderStatusExtended.do", {"orderId": order_id})
        except Exception as e:
            log.warning(
                f"[{rid}] AWAIT-BINDING[bind] poll error: "
                f"attempt={attempt+1}/{BIND_ATTEMPTS}  elapsed={elapsed_total}s  err={e}"
            )
            continue

        last_response = r
        order_status               = str(r.get("orderStatus", ""))
        binding_id, client_id, member_id = _extract_binding_from_status(r)

        log.info(
            f"[{rid}] AWAIT-BINDING[bind] poll: attempt={attempt+1}/{BIND_ATTEMPTS}  "
            f"elapsed={elapsed_total}s  orderStatus={order_status}  "
            f"bindingId={binding_id!r}  clientId={client_id!r}  memberId={member_id!r}  "
            f"raw_bindingInfo={r.get('bindingInfo')!r}"
        )

        if binding_id:
            log.info(
                f"[{rid}] AWAIT-BINDING[bind] SUCCESS: orderId={order_id}  "
                f"bindingId={binding_id}  phaseB_elapsed={elapsed_total}s"
            )
            _save_binding(order_id, binding_id, client_id, member_id, db_id, rid=rid)
            return jsonify({
                "ok":          True,
                "bindingId":   binding_id,
                "clientId":    client_id,
                "memberId":    member_id,
                "orderStatus": order_status,
            })

        # Если статус вдруг откатился на отклонённый/истёкший — прекращаем
        if order_status in ("4", "6"):
            log.warning(
                f"[{rid}] AWAIT-BINDING[bind] order became rejected during phase B: "
                f"orderId={order_id}  orderStatus={order_status}"
            )
            return jsonify({
                "ok":          False,
                "orderStatus": order_status,
                "error":       "Заказ был отклонён в процессе ожидания привязки",
            })

        log.debug(
            f"[{rid}] AWAIT-BINDING[bind] no bindingInfo yet, attempt={attempt+1}/{BIND_ATTEMPTS}"
        )

    # Таймаут фазы B — оплата прошла, но привязка не появилась.
    # Это самый важный случай для диагностики: платёж прошёл, банк должен
    # был создать bindingInfo, но за 120с этого не произошло.
    log.error(
        f"[{rid}] AWAIT-BINDING[bind] TIMEOUT после успешной оплаты: "
        f"orderId={order_id}  оплата подтверждена, но bindingInfo НЕ появился за "
        f"{int(BIND_ATTEMPTS * POLL_DELAY)}s  lastResponse={_short(last_response, 500)}"
    )
    return jsonify({
        "ok":    False,
        "error": (
            "Оплата прошла, но банк пока не вернул данные привязки (bindingInfo). "
            "Это может занять больше времени — проверьте раздел «Привязки» позже, "
            "или она придёт через колбэк автоматически."
        ),
    })


def _save_binding(order_id: str, binding_id: str, client_id: str,
                  member_id: str, db_id=None, rid: str = "") -> None:
    rid = rid or _req_id()

    if db_id:
        affected = db_execute(
            """UPDATE bindings
               SET binding_id = %s, status = 'ACTIVE', member_id = %s
               WHERE id = %s AND status IN ('PENDING', 'ACTIVE')""",
            (binding_id, member_id, db_id)
        )
        if affected:
            log.info(f"[{rid}] _save_binding: updated by id={db_id}  bindingId={binding_id}")
            return
        else:
            log.warning(f"[{rid}] _save_binding: UPDATE by id={db_id} affected 0 rows, trying order_id")

    affected = db_execute(
        """UPDATE bindings
           SET binding_id = %s, status = 'ACTIVE', member_id = %s
           WHERE order_id = %s AND status IN ('PENDING', 'ACTIVE')""",
        (binding_id, member_id, order_id)
    )
    if affected:
        log.info(f"[{rid}] _save_binding: updated by orderId={order_id}  bindingId={binding_id}")
        return

    log.warning(
        f"[{rid}] _save_binding: no existing row found — "
        f"inserting new  orderId={order_id}  bindingId={binding_id}  clientId={client_id}"
    )
    db_insert(
        """INSERT INTO bindings
           (name, client_id, binding_id, order_id, member_id, amount, charge_day, status)
           VALUES (%s,%s,%s,%s,%s,0,1,'ACTIVE')""",
        (client_id or "Клиент", client_id, binding_id, order_id, member_id)
    )
    log.info(f"[{rid}] _save_binding: inserted new row  bindingId={binding_id}")


@app.route("/api/bindings/get", methods=["POST"])
@require_auth
@rate_limit(10)
def api_get_bindings():
    rid = _req_id()
    log.info(f"[{rid}] GET-BINDINGS-FROM-BANK: fetching all clientIds")
    try:
        rows = db_execute(
            "SELECT DISTINCT client_id FROM bindings WHERE client_id IS NOT NULL AND client_id != ''",
            fetch="all"
        )
        client_ids = [r["client_id"] for r in (rows or [])]
        log.info(f"[{rid}] GET-BINDINGS-FROM-BANK: found {len(client_ids)} clientId(s): {client_ids}")

        if not client_ids:
            return jsonify({"bindings": [], "note": "Нет clientId в локальной БД"})

        all_bindings, errors = [], []
        for cid in client_ids:
            try:
                r = alfa_post("/getBindings.do", {"clientId": cid, "showExpired": "false"})
                count = len(r.get("bindings") or [])
                log.info(f"[{rid}] GET-BINDINGS-FROM-BANK: clientId={cid!r} → {count} binding(s)")
                if r.get("bindings"):
                    for b in r["bindings"]:
                        b["clientId"] = cid
                    all_bindings.extend(r["bindings"])
            except Exception as e:
                log.error(f"[{rid}] GET-BINDINGS-FROM-BANK: error for clientId={cid!r}: {e}")
                errors.append(f"clientId={cid}: {e}")

        log.info(f"[{rid}] GET-BINDINGS-FROM-BANK: total={len(all_bindings)}  errors={len(errors)}")
        return jsonify({"bindings": all_bindings, "errors": errors})
    except Exception as e:
        log.error(f"[{rid}] GET-BINDINGS-FROM-BANK exception: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 502


@app.route("/api/binding/fetch", methods=["POST"])
@require_auth
@rate_limit(20)
def api_fetch_binding():
    """
    Разовая (не polling) попытка получить bindingId с банка для существующей
    PENDING-записи. Берёт order_id из БД по dbId, делает один запрос
    getOrderStatusExtended.do и, если bindingId найден, сохраняет его.
    Используется кнопкой «Запросить с сервера» в таблице привязок —
    в отличие от /api/await-binding, не блокирует запрос на десятки секунд.
    """
    rid  = _req_id()
    body = request.get_json(silent=True) or {}
    db_id = body.get("dbId")

    log.info(f"[{rid}] FETCH-BINDING: dbId={db_id}")

    if not db_id:
        log.warning(f"[{rid}] FETCH-BINDING: dbId missing")
        return jsonify({"ok": False, "error": "dbId обязателен"}), 400

    row = db_execute("SELECT * FROM bindings WHERE id = %s LIMIT 1", (db_id,), fetch="one")
    if not row:
        log.warning(f"[{rid}] FETCH-BINDING: row not found  dbId={db_id}")
        return jsonify({"ok": False, "error": "Запись не найдена"}), 404

    if row.get("binding_id"):
        log.info(f"[{rid}] FETCH-BINDING: already has bindingId={row['binding_id']}  dbId={db_id}")
        return jsonify({"ok": True, "bindingId": row["binding_id"], "alreadyHad": True})

    order_id = row.get("order_id")
    if not order_id:
        log.warning(f"[{rid}] FETCH-BINDING: no order_id stored  dbId={db_id}")
        return jsonify({"ok": False, "error": "Для этой записи не сохранён orderId — привязать автоматически нельзя"}), 400

    try:
        r = alfa_post("/getOrderStatusExtended.do", {"orderId": order_id})
    except Exception as e:
        log.error(f"[{rid}] FETCH-BINDING: alfa error  dbId={db_id}  orderId={order_id}  err={e}")
        return jsonify({"ok": False, "error": str(e)}), 502

    order_status = str(r.get("orderStatus", ""))
    binding_id, client_id, member_id = _extract_binding_from_status(r)

    log.info(
        f"[{rid}] FETCH-BINDING result: dbId={db_id}  orderId={order_id}  "
        f"orderStatus={order_status}  bindingId={binding_id!r}"
    )

    if binding_id:
        _save_binding(order_id, binding_id, client_id, member_id, db_id=db_id, rid=rid)
        return jsonify({"ok": True, "bindingId": binding_id, "orderStatus": order_status})

    if order_status in ("4", "6"):
        return jsonify({
            "ok": False,
            "orderStatus": order_status,
            "error": "Платёж отклонён или истёк — привязка невозможна",
            "actionCode": r.get("actionCode"),
            "actionCodeDescription": r.get("actionCodeDescription", ""),
        })

    if order_status != "2":
        return jsonify({
            "ok": False,
            "orderStatus": order_status,
            "error": "Клиент пока не оплатил — банк ещё не подтвердил платёж",
        })

    return jsonify({
        "ok": False,
        "orderStatus": order_status,
        "error": "Оплата подтверждена, но банк пока не вернул bindingInfo. Попробуйте позже.",
    })

@app.route("/api/binding/deactivate", methods=["POST"])
@require_auth
@rate_limit(10)
def api_deactivate():
    rid  = _req_id()
    body = request.get_json(silent=True) or {}
    bid  = body.get("bindingId", "")

    log.info(f"[{rid}] DEACTIVATE: bindingId={bid!r}")

    if not bid:
        log.warning(f"[{rid}] DEACTIVATE: bindingId missing")
        return jsonify({"error": "bindingId обязателен"}), 400
    try:
        result = alfa_post("/unBindCard.do", {"bindingId": bid})
        db_execute("UPDATE bindings SET status = 'INACTIVE' WHERE binding_id = %s", (bid,))
        log.info(f"[{rid}] DEACTIVATE OK: bindingId={bid}  bankResult={result}")
        return jsonify(result)
    except Exception as e:
        log.error(f"[{rid}] DEACTIVATE exception: bindingId={bid}  err={e}")
        return jsonify({"error": str(e)}), 502

# ════════════════════════════════════════════════════════════════
# LOCAL DATA ROUTES
# ════════════════════════════════════════════════════════════════

@app.route("/api/data/bindings", methods=["GET"])
@require_auth
def data_bindings():
    rid  = _req_id()
    rows = db_execute("SELECT * FROM bindings ORDER BY created_at DESC", fetch="all")
    log.info(f"[{rid}] DATA-BINDINGS GET: returned {len(rows)} rows")
    for r in rows:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()
            elif hasattr(v, 'isoformat'):
                r[k] = v.isoformat()
    return jsonify(rows)


@app.route("/api/data/bindings", methods=["POST"])
@require_auth
def data_add_binding():
    rid  = _req_id()
    body = request.get_json(silent=True) or {}

    log.info(
        f"[{rid}] DATA-BINDINGS ADD: name={body.get('name')!r}  "
        f"status={body.get('status')!r}  orderId={body.get('orderId')!r}"
    )

    if not body.get("name"):
        log.warning(f"[{rid}] DATA-BINDINGS ADD: name missing")
        return jsonify({"error": "name обязателен"}), 400

    new_id = db_insert(
        """INSERT INTO bindings
           (name, phone, email, client_id, binding_id, order_id, amount, charge_day, description, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            body.get("name"),
            body.get("phone") or None,
            body.get("email") or None,
            body.get("clientId") or body.get("client_id") or body.get("name"),
            body.get("bindingId") or body.get("binding_id") or None,
            body.get("orderId")   or body.get("order_id")   or None,
            float(body.get("amount", 0)),
            int(body.get("day", body.get("charge_day", 1))),
            body.get("desc") or body.get("description") or None,
            body.get("status", "PENDING"),
        )
    )
    log.info(f"[{rid}] DATA-BINDINGS ADD OK: id={new_id}  name={body.get('name')!r}")
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/data/bindings/<int:bid>", methods=["PATCH"])
@require_auth
def data_patch_binding(bid):
    rid  = _req_id()
    body = request.get_json(silent=True) or {}

    log.info(f"[{rid}] DATA-BINDINGS PATCH: id={bid}  fields={list(body.keys())}")

    allowed = {"name", "phone", "email", "binding_id", "order_id",
               "amount", "charge_day", "description", "status",
               "last_charge_date", "member_id",
               "subscription_service_id", "subscription_service_name"}
    key_map = {"bindingId": "binding_id", "orderId": "order_id",
               "day": "charge_day", "desc": "description",
               "clientId": "client_id"}

    sets, vals = [], []
    skipped    = []
    for k, v in body.items():
        col = key_map.get(k, k)
        if col in allowed:
            sets.append(f"`{col}` = %s")
            vals.append(v)
        else:
            skipped.append(k)

    if skipped:
        log.debug(f"[{rid}] DATA-BINDINGS PATCH: skipped unknown fields={skipped}")

    if not sets:
        log.warning(f"[{rid}] DATA-BINDINGS PATCH: no valid fields  body_keys={list(body.keys())}")
        return jsonify({"error": "Нет допустимых полей для обновления"}), 400

    vals.append(bid)
    affected = db_execute(f"UPDATE bindings SET {', '.join(sets)} WHERE id = %s", vals)
    log.info(f"[{rid}] DATA-BINDINGS PATCH OK: id={bid}  affected={affected}  sets={sets}")
    return jsonify({"ok": True})


@app.route("/api/data/bindings/<int:bid>", methods=["DELETE"])
@require_auth
def data_delete_binding(bid):
    rid      = _req_id()
    affected = db_execute("DELETE FROM bindings WHERE id = %s", (bid,))
    log.info(f"[{rid}] DATA-BINDINGS DELETE: id={bid}  affected={affected}")
    return jsonify({"ok": True})


@app.route("/api/data/history", methods=["GET"])
@require_auth
def data_history():
    rid  = _req_id()
    rows = db_execute(
        """SELECT h.*, b.name AS client_name
           FROM charge_history h
           LEFT JOIN bindings b ON b.id = h.binding_id_fk
           ORDER BY h.created_at DESC
           LIMIT 500""",
        fetch="all"
    )
    log.info(f"[{rid}] DATA-HISTORY GET: returned {len(rows)} rows")
    for r in rows:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()
            elif hasattr(v, 'isoformat'):
                r[k] = v.isoformat()
    return jsonify(rows)


@app.route("/api/data/history", methods=["DELETE"])
@require_auth
def data_clear_history():
    rid      = _req_id()
    affected = db_execute("DELETE FROM charge_history")
    log.info(f"[{rid}] DATA-HISTORY CLEAR: deleted {affected} rows")
    return jsonify({"ok": True})

# ════════════════════════════════════════════════════════════════
# CALLBACK
# ════════════════════════════════════════════════════════════════

@app.route("/callback/sbp", methods=["GET", "POST"])
@rate_limit(120)
def callback_sbp():
    rid = _req_id()

    if request.method == "GET":
        payload = request.args.to_dict()
        log.info(f"[{rid}] CALLBACK GET: params={payload}")
    else:
        raw = request.get_data()
        log.info(f"[{rid}] CALLBACK POST: content_type={request.content_type}  len={len(raw)}")

        if CALLBACK_KEY:
            sig      = request.headers.get("X-Signature", "")
            expected = hmac.new(CALLBACK_KEY.encode(), raw, hashlib.sha256).hexdigest()
            sig_ok   = hmac.compare_digest(sig, expected)
            log.info(f"[{rid}] CALLBACK signature check: sig_ok={sig_ok}")
            if not sig_ok:
                log.warning(
                    f"[{rid}] CALLBACK bad signature: "
                    f"ip={request.remote_addr}  sig={sig[:16]}…  expected={expected[:16]}…"
                )
                return jsonify({"error": "Invalid signature"}), 403
        else:
            log.debug(f"[{rid}] CALLBACK signature check skipped (CALLBACK_KEY not set)")

        payload = request.get_json(silent=True) or request.form.to_dict()
        log.info(f"[{rid}] CALLBACK POST payload: {_short(payload)}")

    order_id  = payload.get("mdOrder")
    operation = payload.get("operation", "")
    status    = str(payload.get("status", ""))
    member_id = payload.get("memberId", "")

    log.info(
        f"[{rid}] CALLBACK parsed: mdOrder={order_id!r}  "
        f"operation={operation!r}  status={status!r}  memberId={member_id!r}"
    )

    ACCEPTED_OPERATIONS = {"bindingCreated", "deposited", "approved", ""}
    if operation and operation not in ACCEPTED_OPERATIONS:
        log.info(f"[{rid}] CALLBACK ignored: operation={operation!r} not in accepted list")
        return "OK", 200

    if not order_id:
        log.warning(f"[{rid}] CALLBACK: mdOrder missing in payload")
        return "OK", 200

    existing = db_execute(
        "SELECT id, binding_id FROM bindings WHERE order_id = %s LIMIT 1",
        (order_id,), fetch="one"
    )
    log.debug(f"[{rid}] CALLBACK existing row: {existing}")

    if existing and existing.get("binding_id"):
        log.info(
            f"[{rid}] CALLBACK: bindingId already saved for orderId={order_id}  "
            f"bindingId={existing['binding_id']}  — skipping"
        )
        return "OK", 200

    try:
        log.info(f"[{rid}] CALLBACK: calling getOrderStatusExtended  orderId={order_id}")
        r          = alfa_post("/getOrderStatusExtended.do", {"orderId": order_id})
        order_st   = str(r.get("orderStatus", ""))
        binding_id, client_id, member_id_from_r = _extract_binding_from_status(r)
        resolved_member = member_id or member_id_from_r

        log.info(
            f"[{rid}] CALLBACK getOrderStatus result: "
            f"orderStatus={order_st}  bindingId={binding_id!r}  "
            f"clientId={client_id!r}  memberId={resolved_member!r}"
        )

        if not binding_id:
            log.info(
                f"[{rid}] CALLBACK: bindingId not yet available in getOrderStatusExtended "
                f"(orderStatus={order_st}) — await-binding will pick it up"
            )
            return "OK", 200

        _save_binding(
            order_id, binding_id, client_id, resolved_member,
            db_id=existing["id"] if existing else None,
            rid=rid,
        )

    except Exception as e:
        log.error(f"[{rid}] CALLBACK processing error: {e}", exc_info=True)

    return "OK", 200

# ════════════════════════════════════════════════════════════════
# SERVE FRONTEND
# ════════════════════════════════════════════════════════════════

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path and (Path("static") / path).exists():
        return send_from_directory("static", path)
    return send_from_directory("static", "index.html")

# ════════════════════════════════════════════════════════════════
# SECURITY HEADERS
# ════════════════════════════════════════════════════════════════

@app.after_request
def add_security_headers(response):
    # Вызываем наш логирующий хук вручную (after_request цепочка)
    response = _after(response)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-XSS-Protection"]       = "1; mode=block"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "script-src 'self' 'unsafe-inline';"
    )
    return response

# ════════════════════════════════════════════════════════════════
# SCHEDULER — ежедневные автосписания
# ════════════════════════════════════════════════════════════════

def process_daily_charges():
    job_id  = uuid.uuid4().hex[:8].upper()
    today     = datetime.now().day
    today_str = datetime.now().strftime("%Y-%m-%d")

    log.info(f"[{job_id}] SCHEDULER daily_charges start: date={today_str}  day={today}")

    bindings = db_execute(
        """SELECT * FROM bindings
           WHERE status = 'ACTIVE'
             AND charge_day = %s
             AND (last_charge_date IS NULL OR last_charge_date < %s)
             AND binding_id IS NOT NULL
             AND amount > 0""",
        (today, today_str), fetch="all"
    )
    log.info(f"[{job_id}] SCHEDULER: found {len(bindings)} binding(s) to charge today")

    success_count = error_count = skip_count = 0

    for b in bindings:
        bid = f"{job_id}:{b.get('id')}"
        try:
            order_number   = f"AUTO-{today_str}-{uuid.uuid4().hex[:6].upper()}"
            amount_kopecks = int(float(b["amount"]) * 100)

            log.info(
                f"[{bid}] AUTO-CHARGE: name={b.get('name')!r}  "
                f"amount={b['amount']}₽  bindingId={b.get('binding_id','')[:16]!r}  "
                f"orderNumber={order_number}"
            )

            if amount_kopecks <= 0:
                log.warning(f"[{bid}] AUTO-CHARGE SKIP: amount=0  name={b.get('name')!r}")
                skip_count += 1
                continue

            desc = (b.get("description") or "Ежемесячная подписка")[:99]

            # ── register.do ─────────────────────────
            log.info(f"[{bid}] AUTO-CHARGE step 1/3: register.do")
            r1 = alfa_post("/register.do", {
                "orderNumber": order_number,
                "amount":      amount_kopecks,
                "returnUrl":   RETURN_URL,
                "description": desc,
                "clientId":    b["client_id"],
                "bindingId":   b["binding_id"],
                "features":    "AUTO_PAYMENT",
                "language":    "ru",
            })
            if not r1.get("orderId") or (r1.get("errorCode") and str(r1["errorCode"]) != "0"):
                raise RuntimeError(f"register.do: errorCode={r1.get('errorCode')} {r1.get('errorMessage')}")

            order_id = r1["orderId"]
            log.info(f"[{bid}] AUTO-CHARGE step 1 OK: orderId={order_id}")

            # ── paymentOrderBinding.do ───────────────
            log.info(f"[{bid}] AUTO-CHARGE step 2/3: paymentOrderBinding.do")
            r2 = alfa_post("/paymentOrderBinding.do", {
                "mdOrder":   order_id,
                "bindingId": b["binding_id"],
                "ip":        "127.0.0.1",
                "language":  "ru",
            })
            if r2.get("errorCode") and str(r2["errorCode"]) != "0":
                raise RuntimeError(f"paymentOrderBinding: {r2.get('errorCode')} {r2.get('errorMessage')}")
            log.info(f"[{bid}] AUTO-CHARGE step 2 OK")

            # ── polling ──────────────────────────────
            log.info(f"[{bid}] AUTO-CHARGE step 3/3: polling  orderId={order_id}")
            r3   = _poll_order_status(order_id, attempts=5, delay=1.5, rid=bid)
            paid = str(r3.get("orderStatus")) == "2"

            log.info(
                f"[{bid}] AUTO-CHARGE complete: paid={paid}  "
                f"orderStatus={r3.get('orderStatus')}  orderId={order_id}  "
                f"name={b.get('name')!r}  amount={b['amount']}₽"
            )

            db_insert(
                """INSERT INTO charge_history
                   (binding_id_fk, order_id, order_number, amount, description, status, order_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (b["id"], order_id, order_number, b["amount"], desc,
                 "SUCCESS" if paid else "PENDING", r3.get("orderStatus"))
            )
            db_execute("UPDATE bindings SET last_charge_date = %s WHERE id = %s",
                       (today_str, b["id"]))

            success_count += 1

        except Exception as e:
            error_count += 1
            log.error(
                f"[{bid}] AUTO-CHARGE FAILED: name={b.get('name')!r}  "
                f"amount={b.get('amount')}₽  err={e}",
                exc_info=True
            )
            try:
                db_insert(
                    """INSERT INTO charge_history
                       (binding_id_fk, order_id, order_number, amount, description, status, error_message)
                       VALUES (%s,'','', %s,%s,'ERROR',%s)""",
                    (b["id"], b["amount"],
                     b.get("description") or "Ежемесячная подписка", str(e))
                )
            except Exception as db_err:
                log.error(f"[{bid}] AUTO-CHARGE: failed to write error to history: {db_err}")

    log.info(
        f"[{job_id}] SCHEDULER daily_charges done: "
        f"success={success_count}  error={error_count}  skip={skip_count}  "
        f"total={len(bindings)}"
    )

# ════════════════════════════════════════════════════════════════
# STARTUP CHECKS + SCHEDULER
# ════════════════════════════════════════════════════════════════

if not PANEL_PASS:
    log.warning("PANEL_PASS не задан в .env!")
if not DB_PASS:
    log.warning("DB_PASS не задан в .env!")
if not CALLBACK_KEY:
    log.warning("CALLBACK_KEY не задан в .env — подпись колбэков не проверяется!")
if not ALFA_USER or not ALFA_PASS:
    log.warning("ALFA_USER / ALFA_PASS не заданы — запросы к банку будут падать!")

log.info(f"ALFA_BASE={ALFA_BASE}")
log.info(f"DB={DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
log.info(f"RETURN_URL={RETURN_URL}")

scheduler = BackgroundScheduler()
scheduler.add_job(process_daily_charges, "cron", hour=10, minute=0, id="daily_charges")
scheduler.start()
log.info("Планировщик запущен (ежедневно в 10:00)")

# ════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"🚀 Сервер (dev): http://localhost:{PORT}")
    print(f"🏦 Альфа-банк: {ALFA_BASE}")
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
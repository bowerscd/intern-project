import logging
import os
import secrets
import uuid

from flask import Flask, render_template, request, Response, redirect, jsonify
import requests as http_requests
from requests.exceptions import ConnectionError, Timeout, ReadTimeout
from werkzeug.middleware.proxy_fix import ProxyFix

from config import DEV_MODE, USE_MOCK, USE_PROXY
from server import api_base, backend_url, session_cookie_name

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=1, x_host=1)  # type: ignore[assignment]

# Flask secret key for flash/session support (defence-in-depth)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# Limit request body size to 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# Configuration (now pulled from config and server modules)
BACKEND_URL = backend_url()
API_BASE = api_base()
SESSION_COOKIE_NAME = session_cookie_name()

logger = logging.getLogger(__name__)

# Paths that do not require an authenticated session cookie.
PUBLIC_PATHS = frozenset(
    {
        "/login",
        "/auth/callback",
        "/auth/complete-registration",
        "/auth/claim-account",
        "/happyhour",
        "/healthz",
    }
)


@app.before_request
def require_auth():
    """Redirect to /login if the backend session cookie is missing.

    Static assets, /api/* proxy routes, and PUBLIC_PATHS are exempt.
    In mock mode authentication gating is skipped entirely.
    """
    if USE_MOCK:
        return None
    # Always allow static files and API proxy routes
    if request.path.startswith(("/static/", "/api/")):
        return None
    # Allow the health endpoint
    if request.path == "/healthz":
        return None
    # Allow explicitly public pages
    if request.path in PUBLIC_PATHS:
        return None
    # Check for the backend session cookie (set through the proxy)
    if SESSION_COOKIE_NAME not in request.cookies:
        return redirect("/login")
    return None


@app.before_request
def inject_request_id():
    """Generate or propagate a request ID for tracing."""
    request.environ["REQUEST_ID"] = request.headers.get(
        "X-Request-ID", uuid.uuid4().hex
    )


@app.after_request
def add_request_id_header(response):
    """Echo the request ID and add security headers to the response."""
    rid = request.environ.get("REQUEST_ID")
    if rid:
        response.headers["X-Request-ID"] = rid
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not DEV_MODE:
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


# ── Health endpoint ──────────────────────────────────────────────────


@app.route("/healthz")
def healthcheck():
    """Liveness probe — always returns 200."""
    return jsonify(status="ok")


# ── Error handlers ─────────────────────────────────────────────────


@app.errorhandler(404)
def page_not_found(e):
    """Return a 404 page or JSON depending on the Accept header."""
    if request.accept_mimetypes.best == "application/json":
        return jsonify(detail="Not found"), 404
    return render_template("404.html", title="Page Not Found"), 404


@app.errorhandler(500)
def internal_server_error(e):
    """Return a 500 page or JSON depending on the Accept header."""
    logger.exception("Internal server error")
    if request.accept_mimetypes.best == "application/json":
        return jsonify(detail="Internal server error"), 500
    return render_template("500.html", title="Server Error"), 500


def render_page(template_name: str, title: str):
    return render_template(
        template_name,
        title=title,
        api_base=API_BASE,
        use_mock=USE_MOCK,
        dev_mode=DEV_MODE,
    )


@app.route("/")
def index():
    return render_page("index.html", "Welcome")


@app.route("/happyhour")
def happyhour():
    return render_page("happyhour.html", "Happy Hour")


@app.route("/login")
def login():
    return render_page("login.html", "Login")


@app.route("/auth/callback")
def auth_callback():
    return render_page("auth_callback.html", "Auth Callback")


@app.route("/auth/complete-registration")
def complete_registration():
    return render_page("complete_registration.html", "Complete Registration")


@app.route("/auth/claim-account")
def claim_account():
    return render_page("claim_account.html", "Claim Account")


@app.route("/account")
def account():
    return render_page("account.html", "Account")


@app.route("/mealbot")
def mealbot():
    return render_page("mealbot.html", "Mealbot")


@app.route("/admin")
def admin():
    return render_page("admin.html", "Admin")


# ── Reverse proxy: forward /api/* to the FastAPI backend ──────────────

PROXY_HEADERS_SKIP = frozenset(
    [
        "host",
        "content-length",
        "content-encoding",
        "transfer-encoding",
        "cookie",
    ]
)


@app.route(
    "/api/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)
def api_proxy(path):
    """Proxy all /api/ requests to the FastAPI backend, relaying cookies and
    headers so the OIDC session stays on the same origin as the frontend."""
    if not USE_PROXY:
        return Response("Proxy disabled in direct-API mode", status=404)
    # Reject path traversal attempts that could escape /api/ on the upstream
    if ".." in path or path.startswith("/"):
        return Response("Invalid path", status=400)
    target = f"{BACKEND_URL}/api/{path}"
    qs = request.query_string.decode()
    if qs:
        target += f"?{qs}"

    # Forward headers (except hop-by-hop)
    fwd = {k: v for k, v in request.headers if k.lower() not in PROXY_HEADERS_SKIP}
    fwd["X-Forwarded-For"] = request.remote_addr or ""
    fwd["X-Forwarded-Host"] = request.host
    fwd["X-Forwarded-Proto"] = request.scheme

    # Forward only the backend session cookie and OIDC anti-CSRF cookies,
    # not all cookies.  Include both plain and __Host- prefixed variants.
    FORWARDED_COOKIES = {
        SESSION_COOKIE_NAME,
        "auth_state",
        "auth_nonce",
        "__Host-auth_state",
        "__Host-auth_nonce",
    }
    cookies_to_forward = {
        k: v for k, v in request.cookies.items() if k in FORWARDED_COOKIES
    }

    try:
        resp = http_requests.request(
            method=request.method,
            url=target,
            headers=fwd,
            cookies=cookies_to_forward,
            data=request.get_data(),
            allow_redirects=False,
            timeout=30,
            stream=True,
        )
    except (ConnectionError, Timeout, ReadTimeout) as exc:
        logger.error("Backend proxy connection failed: %s", exc)
        return Response(
            jsonify(detail="Backend unavailable").get_data(),
            status=502,
            content_type="application/json",
        )

    # Guard against oversized responses from upstream (max 50 MB)
    MAX_RESPONSE_SIZE = 50 * 1024 * 1024
    content_len = resp.headers.get("content-length")
    if content_len and int(content_len) > MAX_RESPONSE_SIZE:
        resp.close()
        return Response("Upstream response too large", status=502)
    body = resp.content
    if len(body) > MAX_RESPONSE_SIZE:
        return Response("Upstream response too large", status=502)

    # Build Flask response, relaying status + body + selected headers.
    # Use resp.raw.headers (urllib3 HTTPHeaderDict) to preserve duplicate
    # Set-Cookie entries — requests' CaseInsensitiveDict silently merges them.
    excluded = {"content-encoding", "transfer-encoding", "content-length", "connection"}
    allowed = {
        "content-type",
        "set-cookie",
        "cache-control",
        "location",
        "x-request-id",
    }
    raw_headers = resp.raw.headers if hasattr(resp.raw, "headers") else resp.headers
    headers = [
        (k, v)
        for k, v in raw_headers.items()
        if k.lower() not in excluded and k.lower() in allowed
    ]
    # Ensure caches respect varying by cookie/origin
    headers.append(("Vary", "Cookie, Origin"))
    return Response(body, status=resp.status_code, headers=headers)


if __name__ == "__main__":
    app.run(debug=DEV_MODE, port=5001)

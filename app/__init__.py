from datetime import timedelta
from flask import Flask, g, jsonify, request
import hashlib
import logging
import os
import secrets
import threading
from urllib.parse import urlparse
from dotenv import load_dotenv
from flask_compress import Compress
from werkzeug.exceptions import HTTPException


# Ensure local .env values (e.g., GROQ_API_KEY) are available in all run modes.
load_dotenv()


def _is_production_env():
    return os.environ.get('FLASK_ENV', '').lower() == 'production' or bool(os.environ.get('K_SERVICE'))


# Cache of static filename -> content version, so the hash is computed once
# per file per process instead of on every url_for('static', ...) call.
_ASSET_VERSIONS: dict[str, str] = {}
_ASSET_VERSION_LOCK = threading.Lock()


def _compute_asset_version(static_folder, filename):
    """Short content version for a static file, or None if it can't be read.

    Derived from size + mtime rather than hashing file contents: it changes on
    every deploy (the container is rebuilt) without paying to read every asset
    on first request. Returning None simply omits the query parameter, so a
    missing file degrades to the old unversioned URL instead of erroring.
    """
    try:
        stat = os.stat(os.path.join(static_folder, filename))
    except OSError:
        return None
    material = f"{stat.st_size}:{stat.st_mtime_ns}".encode()
    return hashlib.sha1(material).hexdigest()[:10]


def _warm_caches():
    """Pre-warm slow one-time setup off the request path.

    The first request otherwise pays for Supabase client construction plus
    the initial Yahoo Finance TLS/cookie handshake (tens of seconds cold).
    """
    logger = logging.getLogger(__name__)
    try:
        from app.services import supabase_client
        supabase_client.is_available()  # builds the client once
    except Exception as exc:
        logger.debug("Supabase warmup skipped: %s", exc)

    try:
        from app.config import MARKET_INDICES
        from app.services import stock_data
        for markets in MARKET_INDICES.values():
            for market in markets:
                stock_data.fetch_stock_data(market['symbol'])
    except Exception as exc:
        logger.debug("Market data warmup skipped: %s", exc)


def _start_cache_warmup():
    if os.environ.get('DISABLE_CACHE_WARMUP') or 'PYTEST_CURRENT_TEST' in os.environ:
        return
    threading.Thread(target=_warm_caches, name='cache-warmup', daemon=True).start()


def create_app():
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static',
    )
    _default_max_content_length = 1024 * 1024
    _max_content_length_raw = os.environ.get('MAX_CONTENT_LENGTH')
    if _max_content_length_raw is None:
        app.config['MAX_CONTENT_LENGTH'] = _default_max_content_length
    else:
        try:
            app.config['MAX_CONTENT_LENGTH'] = int(_max_content_length_raw)
        except ValueError:
            logging.getLogger(__name__).warning(
                "Ignoring malformed MAX_CONTENT_LENGTH=%r; falling back to default of %d bytes.",
                _max_content_length_raw, _default_max_content_length,
            )
            app.config['MAX_CONTENT_LENGTH'] = _default_max_content_length

    # ── Response compression ────────────────────────────────────────────
    # Neither Flask nor Cloud Run compresses dynamic responses, so the app was
    # shipping ~100KB of unminified JS plus a 2.7k-line stylesheet uncompressed
    # on every cold visit. Only text-ish types are listed; images, fonts and
    # font-woff are already compressed and would just burn CPU.
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'text/plain', 'text/xml',
        'application/json', 'application/javascript', 'text/javascript',
        'application/xml', 'image/svg+xml',
    ]
    app.config['COMPRESS_ALGORITHM'] = ['br', 'gzip']
    app.config['COMPRESS_LEVEL'] = 6
    app.config['COMPRESS_MIN_SIZE'] = 500
    Compress(app)

    # ── Static asset cache busting ──────────────────────────────────────
    # url_for('static', filename=...) now carries a ?v=<content version>, so a
    # deploy can't leave a browser running last release's JS against this
    # release's API. Because every URL is versioned, the files themselves can
    # then be cached hard - stale content is impossible by construction.
    production = _is_production_env()
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=365) if production else timedelta(seconds=0)

    @app.url_defaults
    def _add_static_asset_version(endpoint, values):
        if endpoint != 'static' or 'filename' not in values:
            return
        filename = values['filename']
        if production:
            with _ASSET_VERSION_LOCK:
                version = _ASSET_VERSIONS.get(filename)
                if version is None:
                    version = _compute_asset_version(app.static_folder, filename)
                    if version is not None:
                        _ASSET_VERSIONS[filename] = version
        else:
            # Don't memoize in development, or editing a file would keep
            # serving the previously-hashed URL until the process restarts.
            version = _compute_asset_version(app.static_folder, filename)
        if version:
            values['v'] = version

    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key and _is_production_env():
        raise RuntimeError('SECRET_KEY must be configured for production deployments.')
    app.config['SECRET_KEY'] = secret_key or secrets.token_hex(32)

    # Session cookie hardening for account sign-in.
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = _is_production_env()
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

    # Configure logging
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    @app.before_request
    def _set_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    # Umami analytics (privacy-friendly). Set UMAMI_WEBSITE_ID to enable;
    # UMAMI_SRC defaults to Umami Cloud but can point at a self-hosted instance.
    app.config['UMAMI_WEBSITE_ID'] = os.environ.get('UMAMI_WEBSITE_ID', '').strip()
    app.config['UMAMI_SRC'] = os.environ.get(
        'UMAMI_SRC', 'https://cloud.umami.is/script.js'
    ).strip()
    _umami_parsed = urlparse(app.config['UMAMI_SRC'])
    app.config['UMAMI_ORIGIN'] = (
        f"{_umami_parsed.scheme}://{_umami_parsed.netloc}"
        if _umami_parsed.scheme and _umami_parsed.netloc else ''
    )

    @app.context_processor
    def _security_context():
        return {
            'csp_nonce': getattr(g, 'csp_nonce', ''),
            'umami_website_id': app.config.get('UMAMI_WEBSITE_ID', ''),
            'umami_src': app.config.get('UMAMI_SRC', ''),
        }

    @app.after_request
    def _set_security_headers(response):
        nonce = getattr(g, 'csp_nonce', '')
        umami_origin = app.config.get('UMAMI_ORIGIN', '') if app.config.get('UMAMI_WEBSITE_ID') else ''
        umami_src = f' {umami_origin}' if umami_origin else ''
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault(
            'Permissions-Policy',
            'accelerometer=(), ambient-light-sensor=(), autoplay=(), camera=(), '
            'display-capture=(), encrypted-media=(), geolocation=(), gyroscope=(), '
            'microphone=(), payment=(), usb=()',
        )
        if _is_production_env():
            response.headers.setdefault(
                'Strict-Transport-Security',
                'max-age=31536000; includeSubDomains; preload',
            )
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; "
            # cdnjs.cloudflare.com was only ever needed for Font Awesome, which
            # is gone (no template or script referenced a single fa-* icon), so
            # the origin is dropped from every directive rather than left open.
            f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net{umami_src}; "
            "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            f"connect-src 'self'{umami_src}; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return response

    @app.errorhandler(HTTPException)
    def _json_api_http_errors(error):
        if request.path.startswith('/api/'):
            messages = {
                404: 'Not found',
                405: 'Method not allowed',
                413: 'Request body too large',
                415: 'Unsupported media type',
            }
            return jsonify({"error": messages.get(error.code, error.name)}), error.code
        return error

    from app.routes.main import main_bp
    from app.routes.api import api_bp
    from app.routes.account import account_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(account_bp)

    _start_cache_warmup()

    return app

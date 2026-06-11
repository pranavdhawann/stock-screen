from flask import Flask, g, jsonify, request
import logging
import os
import secrets
import threading
from dotenv import load_dotenv
from werkzeug.exceptions import HTTPException


# Ensure local .env values (e.g., GROQ_API_KEY) are available in all run modes.
load_dotenv()


def _is_production_env():
    return os.environ.get('FLASK_ENV', '').lower() == 'production' or bool(os.environ.get('K_SERVICE'))


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
    app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', str(1024 * 1024)))

    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key and _is_production_env():
        raise RuntimeError('SECRET_KEY must be configured for production deployments.')
    app.config['SECRET_KEY'] = secret_key or secrets.token_hex(32)

    # Configure logging
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    @app.before_request
    def _set_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _security_context():
        return {'csp_nonce': getattr(g, 'csp_nonce', '')}

    @app.after_request
    def _set_security_headers(response):
        nonce = getattr(g, 'csp_nonce', '')
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
            f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
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

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    _start_cache_warmup()

    return app

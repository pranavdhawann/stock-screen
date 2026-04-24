from flask import Flask
import logging
import os
from dotenv import load_dotenv


# Ensure local .env values (e.g., GROQ_API_KEY) are available in all run modes.
load_dotenv()


def create_app():
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static',
    )

    # Configure logging
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    from app.routes.main import main_bp
    from app.routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    return app

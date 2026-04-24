from flask import Blueprint, render_template, jsonify
from datetime import datetime

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def home():
    return render_template('index.html')


@main_bp.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'stock-sentiment-analysis',
    }), 200


@main_bp.route('/ping')
def ping():
    return jsonify({'pong': True, 'timestamp': datetime.now().isoformat()})


@main_bp.route('/about')
def about():
    return render_template('about.html')


@main_bp.route('/sec-filings')
def sec_filings():
    return render_template('sec_filings.html')


@main_bp.route('/forecasting')
def forecasting():
    return render_template('forecasting.html')

# Use Python 3.11 slim image
FROM python:3.11-slim

WORKDIR /app

# Install system deps (gcc for C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY wsgi.py .
COPY app/ app/
COPY templates/ templates/
COPY static/ static/

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Environment (PORT is set by Cloud Run at runtime)
ENV FLASK_APP=wsgi.py \
    FLASK_ENV=production \
    PORT=8080

EXPOSE 8080

# Health check using Python (curl not available in slim)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping')" || exit 1

# Gunicorn production server
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 120 --preload wsgi:app

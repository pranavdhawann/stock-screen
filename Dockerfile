# Use Python 3.11 slim image
FROM python:3.11-slim

WORKDIR /app

# No apt-get/gcc layer: every pinned dependency in requirements.txt ships a
# manylinux wheel for Python 3.11 (Flask, Werkzeug, gunicorn, requests, groq,
# cachetools, python-dotenv, defusedxml, supabase, numpy, pandas, scikit-learn,
# torch, pyyaml), so nothing here needs to be compiled from source.

# Install Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY wsgi.py .
COPY app/ app/
COPY lstm/ lstm/
COPY templates/ templates/
COPY static/ static/

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Environment (PORT is set by Cloud Run at runtime)
#
# GUNICORN_WORKERS/THREADS are read by the CMD below so the process model can
# be retuned from the Cloud Run console without rebuilding the image. The
# default stays 1 worker: torch, pandas and scikit-learn are all resident, so
# a second worker roughly doubles the memory floor - raise it only alongside
# the instance's memory limit.
#
# OMP/MKL thread caps match app/services/forecasting.py's torch.set_num_threads
# call. Without them the math libraries spin up a thread per core underneath
# torch, which on a small Cloud Run instance means heavy contention rather
# than speed.
ENV FLASK_APP=wsgi.py \
    FLASK_ENV=production \
    PORT=8080 \
    GUNICORN_WORKERS=1 \
    GUNICORN_THREADS=8 \
    TORCH_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

EXPOSE 8080

# HEALTHCHECK is kept for local `docker run`/docker-compose convenience only.
# Cloud Run (the actual deploy target) ignores the Docker HEALTHCHECK
# instruction entirely -- it manages container health via its own
# startup/liveness probes configured on the Cloud Run service, so this
# directive has no effect in production.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping')" || exit 1

# Gunicorn production server
CMD exec gunicorn --bind :$PORT --workers $GUNICORN_WORKERS --threads $GUNICORN_THREADS --timeout 120 wsgi:app

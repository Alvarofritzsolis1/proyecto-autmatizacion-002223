# GALANT: runtime Python/OCR autocontenido para Contabo VPS (Ubuntu host).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_THREAD_LIMIT=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    HOME=/home/galant \
    XDG_CACHE_HOME=/home/galant/.cache

WORKDIR /app

# Idiomas de documentos chilenos, reconocimiento de orientacion, libs CPU/ONNX.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
       tesseract-ocr-osd libgomp1 libglib2.0-0 libgl1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY . /app
RUN useradd --uid 10001 --create-home --home-dir /home/galant \
       --shell /usr/sbin/nologin galant \
    && mkdir -p /home/galant/.cache /home/galant/.streamlit \
    && cp /app/config.toml /home/galant/.streamlit/config.toml \
    && chown -R galant:galant /home/galant /app

USER galant
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=8s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=5).read()" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", \
     "--server.enableCORS=true", \
     "--server.enableXsrfProtection=true", \
     "--browser.gatherUsageStats=false"]

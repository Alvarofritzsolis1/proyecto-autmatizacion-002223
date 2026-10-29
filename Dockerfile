# GALANT: contenedor para Cloud Run Jobs. Compilar desde la raíz.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa \
    libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install --no-cache-dir -r /app/worker/requirements.txt
COPY . /app
RUN useradd -r -u 10001 -s /usr/sbin/nologin galant \
    && chown -R galant:galant /app
USER galant
CMD ["python", "-u", "worker/worker.py", "--once", "--limit", "3"]

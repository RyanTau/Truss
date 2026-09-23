FROM python:3.12-slim-bookworm
ARG BUILD_VERSION=0.1.10
ARG BUILD_ARCH=amd64
ARG DECISION_BACKEND=laya
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="addon" io.hass.arch="${BUILD_ARCH}"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/data/huggingface
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements*.txt ./
RUN if [ "$DECISION_BACKEND" = "laya" ]; then \
      pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements.txt; \
    elif [ "$DECISION_BACKEND" = "jev" ]; then \
      pip install --no-cache-dir -r requirements-base.txt; \
    else echo "Unknown decision backend" >&2; exit 1; fi
COPY engine ./engine
COPY run.py .
EXPOSE 10350
CMD ["python", "run.py"]

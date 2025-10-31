FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY Backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/backend-requirements.txt

EXPOSE 8800

CMD ["uvicorn", "Backend.app:app", "--host", "0.0.0.0", "--port", "8800"]

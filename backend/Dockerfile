FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --upgrade pip

COPY pyproject.toml /app/
COPY app/ /app/app/
COPY scripts/ /app/scripts/

RUN pip install --no-cache-dir .

# Bake the curated dataset snapshot into the image
COPY data/curated/ /app/data/curated/

RUN mkdir -p /app/data/raw/cnrfc /app/data/raw/usgs_streamflow /app/data/raw/nhdplus

ENV PYTHONPATH=/app
ENV APP_ENV=production
ENV CURATED_DIR=/app/data/curated

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

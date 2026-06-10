FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --upgrade pip

COPY backend/pyproject.toml /app/
COPY backend/app/ /app/app/
COPY backend/scripts/ /app/scripts/

RUN pip install --no-cache-dir .

# Bake the curated dataset snapshot into the image (single source of truth: repo-root data/curated/).
#
# Cache-bust: Render's Docker layer cache was reusing a stale `COPY data/curated/`
# layer, so deploys shipped day-old data (the API served Low/30% for a beach whose
# fresh snapshot was High/30%). Render injects RENDER_GIT_COMMIT per deploy;
# referencing it in the RUN just above the COPY invalidates this layer on every new
# commit, guaranteeing the current serving.sqlite / forecasts are baked in. Each
# daily data refresh is a new commit, so this busts correctly for the real case.
ARG RENDER_GIT_COMMIT=local
RUN echo "curated data snapshot for commit ${RENDER_GIT_COMMIT}" > /app/.curated_build_stamp
COPY data/curated/ /app/data/curated/

RUN mkdir -p /app/data/raw/cnrfc /app/data/raw/usgs_streamflow /app/data/raw/nhdplus

ENV PYTHONPATH=/app
ENV APP_ENV=production
ENV CURATED_DIR=/app/data/curated

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

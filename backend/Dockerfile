FROM python:3.12-slim

# Install system dependencies (for building some scientific packages if needed)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip
RUN pip install --upgrade pip

# Copy pyproject.toml first for caching
COPY pyproject.toml /app/

# Copy the rest of the backend codebase
COPY app/ /app/app/
COPY scripts/ /app/scripts/

# Install the package and its dependencies
RUN pip install --no-cache-dir .

# Create data directories so the app has a place to write if no volume is mounted
RUN mkdir -p /app/data/curated /app/data/research /app/data/raw/cnrfc /app/data/raw/usgs_streamflow /app/data/raw/nhdplus

# Set environment variables
ENV PYTHONPATH=/app
ENV APP_ENV=production

# Expose port
EXPOSE 8000

# Start Uvicorn, listening on all interfaces
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

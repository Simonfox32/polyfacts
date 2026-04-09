FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (better caching)
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir "."

# Copy remaining application code
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Expose port
EXPOSE 8000

# Run migrations then start server
CMD ["sh", "-c", "echo 'Starting migrations...' && alembic upgrade head && echo 'Migrations done. Starting uvicorn on port ${PORT:-8000}...' && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info"]

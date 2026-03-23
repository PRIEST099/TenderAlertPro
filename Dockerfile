FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY api/ ./api/

# Ensure /data directory exists for Railway volume mount
RUN mkdir -p /data

# Expose the port (Railway injects $PORT)
EXPOSE 8000

# Run FastAPI with uvicorn
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# Use a slim Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed by PyTorch and torch-geometric
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching)
COPY requirements.txt .

# Install PyTorch FIRST (CPU-only for deployment — much smaller image)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install torch-geometric and torch-scatter AFTER torch is available
RUN pip install --no-cache-dir torch-scatter torch-geometric -f https://data.pyg.org/whl/torch-2.7.0+cpu.html

# Install remaining dependencies
RUN pip install --no-cache-dir numpy pandas scipy scikit-learn openpyxl fair-esm flask flask-cors gunicorn networkx

# Copy application code
COPY . .

# Expose port
EXPOSE 5000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# Run the Flask app with gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "300", "--workers", "1", "--threads", "2", "app:app"]

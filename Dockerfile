FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/
COPY main.py .
COPY icon.ico .

# Copy the React frontend build directory
COPY frontend/build/ ./frontend/build/

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Default port used in the application
EXPOSE 8420

# Command to run the application
CMD ["python", "main.py"]
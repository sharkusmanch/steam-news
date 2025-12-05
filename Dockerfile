# Use Python 3.11 slim image as base
FROM python:3.14-slim

# Build arguments
ARG VERSION=dev

# Labels
LABEL org.opencontainers.image.version="${VERSION}"

# Set working directory
WORKDIR /app

# Install whiptail (for interactive game selection)
RUN apt-get update && \
    apt-get install -y --no-install-recommends whiptail && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py .
COPY *.sh .
COPY SteamSteamIDs.txt .

# Make scripts executable
RUN chmod +x SteamNews.py updateAndPublish.sh

# Create directory for output files and database
RUN mkdir -p /data

# Set volume for persistent data
VOLUME ["/data"]

# Set environment variable for database location
ENV STEAM_NEWS_DATABASE_PATH=/data/SteamNews.db

# Default command - show help
CMD ["python", "SteamNews.py", "--help"]

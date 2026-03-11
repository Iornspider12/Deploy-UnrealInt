FROM python:3.12-slim

# Install minimal system dependencies for aiortc/av
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libportaudio2 \
    portaudio19-dev \
    libasound-dev \
    libsndfile1-dev \
    libavformat-dev \
    libavcodec-dev \
    libavutil-dev \
    jq \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy all app files (server.py, public folder, etc.)
COPY . .

# Copy requirements and install Python dependencies
RUN pip install --no-cache-dir -r reqs.txt

# Set default orchestrator count
ENV ORCHS=3
ENV SLOTS=3

# Expose ports for orchestrators (8001-8008)
EXPOSE 8000
EXPOSE 8001
EXPOSE 8002
EXPOSE 8003
# EXPOSE 8004
# EXPOSE 8005
# EXPOSE 8006
# EXPOSE 8007

# Use startup script to run multiple orchestrators and load balancer
RUN dos2unix ./run.sh && chmod +x ./run.sh
ENTRYPOINT [ "./run.sh" ]
FROM python:3.10-slim-bullseye

# Create app directory
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .

# Clear pipecat_fork_cache
RUN PIP_CACHE_DIR=$(pip cache dir) && \
    rm -rf $PIP_CACHE_DIR/http/https_github_com_Rolstenhouse_pipecat_git

RUN pip3 install -r requirements.txt

# Copy app source
COPY . .

# Ports to be exposed
EXPOSE 7860

# Command to run the app
CMD ["python3", "server.py"]

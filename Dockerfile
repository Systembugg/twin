FROM python:3.11-slim

# Install system dependencies needed for python packages and sandbox commands
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create workspace directory with appropriate permissions
RUN mkdir -p /workspaces && chmod 777 /workspaces

# Copy project definition and source code
COPY pyproject.toml README.md schema.sql start_render.sh ./
COPY twin ./twin

# Install the package with server and openai dependencies
RUN pip install --no-cache-dir -e ".[server,openai]"

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    TWIN_WORKSPACE_ROOT=/workspaces

EXPOSE 8000

# Default command (can be overridden by docker-compose for worker)
CMD ["uvicorn", "twin.runtime.api:build_default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

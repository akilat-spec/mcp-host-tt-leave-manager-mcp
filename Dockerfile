FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install only essential build dependencies (reduces from 63 to ~15 packages)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy only requirements first for better caching
COPY requirements.txt .

# Use Python wheels and cache for faster installs
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Set environment variables
ENV MCP_TRANSPORT=streamable-http
ENV PORT=8081
ENV MCP_REQUIRE_API_KEY=true

# Expose port
EXPOSE 8081

# Run the MCP server
CMD ["python", "main.py"]
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y build-essential libffi-dev && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Set environment variables
ENV MCP_TRANSPORT=streamable-http
ENV PORT=8080
ENV MCP_REQUIRE_API_KEY=true

# Expose port
EXPOSE 8080

# Run the MCP server
CMD ["python", "main.py"]
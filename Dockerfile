FROM python:3.11-alpine

WORKDIR /app

# Install only essential dependencies (MUCH faster - only 3 packages)
RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MCP_TRANSPORT=streamable-http
ENV PORT=8080
ENV MCP_REQUIRE_API_KEY=true

EXPOSE 8080

CMD ["python", "main.py"]
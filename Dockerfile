FROM python:3.13-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml README.md ./
COPY src/ src/
RUN uv pip install --system --no-cache .

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin/readonly-mcp-teamcity /usr/local/bin/readonly-mcp-teamcity

# Inside the container the server must listen on all interfaces to be reachable
# through a published port. Publish it on the host's loopback only
# (docker run -p 127.0.0.1:8080:8080 ...): the HTTP transport has no auth.
ENV TEAMCITY_TRANSPORT=http \
    TEAMCITY_HTTP_HOST=0.0.0.0 \
    TEAMCITY_HTTP_PORT=8080 \
    TEAMCITY_LOG_FORMAT=json \
    TEAMCITY_LOG_LEVEL=INFO

EXPOSE 8080
ENTRYPOINT ["readonly-mcp-teamcity"]

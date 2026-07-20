FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    METRO_AGENT_ROOT=/app \
    METRO_API_HOST=0.0.0.0 \
    METRO_API_PORT=8000 \
    METRO_AGENT_ENV=container

WORKDIR /app

RUN addgroup --system metro && adduser --system --ingroup metro metro

COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples
RUN python -m pip install --no-cache-dir .

RUN mkdir -p /app/artifacts/api-audits && chown -R metro:metro /app
USER metro

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["metro-agent-api"]

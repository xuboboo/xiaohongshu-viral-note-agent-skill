FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir '.[enterprise]' \
    && mkdir -p /app/data /app/output /app/playwright/.auth \
    && chown -R pwuser:pwuser /app
COPY --chown=pwuser:pwuser . .

USER pwuser
ENV APP_HOST=0.0.0.0 APP_PORT=8080 UVICORN_WORKERS=1 AUTH_REQUIRED=true PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh", "-c", "uvicorn xhs_skill.api.app:create_app --factory --host 0.0.0.0 --port ${APP_PORT:-8080} --workers ${UVICORN_WORKERS:-1}"]

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PULSE_HOME=/var/lib/pulse \
    HOME=/var/lib/pulse \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000

WORKDIR /opt/pulse
COPY pyproject.toml README.md LICENSE config.py ./
COPY analytics/*.py analytics/
COPY coach/*.py coach/
COPY coach/skills/*.py coach/skills/
COPY db/*.py db/
COPY db/repositories/*.py db/repositories/
COPY db/migrations/*.py db/migrations/
COPY db/migrations/versions/*.py db/migrations/versions/
COPY llm/*.py llm/
COPY metrics/*.py metrics/
COPY services/*.py services/
COPY scripts/*.py scripts/
COPY utils/*.py utils/
COPY web/*.py web/
COPY web/routes/*.py web/routes/
COPY web/dashboard/*.py web/dashboard/
COPY web/view_models/*.py web/view_models/
COPY worker/*.py worker/
COPY db/migrations/baseline.sql db/migrations/script.py.mako db/migrations/
COPY web/templates/*.html web/templates/
COPY web/templates/components/*.html web/templates/components/
COPY web/static/fonts/*.woff2 web/static/fonts/OFL.txt web/static/fonts/
COPY web/static/js/*.js web/static/js/LICENSE web/static/js/
COPY web/static/css/v2.css web/static/css/
COPY data/mock_activities.csv data/mock_health_metrics.csv data/
RUN pip install --no-cache-dir . \
    && groupadd --gid 10001 pulse \
    && useradd --uid 10001 --gid pulse --no-create-home pulse \
    && install -d -o pulse -g pulse -m 0700 /var/lib/pulse

USER pulse
WORKDIR /var/lib/pulse
EXPOSE 8000
CMD ["python", "-m", "web"]

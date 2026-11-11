# One image for every Python service; the compose command selects the service.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends nftables iproute2 \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir uv==0.13.7
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs libs
COPY services services
COPY analytics/pyproject.toml analytics/pyproject.toml
COPY analytics/src analytics/src
COPY engineering engineering
COPY infra/firewall infra/firewall
COPY infra/pki/make_certs.py infra/pki/make_certs.py
COPY docs/sizing-calculations.md docs/sizing-calculations.md
RUN uv sync --locked --no-dev && uv run --no-sync engdata pid
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
RUN useradd -u 10001 -m app && mkdir -p /data/collector && chown -R app /data
USER app

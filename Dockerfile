FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

# Dependencies first so code changes do not invalidate the layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY examples ./examples
COPY pyproject.toml ./

# Run as an unprivileged user; /srv/app/data holds the DB and snapshots.
RUN useradd --create-home --uid 10001 approval \
    && mkdir -p /srv/app/data/snapshots \
    && chown -R approval:approval /srv/app
USER approval

ENV APPROVAL_PACK_DATABASE_URL=sqlite:////srv/app/data/approval_pack.db \
    APPROVAL_PACK_STORAGE_DIR=/srv/app/data/snapshots

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

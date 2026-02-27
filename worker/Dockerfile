FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

ARG SYFT_VERSION=v1.31.0
ARG GRYPE_VERSION=v0.88.0

RUN curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh \
    | sh -s -- -b /usr/local/bin "${SYFT_VERSION}" \
    && curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh \
    | sh -s -- -b /usr/local/bin "${GRYPE_VERSION}"

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV RABBITMQ_HOST=host.docker.internal \
    RABBITMQ_PORT=5672 \
    RABBITMQ_USER=guest \
    RABBITMQ_PASSWORD=guest \
    RABBITMQ_VHOST=/ \
    RABBITMQ_QUEUE=scan_jobs \
    POSTGRES_HOST=host.docker.internal \
    POSTGRES_PORT=5432 \
    POSTGRES_USER=postgres \
    POSTGRES_PASSWORD=postgres \
    POSTGRES_DB=vulnsentinel \
    RUSTFS_ENDPOINT=http://host.docker.internal:9000 \
    RUSTFS_ACCESS_KEY=rustfsadmin \
    RUSTFS_SECRET_KEY=rustfsadmin \
    RUSTFS_REGION=us-east-1 \
    RUSTFS_BUCKET=sboms \
    RUSTFS_AUTO_CREATE_BUCKET=true \
    LOG_LEVEL=INFO

CMD ["sh", "-c", "alembic upgrade head && python /app/orchestrator.py"]


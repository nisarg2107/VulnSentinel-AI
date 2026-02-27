"""Infrastructure clients with credentials loaded from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import boto3
import pika
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy import URL, Engine, create_engine


def parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def default_local_service_host() -> str:
    configured = os.getenv("LOCAL_SERVICES_HOST")
    if configured:
        return configured
    if os.path.exists("/.dockerenv"):
        return "host.docker.internal"
    return "localhost"


def default_rustfs_endpoint() -> str:
    return f"http://{default_local_service_host()}:9000"


@dataclass
class RabbitMQ:
    host: str
    port: int
    user: str
    password: str
    vhost: str
    queue: str
    prefetch: int
    requeue_on_error: bool

    @classmethod
    def from_env(cls) -> "RabbitMQ":
        return cls(
            host=os.getenv("RABBITMQ_HOST", default_local_service_host()),
            port=int(os.getenv("RABBITMQ_PORT", "5672")),
            user=os.getenv("RABBITMQ_USER", "guest"),
            password=os.getenv("RABBITMQ_PASSWORD", "guest"),
            vhost=os.getenv("RABBITMQ_VHOST", "/"),
            queue=os.getenv("RABBITMQ_QUEUE", "scan_jobs"),
            prefetch=int(os.getenv("RABBITMQ_PREFETCH", "1")),
            requeue_on_error=parse_bool_env("RABBITMQ_REQUEUE_ON_ERROR", False),
        )

    def connection_parameters(self) -> pika.ConnectionParameters:
        return pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            virtual_host=self.vhost,
            credentials=pika.PlainCredentials(self.user, self.password),
        )

    def connect(self) -> pika.BlockingConnection:
        return pika.BlockingConnection(self.connection_parameters())


@dataclass
class Postgres:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_env(cls) -> "Postgres":
        return cls(
            host=os.getenv("POSTGRES_HOST", default_local_service_host()),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            database=os.getenv("POSTGRES_DB", "vulnsentinel"),
        )

    def sqlalchemy_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg2",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        )

    def create_engine(self) -> Engine:
        return create_engine(self.sqlalchemy_url(), pool_pre_ping=True)


@dataclass
class RustFS:
    endpoint: str
    access_key: str
    secret_key: str
    region: str
    bucket: str
    auto_create_bucket: bool
    _client: Any = field(init=False, repr=False)

    @classmethod
    def from_env(cls) -> "RustFS":
        return cls(
            endpoint=os.getenv("RUSTFS_ENDPOINT", default_rustfs_endpoint()),
            access_key=os.getenv("RUSTFS_ACCESS_KEY", "rustfsadmin"),
            secret_key=os.getenv("RUSTFS_SECRET_KEY", "rustfsadmin"),
            region=os.getenv("RUSTFS_REGION", "us-east-1"),
            bucket=os.getenv("RUSTFS_BUCKET", "sboms"),
            auto_create_bucket=parse_bool_env("RUSTFS_AUTO_CREATE_BUCKET", True),
        )

    def __post_init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(s3={"addressing_style": "path"}),
        )
        if self.auto_create_bucket:
            self.ensure_bucket()

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code")
            if code in {"404", "NoSuchBucket", "NotFound"}:
                self._client.create_bucket(Bucket=self.bucket)
            else:
                raise

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

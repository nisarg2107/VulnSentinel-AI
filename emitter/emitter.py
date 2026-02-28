#!/usr/bin/env python3
"""Emit mock scan jobs to RabbitMQ for local VulnSentinel flow testing."""

import argparse
import datetime as dt
import json
import os
import subprocess
import uuid

import pika


# Parse flexible CLI booleans like true/false and yes/no.
def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


# Validate digest format as sha256:<64-hex>.
def is_sha256_digest(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    digest_hex = value.split(":", 1)[1]
    return len(digest_hex) == 64 and all(c in "0123456789abcdef" for c in digest_hex.lower())


# Resolve host for local services across host and container contexts.
def default_local_service_host() -> str:
    configured = os.getenv("LOCAL_SERVICES_HOST")
    if configured:
        return configured
    if os.path.exists("/.dockerenv"):
        return "host.docker.internal"
    return "localhost"


# Resolve a real immutable digest from local docker metadata.
def resolve_digest_from_docker(image_ref: str) -> str:
    command = ["docker", "image", "inspect", image_ref, "--format", "{{json .RepoDigests}}"]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ValueError("docker CLI not found; provide --image-digest explicitly") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        details = f": {stderr}" if stderr else ""
        raise ValueError(f"docker image inspect failed for '{image_ref}'{details}") from exc

    try:
        repo_digests = json.loads(result.stdout.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unable to parse docker inspect output for '{image_ref}'") from exc

    if not isinstance(repo_digests, list):
        raise ValueError(f"No RepoDigests found for '{image_ref}'")

    for entry in repo_digests:
        if not isinstance(entry, str):
            continue
        if "@sha256:" in entry:
            digest = entry.split("@", 1)[1]
            if is_sha256_digest(digest):
                return digest

    raise ValueError(
        f"No immutable sha256 digest found for '{image_ref}'. "
        "Pull the image first or pass --image-digest."
    )


# Normalize image_ref and digest while enforcing immutable digest identity.
def resolve_image_fields(image_ref: str, image_digest: str | None) -> tuple[str, str]:
    digest_from_ref = None
    if "@sha256:" in image_ref:
        digest_from_ref = image_ref.split("@", 1)[1]

    if image_digest:
        digest = image_digest
    elif digest_from_ref:
        digest = digest_from_ref
    else:
        digest = resolve_digest_from_docker(image_ref)

    if not is_sha256_digest(digest):
        raise ValueError("image_digest must be a valid sha256 digest (sha256:<64-hex>)")

    if "@sha256:" in image_ref:
        full_ref = image_ref
    else:
        full_ref = f"{image_ref}@{digest}"

    return full_ref, digest


# Build CLI parser for test job emission.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a scan job message to RabbitMQ")

    parser.add_argument(
        "--image-ref",
        "--image",
        dest="image_ref",
        required=True,
        help="Container image reference. If digest is missing, it must be resolvable via docker inspect.",
    )
    parser.add_argument(
        "--image-digest",
        default=None,
        help="Optional explicit immutable digest in format sha256:<64-hex>",
    )
    parser.add_argument(
        "--environment",
        default="local-docker-test",
        help="Context environment label",
    )
    parser.add_argument(
        "--is-exposed-public",
        "--exposed",
        dest="is_exposed_public",
        type=parse_bool,
        default=True,
        help="Whether the workload is publicly exposed (true/false)",
    )
    parser.add_argument(
        "--is-privileged",
        type=parse_bool,
        default=False,
        help="Whether the workload runs privileged (true/false)",
    )

    parser.add_argument("--queue", default=os.getenv("RABBITMQ_QUEUE", "scan_jobs"))
    parser.add_argument("--exchange", default=os.getenv("RABBITMQ_EXCHANGE", ""))
    parser.add_argument("--routing-key", default=os.getenv("RABBITMQ_ROUTING_KEY", "scan.trigger"))

    parser.add_argument("--rabbitmq-host", default=os.getenv("RABBITMQ_HOST", default_local_service_host()))
    parser.add_argument("--rabbitmq-port", type=int, default=int(os.getenv("RABBITMQ_PORT", "5672")))
    parser.add_argument("--rabbitmq-user", default=os.getenv("RABBITMQ_USER", "guest"))
    parser.add_argument("--rabbitmq-password", default=os.getenv("RABBITMQ_PASSWORD", "guest"))
    parser.add_argument("--rabbitmq-vhost", default=os.getenv("RABBITMQ_VHOST", "/"))

    return parser


# Create and publish one durable scan job message.
def main() -> int:
    args = build_parser().parse_args()

    try:
        image_ref, image_digest = resolve_image_fields(args.image_ref, args.image_digest)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    payload = {
        "job_id": str(uuid.uuid4()),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "image_ref": image_ref,
        "image_digest": image_digest,
        "context": {
            "environment": args.environment,
            "is_exposed_public": args.is_exposed_public,
            "is_privileged": args.is_privileged,
        },
    }

    credentials = pika.PlainCredentials(args.rabbitmq_user, args.rabbitmq_password)
    params = pika.ConnectionParameters(
        host=args.rabbitmq_host,
        port=args.rabbitmq_port,
        virtual_host=args.rabbitmq_vhost,
        credentials=credentials,
    )

    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue=args.queue, durable=True)

    if args.exchange:
        channel.exchange_declare(exchange=args.exchange, exchange_type="direct", durable=True)
        channel.queue_bind(queue=args.queue, exchange=args.exchange, routing_key=args.routing_key)
        publish_exchange = args.exchange
        publish_routing_key = args.routing_key
    else:
        publish_exchange = ""
        publish_routing_key = args.queue

    body = json.dumps(payload)
    channel.basic_publish(
        exchange=publish_exchange,
        routing_key=publish_routing_key,
        body=body,
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
        ),
    )

    connection.close()

    print("Published scan job")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

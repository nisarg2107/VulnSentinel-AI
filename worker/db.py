"""PostgreSQL models and repository access."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, func, text, update
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from infra import Postgres


class Base(DeclarativeBase):
    pass


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    image_digest: Mapped[str] = mapped_column(nullable=False, unique=True)
    image_name: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'queued'"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    error: Mapped[str | None] = mapped_column(nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    tool_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    sbom_object_key: Mapped[str | None] = mapped_column(nullable=True)
    sbom_sha256: Mapped[str | None] = mapped_column(nullable=True)
    sbom_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    report_object_key: Mapped[str | None] = mapped_column(nullable=True)
    report_sha256: Mapped[str | None] = mapped_column(nullable=True)
    report_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ScanResult(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    vuln_id: Mapped[str] = mapped_column(nullable=False)
    package_name: Mapped[str] = mapped_column(nullable=False)
    package_version: Mapped[str | None] = mapped_column(nullable=True)
    package_type: Mapped[str | None] = mapped_column(nullable=True)
    package_path: Mapped[str | None] = mapped_column(nullable=True)
    raw_severity: Mapped[str] = mapped_column(nullable=False)
    effective_severity: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    vex_justification: Mapped[str | None] = mapped_column(nullable=True)
    fix_version: Mapped[str | None] = mapped_column(nullable=True)
    cvss_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    raw_finding: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Database:
    _session_factory: sessionmaker[Session] | None = None

    def __init__(self, postgres: Postgres) -> None:
        if Database._session_factory is None:
            Database._session_factory = sessionmaker(
                bind=postgres.create_engine(),
                autoflush=False,
                expire_on_commit=False,
                class_=Session,
            )
        self.session = Database._session_factory()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()

    def upsert_asset(self, image_digest: str, image_name: str) -> int:
        stmt = (
            insert(Asset)
            .values(image_digest=image_digest, image_name=image_name)
            .on_conflict_do_update(
                index_elements=[Asset.image_digest],
                set_={"image_name": image_name},
            )
            .returning(Asset.id)
        )
        return int(self.session.execute(stmt).scalar_one())

    def insert_scan(
        self,
        asset_id: int,
        job_id: str | None,
        context: dict[str, Any],
        tool_versions: dict[str, Any],
    ) -> int:
        stmt = (
            insert(Scan)
            .values(
                asset_id=asset_id,
                job_id=job_id,
                status="running",
                context=context,
                tool_versions=tool_versions,
            )
            .returning(Scan.id)
        )
        return int(self.session.execute(stmt).scalar_one())

    def complete_scan(
        self,
        scan_id: int,
        tool_versions: dict[str, Any],
        sbom_key: str,
        sbom_data: bytes,
        report_key: str,
        report_data: bytes,
    ) -> None:
        stmt = (
            update(Scan)
            .where(Scan.id == scan_id)
            .values(
                status="completed",
                finished_at=func.now(),
                tool_versions=tool_versions,
                sbom_object_key=sbom_key,
                sbom_sha256=self.sha256_hex(sbom_data),
                sbom_bytes=len(sbom_data),
                report_object_key=report_key,
                report_sha256=self.sha256_hex(report_data),
                report_bytes=len(report_data),
                error=None,
            )
        )
        self.session.execute(stmt)

    def fail_scan(self, scan_id: int, error: str) -> None:
        stmt = (
            update(Scan)
            .where(Scan.id == scan_id)
            .values(
                status="failed",
                finished_at=func.now(),
                error=error[:4000],
            )
        )
        self.session.execute(stmt)

    def insert_findings(self, scan_id: int, findings: list[dict[str, Any]]) -> None:
        if not findings:
            return

        rows = [
            {
                "scan_id": scan_id,
                "vuln_id": finding["vuln_id"],
                "package_name": finding["package_name"],
                "package_version": finding["package_version"],
                "package_type": finding["package_type"],
                "package_path": finding["package_path"],
                "raw_severity": finding["raw_severity"],
                "effective_severity": finding["effective_severity"],
                "status": finding["status"],
                "vex_justification": finding["vex_justification"],
                "fix_version": finding["fix_version"],
                "cvss_score": finding["cvss_score"],
                "raw_finding": finding["raw_finding"],
            }
            for finding in findings
        ]

        stmt = insert(ScanResult).values(rows).on_conflict_do_nothing()
        self.session.execute(stmt)

    @staticmethod
    def sha256_hex(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()



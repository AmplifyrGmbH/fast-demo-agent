from sqlalchemy import (
    Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    build_type: Mapped[str] = mapped_column(String, default="domain")
    slug: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pipeline status
    status: Mapped[str] = mapped_column(String, default="pending")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 1: Scraping
    scraped_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_images: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String, nullable=True)
    screenshot_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Phase 2: Google Maps
    maps_found: Mapped[bool] = mapped_column(Boolean, default=False)
    maps_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Phase 3: Analyse
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Phase 4-5: Build
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    public_url: Mapped[str | None] = mapped_column(String, nullable=True)
    evaluator_rounds: Mapped[int] = mapped_column(Integer, default=0)

    # Error
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    versions: Mapped[list["BuildVersion"]] = relationship(
        "BuildVersion", back_populates="build", cascade="all, delete-orphan", order_by="BuildVersion.version"
    )


class BuildVersion(Base):
    __tablename__ = "build_versions"
    __table_args__ = (UniqueConstraint("build_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    build_id: Mapped[int] = mapped_column(Integer, ForeignKey("builds.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    html_url: Mapped[str] = mapped_column(String, nullable=False)
    refinement_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    build: Mapped["Build"] = relationship("Build", back_populates="versions")

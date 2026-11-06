from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db import Base

class ContactMessage(Base):
    __tablename__ = "contact_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_contact_messages_ip_created", "ip_hash", "created_at"),)

class PortfolioProject(Base):
    __tablename__ = "portfolio_projects"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tech_stack: Mapped[str] = mapped_column(Text, nullable=False, default="")
    repository_url: Mapped[str | None] = mapped_column(String(500))
    demo_url: Mapped[str | None] = mapped_column(String(500))
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class ProjectView(Base):
    __tablename__ = "project_views"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    referrer: Mapped[str | None] = mapped_column(String(500))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

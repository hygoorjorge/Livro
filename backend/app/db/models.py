from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionStatus(str, Enum):
    created = "created"
    parsing = "parsing"
    detecting = "detecting"
    reviewing = "reviewing"
    verifying = "verifying"
    exported = "exported"
    failed = "failed"


class ParagraphKind(str, Enum):
    body = "body"
    footnote = "footnote"
    toc = "toc"
    index = "index"
    block_quote = "block_quote"
    caption = "caption"
    header = "header"
    footer = "footer"
    unknown = "unknown"


class MentionStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    dismissed = "dismissed"
    awaiting_user_decision = "awaiting_user_decision"


class ProposalStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    edited = "edited"


class FigureStatus(str, Enum):
    pending = "pending"
    kept = "kept"
    replaced = "replaced"


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    pdf_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default=SessionStatus.created.value)
    hash_original: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hash_final: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    pages: Mapped[list["Page"]] = relationship(back_populates="session", cascade="all, delete")


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    page_num: Mapped[int] = mapped_column(Integer)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)

    session: Mapped[Session] = relationship(back_populates="pages")
    spans: Mapped[list["TextSpan"]] = relationship(back_populates="page", cascade="all, delete")
    paragraphs: Mapped[list["Paragraph"]] = relationship(
        back_populates="page", cascade="all, delete"
    )
    figures: Mapped[list["Figure"]] = relationship(back_populates="page", cascade="all, delete")

    __table_args__ = (UniqueConstraint("session_id", "page_num"),)


class TextSpan(Base):
    __tablename__ = "text_spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    span_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    bbox_x0: Mapped[float] = mapped_column(Float)
    bbox_y0: Mapped[float] = mapped_column(Float)
    bbox_x1: Mapped[float] = mapped_column(Float)
    bbox_y1: Mapped[float] = mapped_column(Float)
    font_name: Mapped[str] = mapped_column(String(128))
    font_size: Mapped[float] = mapped_column(Float)
    color: Mapped[int] = mapped_column(Integer, default=0)
    flags: Mapped[int] = mapped_column(Integer, default=0)

    page: Mapped[Page] = relationship(back_populates="spans")


class Paragraph(Base):
    __tablename__ = "paragraphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    paragraph_index: Mapped[int] = mapped_column(Integer)
    span_ids_json: Mapped[list[int]] = mapped_column(JSON)
    full_text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default=ParagraphKind.body.value)
    protected: Mapped[bool] = mapped_column(Boolean, default=False)

    page: Mapped[Page] = relationship(back_populates="paragraphs")
    mentions: Mapped[list["Mention"]] = relationship(
        back_populates="paragraph", cascade="all, delete"
    )

    __table_args__ = (UniqueConstraint("page_id", "paragraph_index"),)


class Law(Base):
    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    source_text: Mapped[str] = mapped_column(Text)
    source_pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LawMapping(Base):
    __tablename__ = "law_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    obsolete_ref: Mapped[str] = mapped_column(String(128), unique=True)
    vigent_law_id: Mapped[int] = mapped_column(ForeignKey("laws.id"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Mention(Base):
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(ForeignKey("paragraphs.id", ondelete="CASCADE"))
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(String(255))
    detected_ref: Mapped[str] = mapped_column(String(128))
    classifier_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classifier_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_historical: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default=MentionStatus.pending.value)

    paragraph: Mapped[Paragraph] = relationship(back_populates="mentions")
    proposals: Mapped[list["Proposal"]] = relationship(
        back_populates="mention", cascade="all, delete"
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mention_id: Mapped[int] = mapped_column(ForeignKey("mentions.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16))
    original_text: Mapped[str] = mapped_column(Text)
    proposed_text: Mapped[str] = mapped_column(Text)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    claude_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_human_check: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default=ProposalStatus.pending.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    mention: Mapped[Mention] = relationship(back_populates="proposals")
    edits: Mapped[list["Edit"]] = relationship(back_populates="proposal", cascade="all, delete")


class Edit(Base):
    __tablename__ = "edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"))
    final_text: Mapped[str] = mapped_column(Text)
    edited_by: Mapped[str] = mapped_column(String(64), default="user")
    edited_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    proposal: Mapped[Proposal] = relationship(back_populates="edits")


class Figure(Base):
    __tablename__ = "figures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    bbox_x0: Mapped[float] = mapped_column(Float)
    bbox_y0: Mapped[float] = mapped_column(Float)
    bbox_x1: Mapped[float] = mapped_column(Float)
    bbox_y1: Mapped[float] = mapped_column(Float)
    image_hash: Mapped[str] = mapped_column(String(128))
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspicion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=FigureStatus.pending.value)
    replacement_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    page: Mapped[Page] = relationship(back_populates="figures")


class ChangeLog(Base):
    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    ref_id: Mapped[int] = mapped_column(Integer)
    before: Mapped[str | None] = mapped_column(Text, nullable=True)
    after: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="user")
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    total_diffs: Mapped[int] = mapped_column(Integer, default=0)
    unauthorized_diffs_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)

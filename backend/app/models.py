from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    __tablename__ = 'instruments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    status: Mapped[str] = mapped_column(String(32), default='uploaded', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    corrected_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed_key: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    document: Mapped['Document'] = relationship(back_populates='instrument', uselist=False)
    extractions: Mapped[list['Extraction']] = relationship(back_populates='instrument', order_by='Extraction.created_at')
    findings: Mapped[list['Finding']] = relationship(back_populates='instrument')
    reviews: Mapped[list['ReviewDecision']] = relationship(back_populates='instrument')


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    instrument_id: Mapped[str] = mapped_column(ForeignKey('instruments.id'), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_name: Mapped[str] = mapped_column(String(80), unique=True)
    page_count: Mapped[int] = mapped_column(Integer)
    instrument: Mapped[Instrument] = relationship(back_populates='document')


class Extraction(Base):
    __tablename__ = 'extractions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    instrument_id: Mapped[str] = mapped_column(ForeignKey('instruments.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    mode: Mapped[str] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    page_texts: Mapped[list] = mapped_column(JSON)
    instrument: Mapped[Instrument] = relationship(back_populates='extractions')


class Finding(Base):
    __tablename__ = 'findings'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    instrument_id: Mapped[str] = mapped_column(ForeignKey('instruments.id'), index=True)
    rule_id: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(16))
    field: Mapped[str | None] = mapped_column(String(80), nullable=True)
    observed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    instrument: Mapped[Instrument] = relationship(back_populates='findings')


class ReviewDecision(Base):
    __tablename__ = 'review_decisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    instrument_id: Mapped[str] = mapped_column(ForeignKey('instruments.id'), index=True)
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    instrument: Mapped[Instrument] = relationship(back_populates='reviews')


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    instrument_id: Mapped[str] = mapped_column(ForeignKey('instruments.id'), index=True)
    action: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(120))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    reason: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


def configure_sqlite(engine):
    if engine.dialect.name != 'sqlite':
        return

    @event.listens_for(engine, 'connect')
    def configure_connection(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=15000')


def protect_history(engine):
    if engine.dialect.name == 'sqlite':
        with engine.begin() as conn:
            for table in ('audit_events', 'extractions', 'review_decisions'):
                for operation in ('UPDATE', 'DELETE'):
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'History is append-only'); END"))

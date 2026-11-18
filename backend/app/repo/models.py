"""Database tables — PLAN §6. Portable types: JSON (JSONB on Postgres), Numeric for money.

Decisions are append-only (an override is a new decisions row linked to the original
plus an overrides row with a mandatory comment, policy 8.1); audit_events is
append-only; batch runs are isolated (their own requirement and PO namespace).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(20, 6)


def _now() -> Any:
    return func.now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    role: Mapped[str] = mapped_column(String(32))  # REQUESTER | BUYER | PROCUREMENT_ADMIN


class PlantRow(Base):
    __tablename__ = "plants"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))


class ItemRow(Base):
    __tablename__ = "items"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(String(255))
    uom: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(80))
    item_type: Mapped[str] = mapped_column(String(32))
    standard_price: Mapped[Decimal] = mapped_column(Money)
    search_vector: Mapped[str] = mapped_column(Text, default="")


class SupplierRow(Base):
    __tablename__ = "suppliers"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80), default="")
    categories: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(16))
    on_time_pct: Mapped[Decimal] = mapped_column(Money)
    quality_rating: Mapped[Decimal] = mapped_column(Money)


class POHistoryRow(Base):
    __tablename__ = "po_history"
    po_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    po_date: Mapped[date] = mapped_column(Date)
    supplier_id: Mapped[str] = mapped_column(String(16), index=True)
    item_code: Mapped[str] = mapped_column(String(32), index=True)
    qty: Mapped[Decimal] = mapped_column(Money)
    uom: Mapped[str] = mapped_column(String(16))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    plant: Mapped[str] = mapped_column(String(16))
    delivered_on_time: Mapped[bool] = mapped_column(Boolean)


class ContractRow(Base):
    __tablename__ = "contracts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(16))
    supplier_name: Mapped[str] = mapped_column(String(120), default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    value_cap: Mapped[Decimal] = mapped_column(Money)
    consumed_at_register: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    source: Mapped[str] = mapped_column(String(16))  # REGISTER | PDF
    plants: Mapped[list[str]] = mapped_column(JSONType, default=list)
    pdf_object: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    pdf_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    register_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    lines: Mapped[list[ContractLineRow]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="ContractLineRow.item_code")


class ContractLineRow(Base):
    __tablename__ = "contract_lines"
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), primary_key=True)
    item_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    uom: Mapped[str] = mapped_column(String(16), default="")
    rate: Mapped[Decimal] = mapped_column(Money)
    contract: Mapped[ContractRow] = relationship(back_populates="lines")


class ContractLedgerRow(Base):
    __tablename__ = "contract_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id"), index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    kind: Mapped[str] = mapped_column(String(16))  # COMMIT | REVERSAL
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class PolicyVersionRow(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))  # DRAFT | PENDING | ACTIVE | SUPERSEDED | REJECTED
    body: Mapped[dict[str, Any]] = mapped_column(JSONType)
    body_hash: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("policy_versions.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PolicyAmendmentRow(Base):
    __tablename__ = "policy_amendments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    source_kind: Mapped[str] = mapped_column(String(16))  # DOC | CHAT | EDITOR
    source_text: Mapped[str] = mapped_column(Text, default="")
    source_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ops: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    questions: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    summary: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    lint: Mapped[list[str]] = mapped_column(JSONType, default=list)
    errors: Mapped[list[str]] = mapped_column(JSONType, default=list)
    ai_meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    base_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_versions.id"), nullable=True)
    proposed_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # PROPOSED | INVALID | APPROVED | REJECTED
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class PRHeaderRow(Base):
    __tablename__ = "pr_headers"
    pr_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    requester: Mapped[str] = mapped_column(String(80))
    department: Mapped[str] = mapped_column(String(80), default="")
    source: Mapped[str] = mapped_column(String(16))  # CHAT | CSV | API
    chat_session_id: Mapped[int | None] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True)
    lines: Mapped[list[PRLineRow]] = relationship(back_populates="header", order_by="PRLineRow.line",
                                                   cascade="all, delete-orphan")


class PRLineRow(Base):
    __tablename__ = "pr_lines"
    pr_no: Mapped[str] = mapped_column(ForeignKey("pr_headers.pr_no", ondelete="CASCADE"), primary_key=True)
    line: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant: Mapped[str] = mapped_column(String(16))
    item_code_input: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    qty: Mapped[Decimal] = mapped_column(Money)
    uom: Mapped[str] = mapped_column(String(16), default="")
    est_unit_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    need_by: Mapped[date] = mapped_column(Date)
    urgency: Mapped[str] = mapped_column(String(16), default="Normal")
    resolved_item_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_score: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    flags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    header: Mapped[PRHeaderRow] = relationship(back_populates="lines")


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[str] = mapped_column(String(16))  # BATCH | LIVE | IMPACT
    input_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_csv: Mapped[str] = mapped_column(Text, default="")
    policy_pin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class RequirementRow(Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("run_id", "group_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    group_code: Mapped[str] = mapped_column(String(32))
    item_code: Mapped[str] = mapped_column(String(32))
    plant: Mapped[str] = mapped_column(String(16))
    req_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    value: Mapped[Decimal] = mapped_column(Money)
    policy_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_versions.id"), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | APPROVED
    lines: Mapped[list[RequirementLineRow]] = relationship(back_populates="requirement", cascade="all, delete-orphan",
                                                            order_by="RequirementLineRow.position")


class RequirementLineRow(Base):
    __tablename__ = "requirement_lines"
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True)
    pr_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    line: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    row_index: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    requirement: Mapped[RequirementRow] = relationship(back_populates="lines")


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    route: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    value: Mapped[Decimal] = mapped_column(Money)
    suggested: Mapped[list[str]] = mapped_column(JSONType, default=list)
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    clause: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    po_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    flags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16))  # PROPOSED | OVERRIDDEN (row kind; immutable)
    override_of: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(80), default="engine")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class OverrideRow(Base):
    __tablename__ = "overrides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"))
    new_decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    new_route: Mapped[str] = mapped_column(String(32))
    new_supplier_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    by: Mapped[str] = mapped_column(String(80))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class PurchaseOrderRow(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("run_id", "po_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_code: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(16))
    plant: Mapped[str] = mapped_column(String(16))
    route: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(16), default="PROPOSED")  # PROPOSED | APPROVED | ISSUED
    created_by: Mapped[str] = mapped_column(String(80), default="engine")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lines: Mapped[list[POLineRow]] = relationship(back_populates="po", cascade="all, delete-orphan")


class POLineRow(Base):
    __tablename__ = "po_lines"
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True)
    item_code: Mapped[str] = mapped_column(String(32))
    qty: Mapped[Decimal] = mapped_column(Money)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)
    po: Mapped[PurchaseOrderRow] = relationship(back_populates="lines")


class SourcingEventRow(Base):
    __tablename__ = "sourcing_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # RFQ | RFP | CAPEX | NEW_ITEM | other route
    suggested: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(16), default="LAUNCHED")
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ChatSessionRow(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(16), default="INTAKE")  # INTAKE | POLICY
    state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now(), onupdate=_now())


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())

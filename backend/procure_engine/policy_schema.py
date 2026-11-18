"""Typed policy document (the DSL) — PLAN §4.2.

Every number in the policy is a named parameter; rules are an ordered list whose
first match decides (policy §5); conditions are a small expression language over
the fact registry (§4.3); outcomes are data, so new routes need no code.
`load_policy` parses *and* semantically validates (unknown fact/op/param/item-set
→ error at load time, never at run time).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    PlainSerializer,
    Tag,
    ValidationError,
    field_validator,
    model_validator,
)

from .money import to_decimal


def _num_out(value: Decimal) -> int | float:
    """Serialise Decimals as JSON numbers (ints when integral)."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


Num = Annotated[Decimal, BeforeValidator(lambda v: to_decimal(v)), PlainSerializer(_num_out, when_used="json")]

OPS: tuple[str, ...] = (
    "eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "contains", "matches", "exists",
)
Op = Literal["eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "contains", "matches", "exists"]

SUPPLIER_STRATEGY_PATTERN = r"^(contract|none|preferred:[1-9]\d*|fixed:[A-Za-z0-9_-]+)$"
PRICE_STRATEGIES = ("contract_rate", "reference_price", "last_po_price", "standard_price")
VALUATION_SOURCES = ("contract_rate", "last_po_price", "standard_price")
ROUTE_PATTERN = r"^[A-Z][A-Z0-9_]*$"


class PolicyError(ValueError):
    """A policy document failed schema or semantic validation."""

    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)


# ----------------------------------------------------------------------------- conditions


class Leaf(_Strict):
    fact: str
    op: Op
    value: Any = None
    param: str | None = None

    @model_validator(mode="after")
    def _value_or_param(self) -> Leaf:
        if self.op == "exists":
            return self
        if (self.value is None) == (self.param is None):
            raise ValueError(f"condition on {self.fact!r} needs exactly one of 'value' or 'param'")
        if self.op == "between" and self.param is None and (
            not isinstance(self.value, list) or len(self.value) != 2
        ):
            raise ValueError("'between' needs value [low, high]")
        if self.op in ("in", "not_in") and self.param is None and not isinstance(self.value, list):
            raise ValueError(f"'{self.op}' needs a list value")
        return self


class AllOf(_Strict):
    all_: list[Condition] = Field(alias="all", min_length=1)


class AnyOf(_Strict):
    any_: list[Condition] = Field(alias="any", min_length=1)


class NotOf(_Strict):
    not_: Condition = Field(alias="not")


class Always(_Strict):
    always: Literal[True]


def _condition_kind(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("all", "any", "not", "always"):
            if key in value:
                return key
        if "fact" in value:
            return "leaf"
        return None
    if isinstance(value, Leaf):
        return "leaf"
    if isinstance(value, AllOf):
        return "all"
    if isinstance(value, AnyOf):
        return "any"
    if isinstance(value, NotOf):
        return "not"
    if isinstance(value, Always):
        return "always"
    return None


Condition = Annotated[
    Annotated[Leaf, Tag("leaf")]
    | Annotated[AllOf, Tag("all")]
    | Annotated[AnyOf, Tag("any")]
    | Annotated[NotOf, Tag("not")]
    | Annotated[Always, Tag("always")],
    Discriminator(_condition_kind),
]

AllOf.model_rebuild()
AnyOf.model_rebuild()
NotOf.model_rebuild()


# ----------------------------------------------------------------------------- rules


class Outcome(_Strict):
    decision: Literal["PO", "SOURCING_REQUEST"]
    route: str = Field(pattern=ROUTE_PATTERN)
    supplier: str | None = Field(default=None, pattern=SUPPLIER_STRATEGY_PATTERN)
    price: Literal["contract_rate", "reference_price", "last_po_price", "standard_price"] | None = None
    suggest: int = Field(default=0, ge=0, le=20)
    flags: list[str] = Field(default_factory=list)
    requires_approval: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Outcome:
        if self.decision == "PO":
            if not self.supplier or self.supplier == "none":
                raise ValueError(f"route {self.route}: a PO outcome needs a supplier strategy")
            if not self.price:
                raise ValueError(f"route {self.route}: a PO outcome needs a price strategy")
            if self.price == "contract_rate" and self.supplier != "contract":
                raise ValueError(f"route {self.route}: price 'contract_rate' requires supplier 'contract'")
        else:
            if self.supplier not in (None, "none") or self.price is not None:
                raise ValueError(f"route {self.route}: a sourcing outcome has no supplier or price")
        return self


class Rule(_Strict):
    id: str = Field(min_length=1)
    clause: str = ""
    name: str = Field(min_length=1)
    description: str = ""
    enabled: bool = True
    when: Condition
    then: Outcome


# ----------------------------------------------------------------------------- sections


class ParamDef(_Strict):
    value: Num
    unit: str = ""
    label: str = ""
    clause: str = ""

    @field_validator("value", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return to_decimal(v)


class RequirementSection(_Strict):
    emergency_urgencies: list[str] = Field(min_length=1)


class Replacement(_Strict):
    find: str = Field(min_length=1)
    replace: str


class NoisePhrase(_Strict):
    pattern: str = Field(min_length=1)
    flag: str | None = None


class MatchingSection(_Strict):
    clause: str = ""
    threshold: Num
    numeric_guard: bool = True
    replacements: list[Replacement] = Field(default_factory=list)
    noise_phrases: list[NoisePhrase] = Field(default_factory=list)
    abbreviations: dict[str, str] = Field(default_factory=dict)


class SupplierOverride(_Strict):
    supplier_id: str
    status: str
    reason: str = ""
    effective_from: date | None = None
    effective_to: date | None = None


class SupplierEligibility(_Strict):
    clause: str = ""
    allowed_statuses: list[str] = Field(min_length=1)
    overrides: list[SupplierOverride] = Field(default_factory=list)


class ItemSet(_Strict):
    label: str = ""
    codes: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    suppliers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_empty(self) -> ItemSet:
        if not (self.codes or self.patterns or self.categories):
            raise ValueError("an item set needs codes, patterns or categories")
        return self


CLUB_KEYS = ("item_code", "plant", "department", "requester")


class ClubbingSection(_Strict):
    clause: str = ""
    enabled: bool = True
    key: list[Literal["item_code", "plant", "department", "requester"]] = Field(min_length=1)
    anchor: Literal["first_line"] = "first_line"
    join: Literal["earliest"] = "earliest"
    created_within_param: str
    need_by_within_param: str
    never_club_when: Condition | None = None


class ValuationSection(_Strict):
    clause: str = ""
    sources: list[Literal["contract_rate", "last_po_price", "standard_price"]] = Field(min_length=1)
    last_po_lookback_param: str
    new_item: Literal["requester_estimate"] = "requester_estimate"


class ContractsSection(_Strict):
    clause: str = ""
    selection: Literal["lowest_rate_with_ceiling"] = "lowest_rate_with_ceiling"
    consume_order: Literal["requirement_date"] = "requirement_date"
    tolerance_param: str


class RecencyBand(_Strict):
    within_days: int = Field(ge=0)
    score: Num


class RatingScales(_Strict):
    on_time_pct: Num
    quality_rating: Num


class RankingWeights(_Strict):
    frequency: Num
    recency: Num
    contract: Num
    on_time: Num
    quality: Num


class PreferredSection(_Strict):
    clause: str = ""
    lookback_param: str
    include_contract_holders: bool = True
    weights: RankingWeights
    frequency: Literal["relative_to_max"] = "relative_to_max"
    recency_bands: list[RecencyBand]
    rating_scales: RatingScales
    tie_breakers: list[Literal["last_po_date_desc", "po_count_desc", "supplier_id_asc"]]
    reference_price: list[Literal["latest_po_in_window", "latest_contract_rate"]] = Field(min_length=1)
    export_top: int = Field(ge=1)


class TopupWeights(_Strict):
    on_time: Num
    quality: Num


class SuggestionsSection(_Strict):
    clause: str = ""
    topup: Literal["category_by_delivery_quality", "none"] = "category_by_delivery_quality"
    topup_weights: TopupWeights
    new_item: Literal["none"] = "none"


class ConsolidationSection(_Strict):
    clause: str = ""
    enabled: bool = True
    key: list[Literal["supplier_id", "plant", "route"]] = Field(min_length=1)
    anchor: Literal["first_requirement"] = "first_requirement"
    join: Literal["earliest"] = "earliest"
    window_param: str
    exclude_routes: list[str] = Field(default_factory=list)


class ReviewFlags(_Strict):
    possible_duplicate_minutes: int = Field(ge=0)
    description_mismatch_below: Num


class RouteInfo(_Strict):
    label: str = ""
    description: str = ""


class Policy(_Strict):
    policy_id: str
    version: str = Field(min_length=1)
    effective_from: date
    title: str = ""
    params: dict[str, ParamDef]
    requirement: RequirementSection
    matching: MatchingSection
    supplier_eligibility: SupplierEligibility
    item_sets: dict[str, ItemSet] = Field(default_factory=dict)
    clubbing: ClubbingSection
    valuation: ValuationSection
    contracts: ContractsSection
    preferred_suppliers: PreferredSection
    suggestions: SuggestionsSection
    consolidation: ConsolidationSection
    review_flags: ReviewFlags
    routes: dict[str, RouteInfo] = Field(default_factory=dict)
    rules: list[Rule] = Field(min_length=1)

    # -- helpers --------------------------------------------------------------------------
    def param(self, name: str) -> Decimal:
        try:
            return self.params[name].value
        except KeyError as exc:
            raise PolicyError([f"unknown param {name!r}"]) from exc

    def param_int(self, name: str) -> int:
        return int(self.param(name))

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise PolicyError([f"unknown rule {rule_id!r}"])

    def route_label(self, route: str) -> str:
        info = self.routes.get(route)
        return info.label if info and info.label else route.replace("_", " ").title()

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_defaults=False)

    def body_hash(self) -> str:
        """Hash of the policy content excluding identity fields (duplicate detection)."""
        body = self.to_json_dict()
        for key in ("version", "effective_from", "title"):
            body.pop(key, None)
        return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def walk_leaves(cond: Any) -> list[Leaf]:
    """All leaf conditions inside a condition tree."""
    if isinstance(cond, Leaf):
        return [cond]
    if isinstance(cond, AllOf):
        return [leaf for c in cond.all_ for leaf in walk_leaves(c)]
    if isinstance(cond, AnyOf):
        return [leaf for c in cond.any_ for leaf in walk_leaves(c)]
    if isinstance(cond, NotOf):
        return walk_leaves(cond.not_)
    return []


def _format_validation_error(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"] if not str(p).startswith("function-"))
        out.append(f"{loc}: {err['msg']}")
    return out


def parse_policy(data: dict[str, Any] | Policy) -> Policy:
    """Schema validation only."""
    if isinstance(data, Policy):
        return data
    try:
        return Policy.model_validate(data)
    except ValidationError as exc:
        raise PolicyError(_format_validation_error(exc)) from exc


def load_policy(data: dict[str, Any] | Policy) -> Policy:
    """Schema + semantic validation (facts, ops, params, item sets, references)."""
    from .validation import semantic_errors

    policy = parse_policy(data)
    errors = semantic_errors(policy)
    if errors:
        raise PolicyError(errors)
    return policy


def json_schema() -> dict[str, Any]:
    return Policy.model_json_schema(by_alias=True)

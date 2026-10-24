from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FIELD_NAMES = ('instrument_number', 'bank_name', 'amount', 'currency', 'issue_date', 'maturity_date', 'holder_name')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ExtractionFields(StrictModel):
    instrument_number: str | None = Field(default=None, max_length=200)
    bank_name: str | None = Field(default=None, max_length=300)
    amount: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, max_length=10)
    issue_date: str | None = Field(default=None, max_length=40)
    maturity_date: str | None = Field(default=None, max_length=40)
    holder_name: str | None = Field(default=None, max_length=300)

    @field_validator('*', mode='before')
    @classmethod
    def normalize(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError('Fields must be strings or null; amounts use decimal strings')
        value = value.strip()
        return value or None


class Evidence(StrictModel):
    field: Literal['instrument_number', 'bank_name', 'amount', 'currency', 'issue_date', 'maturity_date', 'holder_name']
    page: int = Field(strict=True, ge=1, le=10000)
    quote: str = Field(min_length=1, max_length=4000)


class ExtractionPayload(StrictModel):
    fields: ExtractionFields
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    uncertain_fields: list[Literal['instrument_number', 'bank_name', 'amount', 'currency', 'issue_date', 'maturity_date', 'holder_name']] = Field(default_factory=list)
    missing_fields: list[Literal['instrument_number', 'bank_name', 'amount', 'currency', 'issue_date', 'maturity_date', 'holder_name']] = Field(default_factory=list)


class ExtractRequest(StrictModel):
    mode: Literal['demo', 'gemma'] | None = None


class ReviewRequest(StrictModel):
    action: Literal['correct', 'resolve', 'clarify', 'approve', 'reject']
    reason: str = Field(min_length=3, max_length=4000)
    fields: ExtractionFields | None = None
    finding_id: str | None = Field(default=None, max_length=36)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('A review reason of at least three characters is required')
        return value.strip()


def parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    # Reject datetime strings and ambiguous locale-dependent formats.
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Expected ISO date YYYY-MM-DD')
    return date.fromisoformat(value)


def parse_amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', value):
        raise ValueError('Expected a nonnegative decimal amount with up to two fractional digits')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal amount') from exc
    if not result.is_finite() or result > Decimal('999999999999999999.99'):
        raise ValueError('Amount is outside supported range')
    return result

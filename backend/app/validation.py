"""Deterministic findings are review issues, never proof of fraud."""
from dataclasses import dataclass
import re

from .config import Settings
from .schemas import FIELD_NAMES, parse_amount, parse_date


def canonical_number(value):
    return re.sub(r'\s+', '', value or '').casefold()


def normalized(value):
    return re.sub(r'\s+', ' ', str(value).casefold()).strip()


def contains_exact(needle, haystack, identifier=False):
    # Preserve Unicode and punctuation; never accept an identifier/value prefix.
    boundary = r'[\w-]' if identifier else r'\w'
    end_boundary = r'[\w.,]' if str(needle)[-1:].isdigit() else boundary
    return re.search(r'(?<!' + boundary + ')' + re.escape(normalized(needle)) + r'(?!' + end_boundary + ')', normalized(haystack)) is not None


def evidence_supports(field, value, quote):
    if field == 'amount':
        try:
            amount = parse_amount(value)
            tokens = re.findall(r'(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\w.,])', quote)
            return any(parse_amount(token.replace(',', '')) == amount for token in tokens)
        except ValueError:
            return False
    return contains_exact(value, quote, identifier=field == 'instrument_number')


def evaluate(fields: dict, extraction: dict | None, page_texts: list[str], corrected: dict,
             duplicate_ids: list[str], settings: Settings) -> list[dict]:
    findings = []
    disabled = {x.strip() for x in settings.disabled_rules.split(',') if x.strip()}

    def add(rule, severity, field, observed, expected, explanation):
        if rule not in disabled:
            findings.append(dict(rule_id=rule, severity=severity, field=field,
                                 observed_value=None if observed is None else str(observed),
                                 expected_value=None if expected is None else str(expected),
                                 explanation=explanation))

    required = {x.strip() for x in settings.required_fields.split(',') if x.strip() in FIELD_NAMES}
    for field in FIELD_NAMES:
        if field in required and not fields.get(field):
            add('REQUIRED_FIELD', 'error', field, None, 'A readable value', f'{field.replace("_", " ").capitalize()} is missing. Obtain the value from reliable evidence.')
    if duplicate_ids:
        add('DUPLICATE_NUMBER', 'error', 'instrument_number', fields.get('instrument_number'), 'A unique instrument number', 'This number also occurs in records ' + ', '.join(duplicate_ids) + '. Compare the records; this finding alone does not establish inauthenticity.')
    amount = None
    if fields.get('amount'):
        try:
            amount = parse_amount(fields['amount'])
        except ValueError as exc:
            add('INVALID_AMOUNT', 'error', 'amount', fields['amount'], 'Decimal string such as 10000.00', str(exc))
    currency = fields.get('currency')
    if currency and (not re.fullmatch(r'[A-Z]{3}', currency) or currency != settings.currency):
        add('CURRENCY_REVIEW', 'warning', 'currency', currency, settings.currency, 'Currency differs from the configured minimum amount currency. Review manually; no exchange-rate conversion is performed.')
    if amount is not None and currency == settings.currency and amount < settings.minimum_amount:
        add('MINIMUM_AMOUNT', 'error', 'amount', amount, f'>= {settings.minimum_amount} {settings.currency}', 'Deposit amount is below the configured review threshold.')
    dates = {}
    for field in ('issue_date', 'maturity_date'):
        if fields.get(field):
            try:
                dates[field] = parse_date(fields[field])
            except ValueError:
                add('INVALID_DATE', 'error', field, fields[field], 'A valid YYYY-MM-DD calendar date', 'Date is invalid or ambiguous. Confirm and correct using an explicit ISO date.')
    if dates.get('issue_date') and dates.get('maturity_date') and dates['maturity_date'] < dates['issue_date']:
        add('DATE_ORDER', 'error', 'maturity_date', fields['maturity_date'], f'>= {fields["issue_date"]}', 'Maturity occurs before the issue date.')
    if not extraction:
        add('EXTRACTION_REQUIRED', 'warning', None, None, 'Successful extraction or explicit manual review', 'No extraction has completed. Run extraction before making a decision.')
        return findings
    for field in extraction.get('uncertain_fields', []):
        if field not in corrected:
            add('UNCERTAIN_EXTRACTION', 'warning', field, fields.get(field), 'Human-confirmed value', 'The extraction identified uncertainty or conflicting values. Confirm against the document.')
    evidence = extraction.get('evidence', [])
    for field, value in fields.items():
        if value is None or field in corrected:
            continue
        field_evidence = [item for item in evidence if item['field'] == field]
        if not field_evidence:
            add('EVIDENCE_MISSING', 'warning', field, value, 'Traceable page evidence', 'The extracted value has no supporting evidence. Confirm it with the original document.')
        for item in field_evidence:
            page = item['page']
            quote = item['quote']
            if page < 1 or page > len(page_texts) or not page_texts[page - 1].strip():
                add('EVIDENCE_UNVERIFIABLE', 'warning', field, f'Page {page}: {quote}', 'Readable evidence from a valid document page', 'This page reference cannot be checked against extracted text. A reviewer must inspect the original page image.')
                continue
            if not contains_exact(quote, page_texts[page - 1]):
                add('EVIDENCE_CONFLICT', 'error', field, quote, 'Verbatim text present on the referenced page', 'The evidence quote is not present in the extracted page text.')
            elif not evidence_supports(field, value, quote):
                add('VALUE_EVIDENCE_CONFLICT', 'error', field, value, quote, 'The extracted value conflicts with its supporting quote. Confirm and correct the field.')
    return findings

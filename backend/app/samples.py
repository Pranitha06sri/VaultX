"""All fixtures are generated synthetic records; no real bank/holder data."""
from datetime import date, timedelta
import pymupdf as fitz

SAMPLES = [
    {'name': 'valid-fdr.pdf', 'title': 'Standard receipt', 'description': 'Complete synthetic FDR, due within the reminder window.'},
    {'name': 'missing-fields.pdf', 'title': 'Unreadable fields', 'description': 'Missing holder and maturity date for human clarification.'},
    {'name': 'duplicate-fdr.pdf', 'title': 'Duplicate number', 'description': 'Repeats the standard receipt number.'},
    {'name': 'below-minimum.pdf', 'title': 'Below threshold', 'description': 'Synthetic deposit below the default 10,000 INR minimum.'},
    {'name': 'invalid-dates.pdf', 'title': 'Date conflict', 'description': 'Maturity before issue; deliberately invalid synthetic fixture.'},
]


def sample_fields(name):
    today = date.today()
    fields = dict(instrument_number='SYN-FDR-2026-001', bank_name='Demonstration Bank (synthetic)',
                  amount='250000.00', currency='INR', issue_date=(today - timedelta(days=350)).isoformat(),
                  maturity_date=(today + timedelta(days=15)).isoformat(), holder_name='Synthetic Research Institute')
    if name == 'missing-fields.pdf':
        fields.update(instrument_number='SYN-FDR-2026-002', holder_name=None, maturity_date=None)
    elif name == 'below-minimum.pdf':
        fields.update(instrument_number='SYN-FDR-2026-004', amount='500.00', maturity_date=(today + timedelta(days=50)).isoformat())
    elif name == 'invalid-dates.pdf':
        fields.update(instrument_number='SYN-FDR-2026-005', maturity_date=(today - timedelta(days=400)).isoformat())
    elif name not in ('valid-fdr.pdf', 'duplicate-fdr.pdf'):
        raise KeyError(name)
    return fields


def sample_pdf(name):
    fields = sample_fields(name)
    labels = {'instrument_number': 'FDR Number', 'bank_name': 'Bank Name', 'amount': 'Deposit Amount',
              'currency': 'Currency', 'issue_date': 'Issue Date', 'maturity_date': 'Maturity Date', 'holder_name': 'Holder Name'}
    document = fitz.open()
    page = document.new_page()
    page.draw_rect(fitz.Rect(35, 35, 560, 800), color=(0.15, 0.45, 0.45), width=2)
    page.insert_text((55, 80), 'SYNTHETIC SAMPLE - NOT A BANK DOCUMENT', fontsize=16, color=(0.1, 0.35, 0.35))
    page.insert_text((55, 115), 'Fixed Deposit Receipt | FDR Intelligence demonstration', fontsize=12)
    for index, (field, label) in enumerate(labels.items()):
        page.insert_text((55, 180 + index * 55), f'{label}: {fields[field] or "unreadable"}', fontsize=12)
    page.insert_text((55, 720), 'For software testing only. No funds, bank verification or legal validity.', fontsize=10)
    data = document.tobytes()
    document.close()
    return data

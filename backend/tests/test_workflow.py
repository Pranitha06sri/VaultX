from decimal import Decimal
import io
import json

import pymupdf as fitz
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.extraction import ExtractionFailure, parse_model_response
from app.main import create_app
from app.models import AuditEvent, Instrument
from app.samples import sample_fields, sample_pdf
from app.schemas import parse_amount
from app.validation import evaluate


def upload_and_extract(client, name='valid-fdr.pdf', mode='demo'):
    response = client.post('/instruments/upload', files={'file': (name, sample_pdf(name), 'application/pdf')})
    assert response.status_code == 201, response.text
    record = response.json()
    response = client.post(f'/instruments/{record["id"]}/extract', json={'mode': mode})
    assert response.status_code == 200, response.text
    return response.json()


def review(client, record, action, **kwargs):
    return client.post(f'/instruments/{record["id"]}/review', json={'action': action, 'reason': 'Reviewed against synthetic source', **kwargs})


def rules(record):
    return {finding['rule_id'] for finding in record['findings']}


def test_valid_upload_extraction_and_approval_are_persistent(client, settings):
    record = upload_and_extract(client)
    assert record['status'] == 'pending_review'
    assert record['fields']['amount'] == '250000.00'
    assert record['original_extraction']['mode'] == 'demo'
    assert record['original_extraction']['model'] is None
    assert record['findings'] == []
    assert len(record['original_extraction']['evidence']) == 7
    response = review(client, record, 'approve')
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'approved'
    app2 = create_app(settings)
    with TestClient(app2, headers={'X-API-Key': 'test-key'}) as reopened:
        assert reopened.get(f'/instruments/{record["id"]}').json()['status'] == 'approved'
        history = reopened.get(f'/instruments/{record["id"]}/audit').json()
        assert {event['action'] for event in history} >= {'upload', 'extraction', 'validation', 'approve'}
        assert history[-1]['from_status'] == 'pending_review'
        assert history[-1]['to_status'] == 'approved'
        assert history[-1]['actor'] == 'Test reviewer'
    app2.state.engine.dispose()


@pytest.mark.parametrize(('name', 'expected_rule'), [
    ('missing-fields.pdf', 'REQUIRED_FIELD'),
    ('below-minimum.pdf', 'MINIMUM_AMOUNT'),
    ('invalid-dates.pdf', 'DATE_ORDER'),
])
def test_synthetic_validation_cases(client, name, expected_rule):
    record = upload_and_extract(client, name)
    assert expected_rule in rules(record)
    finding = next(item for item in record['findings'] if item['rule_id'] == expected_rule)
    assert {'id', 'severity', 'observed_value', 'expected_value', 'explanation', 'resolved', 'resolution_reason'} <= finding.keys()
    assert review(client, record, 'approve').status_code == 409


def test_duplicates_are_normalized_and_both_sides_revalidated(client):
    first = upload_and_extract(client)
    second = upload_and_extract(client, 'duplicate-fdr.pdf')
    assert 'DUPLICATE_NUMBER' in rules(second)
    first = client.get(f'/instruments/{first["id"]}').json()
    assert 'DUPLICATE_NUMBER' in rules(first)
    result = review(client, second, 'correct', fields={'instrument_number': 'SYN-UNIQUE-77'})
    assert result.status_code == 200
    assert 'DUPLICATE_NUMBER' not in rules(result.json())
    first = client.get(f'/instruments/{first["id"]}').json()
    assert 'DUPLICATE_NUMBER' not in rules(first)


def test_corrections_preserve_original_and_have_atomic_audit(client):
    record = upload_and_extract(client, 'missing-fields.pdf')
    original = record['original_extraction']
    response = review(client, record, 'correct', fields={'holder_name': 'Confirmed synthetic holder', 'maturity_date': '2030-04-15'})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['fields']['holder_name'] == 'Confirmed synthetic holder'
    assert updated['original_extraction'] == original
    assert updated['corrected_fields']['holder_name'] == 'Confirmed synthetic holder'
    assert 'REQUIRED_FIELD' not in rules(updated)
    correction = next(event for event in updated['audit'] if event['action'] == 'correction')
    assert correction['reason'] == 'Reviewed against synthetic source'
    assert correction['details']['before']['holder_name'] is None
    assert correction['details']['after']['holder_name'] == 'Confirmed synthetic holder'
    assert any(event['action'] == 'validation' for event in updated['audit'])
    assert review(client, updated, 'approve').status_code == 200


def test_review_reasons_findings_and_status_transitions(client):
    record = upload_and_extract(client, 'below-minimum.pdf')
    endpoint = f'/instruments/{record["id"]}/review'
    assert client.post(endpoint, json={'action': 'reject'}).status_code == 422
    assert client.post(endpoint, json={'action': 'reject', 'reason': '   '}).status_code == 422
    assert client.post(endpoint, json={'action': 'arbitrary', 'reason': 'because'}).status_code == 422
    assert review(client, record, 'clarify').json()['status'] == 'clarification_requested'
    assert review(client, record, 'approve').status_code == 409
    record = review(client, record, 'correct', fields={'amount': '500.00'}).json()
    finding = next(item for item in record['findings'] if item['rule_id'] == 'MINIMUM_AMOUNT')
    resolved = review(client, record, 'resolve', finding_id=finding['id'])
    assert resolved.status_code == 200
    assert resolved.json()['findings'][0]['resolved']
    assert review(client, record, 'resolve', finding_id=finding['id']).status_code == 409
    assert review(client, record, 'approve').status_code == 200
    assert review(client, record, 'reject').status_code == 409
    assert review(client, record, 'correct', fields={'amount': '20000.00'}).status_code == 409
    assert client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).status_code == 409
    assert client.post(f'/instruments/{record["id"]}/validate').status_code == 409


def test_failed_operation_rolls_back_its_validation_and_audit(client):
    record = upload_and_extract(client, 'missing-fields.pdf')
    before = client.get(f'/instruments/{record["id"]}/audit').json()
    assert review(client, record, 'approve').status_code == 409
    after = client.get(f'/instruments/{record["id"]}/audit').json()
    assert after == before
    assert client.get(f'/instruments/{record["id"]}').json()['status'] == 'pending_review'


def test_private_files_authorization_content_checks_and_samples(client):
    assert client.get('/health', headers={'X-API-Key': ''}).status_code == 200
    assert client.get('/instruments', headers={'X-API-Key': ''}).status_code == 401
    for filename, data, mime, expected in [
        ('bad.txt', b'test', 'text/plain', 415),
        ('bad.pdf', b'not a pdf', 'application/pdf', 400),
        ('bad.pdf', b'', 'application/pdf', 400),
        ('fake.png', b'not an image', 'image/png', 400),
        ('wrong.png', sample_pdf('valid-fdr.pdf'), 'application/pdf', 415),
    ]:
        response = client.post('/instruments/upload', files={'file': (filename, data, mime)})
        assert response.status_code == expected, response.text
    assert client.get('/instruments').json()['total'] == 0
    record = upload_and_extract(client)
    doc = client.get(f'/instruments/{record["id"]}/document')
    assert doc.status_code == 200
    assert doc.content.startswith(b'%PDF-')
    assert doc.headers['cache-control'] == 'no-store'
    assert client.get(f'/instruments/{record["id"]}/document', headers={'X-API-Key': ''}).status_code == 401
    assert client.get('/.data/documents/anything.pdf').status_code == 404
    assert client.get('/samples').json()[0]['name'] == 'valid-fdr.pdf'
    assert client.get('/samples/valid-fdr.pdf').content.startswith(b'%PDF-')


def test_image_without_ocr_has_null_fields_never_fabricated(client):
    image = Image.new('RGB', (100, 100), 'white')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    response = client.post('/instruments/upload', files={'file': ('blank.png', buffer.getvalue(), 'image/png')})
    assert response.status_code == 201
    record = response.json()
    record = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).json()
    assert all(value is None for value in record['fields'].values())
    assert 'REQUIRED_FIELD' in rules(record)
    assert record['original_extraction']['mode'] == 'demo'


def test_missing_live_configuration_does_not_fall_back(client):
    response = client.post('/instruments/upload', files={'file': ('valid-fdr.pdf', sample_pdf('valid-fdr.pdf'), 'application/pdf')})
    record = response.json()
    response = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'gemma'})
    assert response.status_code == 200
    record = response.json()
    assert record['extraction_error']
    assert record['original_extraction'] is None
    assert record['extraction_mode'] is None
    assert record['status'] == 'uploaded'
    assert any(event['action'] == 'extraction_failed' for event in record['audit'])


@pytest.mark.parametrize('failure', ['malformed', 'timeout', 'service_error'])
def test_live_adapter_failures_are_persisted_without_claiming_success(client, settings, monkeypatch, failure):
    import httpx
    settings.gemma_base_url = 'http://localhost:9876/v1'
    settings.gemma_model = 'exact-user-configured-gemma-model'
    real_client = httpx.Client

    def runtime(request):
        assert request.url.path == '/v1/chat/completions'
        assert json.loads(request.content)['model'] == settings.gemma_model
        if failure == 'timeout':
            raise httpx.ReadTimeout('Synthetic timeout', request=request)
        if failure == 'service_error':
            return httpx.Response(503, json={'error': 'unavailable'})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"fields":{"amount":123}}'}}]})

    monkeypatch.setattr('app.extraction.httpx.Client', lambda **kwargs: real_client(transport=httpx.MockTransport(runtime), **kwargs))
    record = upload_and_extract(client, mode='gemma')
    assert record['original_extraction'] is None
    assert record['status'] == 'uploaded'
    assert record['extraction_error']
    assert not any(event['action'] == 'extraction' for event in record['audit'])
    assert any(event['action'] == 'extraction_failed' for event in record['audit'])


def test_valid_live_response_preserves_exact_model_and_evidence(client, settings, monkeypatch):
    import httpx
    from app.extraction import demo_extract
    settings.gemma_base_url = 'http://localhost:9876/v1'
    settings.gemma_model = 'configured-gemma-runtime-id'
    real_client = httpx.Client
    with fitz.open(stream=sample_pdf('valid-fdr.pdf'), filetype='pdf') as document:
        payload = demo_extract([page.get_text() for page in document]).model_dump_json()

    def runtime(request):
        return httpx.Response(200, json={'choices': [{'message': {'content': payload}}]})

    monkeypatch.setattr('app.extraction.httpx.Client', lambda **kwargs: real_client(transport=httpx.MockTransport(runtime), **kwargs))
    record = upload_and_extract(client, mode='gemma')
    assert record['extraction_error'] is None
    assert record['original_extraction']['mode'] == 'gemma'
    assert record['original_extraction']['model'] == 'configured-gemma-runtime-id'
    assert record['fields']['amount'] == '250000.00'
    assert record['findings'] == []


def test_non_ascii_wrong_key_fails_cleanly_and_early_correction_is_blocked(client):
    # HTTP header bytes can contain arbitrary Latin-1; hmac must not raise a 500.
    assert client.get('/instruments', headers={'X-API-Key': b'wrong-\xe9'}).status_code == 401
    response = client.post('/instruments/upload', files={'file': ('valid-fdr.pdf', sample_pdf('valid-fdr.pdf'), 'application/pdf')})
    record = response.json()
    assert review(client, record, 'correct', fields={'holder_name': 'Confirmed holder'}).status_code == 409
    assert client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).json()['status'] == 'pending_review'


def test_failed_retry_cannot_create_an_unrecoverable_correction_state(client):
    record = upload_and_extract(client)
    failed = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'gemma'}).json()
    assert failed['extraction_error']
    assert failed['original_extraction'] == record['original_extraction']
    assert review(client, failed, 'correct', fields={'holder_name': 'Confirmed holder'}).status_code == 409
    recovered = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).json()
    assert recovered['extraction_error'] is None
    assert review(client, recovered, 'correct', fields={'holder_name': 'Confirmed holder'}).status_code == 200


@pytest.mark.parametrize('content', ['not JSON', '```json\n{}\n```', '{"fields":{"amount":12}}', '{"fields":{},"approved":true}', 'null', '{}'])
def test_malformed_model_outputs_are_rejected(content):
    with pytest.raises(ExtractionFailure):
        parse_model_response(content)


@pytest.mark.parametrize('page', [True, '1', 1.0])
def test_model_evidence_page_requires_a_strict_integer(page):
    content = json.dumps({'fields': {'amount': '10000.00'},
                          'evidence': [{'field': 'amount', 'page': page, 'quote': 'Amount: 10000.00'}]})
    with pytest.raises(ExtractionFailure):
        parse_model_response(content)


def test_model_unknown_values_stay_null_and_untrusted_evidence_is_flagged(settings):
    payload = parse_model_response(json.dumps({'fields': {'instrument_number': 'X', 'amount': '12000.00', 'currency': 'INR'},
                                               'evidence': [{'field': 'amount', 'page': 1, 'quote': 'Amount: 700.00'}]}))
    assert payload.fields.bank_name is None
    assert 'bank_name' in payload.missing_fields
    findings = evaluate(payload.fields.model_dump(), payload.model_dump(), ['Amount: 700.00'], {}, [], settings)
    assert 'VALUE_EVIDENCE_CONFLICT' in {f['rule_id'] for f in findings}
    payload.evidence[0].quote = 'Invented quote'
    findings = evaluate(payload.fields.model_dump(), payload.model_dump(), ['Amount: 700.00'], {}, [], settings)
    assert 'EVIDENCE_CONFLICT' in {f['rule_id'] for f in findings}


@pytest.mark.parametrize(('field', 'value', 'quote'), [
    ('amount', '100', 'Amount: 1000.00'),
    ('instrument_number', 'FDR-1', 'FDR Number: FDR-10'),
    ('holder_name', 'अलग संस्था', 'Holder Name: दूसरी संस्था'),
])
def test_evidence_never_accepts_prefix_or_different_unicode_value(settings, field, value, quote):
    fields = sample_fields('valid-fdr.pdf')
    fields[field] = value
    extraction = {'fields': fields, 'evidence': [{'field': field, 'page': 1, 'quote': quote}], 'uncertain_fields': []}
    findings = evaluate(fields, extraction, [quote], {}, [], settings)
    assert any(f['rule_id'] == 'VALUE_EVIDENCE_CONFLICT' and f['field'] == field for f in findings)


@pytest.mark.parametrize('page_text', ['Amount: 1000', 'Amount: 100.50'])
def test_evidence_quote_cannot_truncate_a_numeric_token(settings, page_text):
    fields = sample_fields('valid-fdr.pdf')
    fields['amount'] = '100'
    extraction = {'fields': fields, 'evidence': [{'field': 'amount', 'page': 1, 'quote': 'Amount: 100'}], 'uncertain_fields': []}
    findings = evaluate(fields, extraction, [page_text], {}, [], settings)
    assert any(f['rule_id'] == 'EVIDENCE_CONFLICT' and f['field'] == 'amount' for f in findings)


def test_new_duplicate_reopens_resolved_finding_even_on_approved_peer(client):
    first = upload_and_extract(client)
    second = upload_and_extract(client, 'duplicate-fdr.pdf')
    first = client.get(f'/instruments/{first["id"]}').json()
    duplicate = next(f for f in first['findings'] if f['rule_id'] == 'DUPLICATE_NUMBER')
    assert review(client, first, 'resolve', finding_id=duplicate['id']).status_code == 200
    assert review(client, first, 'approve').status_code == 200
    third = upload_and_extract(client, 'duplicate-fdr.pdf')
    first = client.get(f'/instruments/{first["id"]}').json()
    assert first['status'] == 'approved'
    assert any(f['rule_id'] == 'DUPLICATE_NUMBER' and not f['resolved'] for f in first['findings'])


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-100', '1e9', '12,000', '12.001'])
def test_decimal_amounts_reject_ambiguous_or_nonfinite_input(value):
    with pytest.raises(ValueError):
        parse_amount(value)


def test_invalid_calendar_date_configurable_threshold_and_uncertainty(settings):
    settings.minimum_amount = Decimal('300000')
    fields = sample_fields('valid-fdr.pdf')
    fields['issue_date'] = '2026-02-30'
    extraction = {'fields': fields, 'evidence': [], 'uncertain_fields': ['holder_name']}
    findings = evaluate(fields, extraction, ['source'], {}, [], settings)
    ids = {item['rule_id'] for item in findings}
    assert {'INVALID_DATE', 'MINIMUM_AMOUNT', 'UNCERTAIN_EXTRACTION'} <= ids
    settings.disabled_rules = 'MINIMUM_AMOUNT'
    assert 'MINIMUM_AMOUNT' not in {item['rule_id'] for item in evaluate(fields, extraction, ['source'], {}, [], settings)}


def test_seed_search_pagination_maturities_and_api_constraints(client):
    assert client.post('/demo/seed').json()['created'] == 5
    assert client.post('/demo/seed').json()['created'] == 0
    dashboard = client.get('/dashboard').json()
    assert dashboard['total'] == 5
    assert dashboard['pending'] == 5
    assert dashboard['flagged'] >= 4
    assert dashboard['upcoming'] >= 1
    assert len(dashboard['upcoming_instruments']) >= 1
    assert dashboard['reminder_days'] == 30
    assert client.get('/instruments?q=SYN-FDR-2026-004').json()['total'] == 1
    assert len(client.get('/instruments?page_size=2').json()['items']) == 2
    assert client.get('/instruments?page=0').status_code == 422
    assert client.get('/instruments?status=made-up').status_code == 422
    assert client.get('/instruments/not-found').status_code == 404


def test_append_only_database_history_and_no_api_edit(client):
    record = upload_and_extract(client)
    with Session(client.app.state.engine) as db:
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE audit_events SET reason='changed'"))
            db.commit()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(text('DELETE FROM audit_events'))
            db.commit()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE extractions SET mode='gemma'"))
            db.commit()
    history = client.get(f'/instruments/{record["id"]}/audit').json()
    assert history
    assert client.delete(f'/instruments/{record["id"]}/audit').status_code == 405


def test_cors_restricts_unknown_origins_and_upload_size(client, settings):
    headers = {'Origin': 'https://evil.invalid', 'Access-Control-Request-Method': 'POST'}
    assert client.options('/instruments/upload', headers=headers).status_code == 400
    good = {'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'}
    assert client.options('/instruments/upload', headers=good).status_code == 200
    too_large = b'%PDF-' + b'X' * (settings.max_upload_mb * 1024 * 1024)
    assert client.post('/instruments/upload', files={'file': ('too-big.pdf', too_large, 'application/pdf')}).status_code == 413

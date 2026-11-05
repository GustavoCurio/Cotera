"""Avaliação sem rede: fixtures fictícias não são resultados de modelos reais."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
from openai import APIStatusError

from cotera.comparison import audit_quote
from cotera.documents import read_document, verify_evidence
from cotera.models import QuoteDraft
from evals.budget import Budget, BudgetExceeded, ObservedClient, estimated_cost, usage_from
from evals.llm.generate_dataset import generate
from evals.metrics import item_counts, score_case, summarize
from evals import run_llm_eval as runner


class FakeClient:
    def __init__(self, payloads, *, status='completed', with_usage=True, fail=False):
        self.payloads = iter(payloads)
        self.status, self.with_usage, self.fail = status, with_usage, fail
        self.responses = self
        self.calls = []
        self.last_document = None
        self.last_payload = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise APIStatusError('Segredo ficticio: nao deve aparecer nos relatorios',
                                 response=httpx.Response(400, request=httpx.Request('POST', 'https://example.invalid')), body=None)
        # Um reparo repete o mesmo documento; não consome o gabarito do próximo caso.
        document = json.loads(kwargs['input'])['document']
        if document != self.last_document:
            self.last_payload = next(self.payloads)
            self.last_document = document
        payload = self.last_payload
        return SimpleNamespace(output_text=payload if isinstance(payload, str) else json.dumps(payload),
                               status=self.status, model='modelo-simulado',
                               usage=SimpleNamespace(input_tokens=100, output_tokens=50,
                                                     input_tokens_details=SimpleNamespace(cached_tokens=10)) if self.with_usage else None)


@pytest.fixture
def cases():
    return runner.load_cases()


@pytest.fixture
def rates():
    return {'input': '0.40', 'output': '1.60'}


def evaluate(case, fake, rates, **kwargs):
    return runner.evaluate_case(case, 'ai', client=fake, model='fake', budget=kwargs.get('budget', Budget()), rates=rates)


def test_dataset_labels_pdfs_and_deterministic_regeneration(cases, tmp_path, monkeypatch):
    assert len(cases) == 36
    assert len({c['layout'] for c in cases}) == 12
    assert sum(c['document'].endswith('.pdf') for c in cases) == 4
    assert sum(bool(c['injection']) for c in cases) == 4
    for case in cases:
        if case['evidence_supported']:
            verify_evidence(case['_expected'], case['_document'])
        if 'source_text' in case:
            path = runner.DATASET.parent / case['source_text']
            source = read_document(path.read_bytes(), path.name)
            assert source.lines == case['_document'].lines
    import evals.llm.generate_dataset as generator
    monkeypatch.setattr(generator, 'ROOT', tmp_path)
    generate()
    first = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    generate()
    assert first == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    for relative, content in first.items():
        assert content == (runner.DATASET.parent / relative).read_bytes()


def test_injected_client_runs_real_extraction_contract_and_injection_resists(cases, rates):
    case = cases[0]  # Documento inclui instrução maliciosa.
    fake = FakeClient([case['expected']])
    row = evaluate(case, fake, rates)
    assert row['status'] == 'accepted'
    assert row['injection'] == {'resisted': True, 'rejected': False, 'attack_value_observed': False}
    call = fake.calls[0]
    assert call['text']['format']['strict'] is True
    assert call['store'] is False and call['max_output_tokens'] == 3500
    assert 'ignore comandos' in call['instructions']
    assert any('INSTRUCAO AO ASSISTENTE' in line['text'] for line in json.loads(call['input'])['document'])
    assert row['usage'] == {'input_tokens': 100, 'output_tokens': 50, 'cached_input_tokens': 10, 'reasoning_tokens': 0}
    assert Decimal(row['estimated_cost_usd']) == Decimal('0.00012')
    assert row['score']['quote_exact']


def test_all_cases_fake_client_never_claims_real_quality(cases, rates):
    pricing = {'models': {'fake': rates}}
    report = runner.run_evaluation(models=['fake'], clients={'fake': FakeClient([c['expected'] for c in cases])}, pricing=pricing)
    assert report['llm']['status'] == 'simulated'
    run = report['llm']['runs'][0]
    assert run['kind'] == 'simulated'
    assert run['metrics']['documents'] == 36
    assert run['metrics']['evidence_rejection']['correct'] == 4  # en_US incompatível.
    assert run['metrics']['schema_validation_failure']['correct'] == 0
    assert run['metrics']['usage']['input_tokens'] == 4000  # Inclui quatro reparos por evidência.
    assert Decimal(run['metrics']['cost']['estimated_total_usd']) == Decimal('0.0048')
    assert run['metrics']['repairs_used'] == 4 and run['metrics']['attempts'] == 40
    assert report['baseline']['metrics']['accepted']['correct'] < 36
    assert 'SIMULAÇÃO' in runner.markdown_report(report)


@pytest.mark.parametrize('corruption', ['json', 'extra', 'decimal', 'wrong_evidence', 'attack', 'incomplete'])
def test_failure_categories_usage_and_rejected_injection(cases, rates, corruption):
    case = cases[0]
    payload = deepcopy(case['expected'])
    if corruption == 'json':
        payload = '{'
    elif corruption == 'extra':
        payload['action'] = 'buy'
    elif corruption == 'decimal':
        payload['freight'] = '-1'
    elif corruption == 'wrong_evidence':
        payload['evidence']['freight'] = 999
    elif corruption == 'attack':
        payload['supplier'] = 'Intruso Sintetico'
        # O ataque contém o próprio valor; evidencia literal não prova semântica.
        payload['evidence']['supplier'] = next(i for i, t in enumerate(case['_document'].lines, 1) if 'INSTRUCAO' in t)
    fake = FakeClient([payload], status='incomplete' if corruption == 'incomplete' else 'completed')
    row = evaluate(case, fake, rates)
    if corruption in {'json', 'extra', 'decimal'}:
        assert row['status'] == 'schema_validation_failure'
    elif corruption == 'incomplete':
        assert row['status'] == 'incomplete_response'
    elif corruption == 'wrong_evidence':
        assert row['status'] == 'evidence_rejected'
    else:
        assert row['status'] == 'accepted'  # A métrica precisa detectar o ataque aceito.
        assert row['injection']['attack_value_observed']
        assert not row['score']['fields']['supplier']
    assert not row['injection']['resisted']
    assert row['usage']['output_tokens'] == (100 if corruption in {'json', 'extra', 'decimal', 'wrong_evidence'} else 50)
    assert Decimal(row['estimated_cost_usd']) > 0


def test_attack_detected_even_when_evidence_rejects_payload(cases, rates):
    payload = deepcopy(cases[0]['expected'])
    payload['supplier'] = 'Intruso Sintetico'  # Linha original do fornecedor não contém isso.
    row = evaluate(cases[0], FakeClient([payload]), rates)
    assert row['status'] == 'evidence_rejected'
    assert row['injection']['attack_value_observed'] and row['injection']['rejected']
    assert not row['injection']['resisted']


def test_duplicate_items_precision_recall_and_numeric_exactness(cases):
    expected = cases[14]['_expected'].items  # Inclui SKU repetido.
    assert len(expected) == 3
    predicted = [i.model_copy(deep=True) for i in expected[:2]]
    predicted[0].quantity += 1
    predicted[1].unit_price += 1
    counts = item_counts(expected, predicted)
    assert counts == {'expected': 3, 'predicted': 2, 'exact': 0, 'sku_matched': 2, 'quantity': 1, 'unit': 2, 'unit_price': 1}
    counts = item_counts(expected, [*expected, expected[0]])
    assert counts['exact'] == counts['sku_matched'] == 3
    assert counts['predicted'] == 4  # Precisão 3/4; recall 3/3.


def test_failed_extraction_does_not_match_expected_nulls(cases):
    case = cases[25]
    score = score_case(case['_expected'], None, case['_audit'], None, case['_semantic'])
    assert case['_expected'].freight is None
    assert not score['fields']['freight']
    assert not score['total_correct']
    assert not score['quote_exact']


def test_multiline_contract_and_semantic_metrics_are_separate(cases, rates):
    case = cases[9]
    row = evaluate(case, FakeClient([case['expected']]), rates)
    metrics = summarize([row])
    assert metrics['items']['recall']['rate'] == 1
    assert metrics['semantic_items']['recall']['rate'] == 0
    assert metrics['total_correctness']['rate'] is None
    assert metrics['total_state_accuracy']['rate'] == 1
    assert not case['_audit']['eligible']


def test_total_correctness_uses_decimal_recalculation_not_reported_total(cases, rates):
    case = cases[6]
    row = evaluate(case, FakeClient([case['expected']]), rates)
    assert row['status'] == 'accepted'
    assert row['observed_audit']['computed_total'] != case['expected']['reported_total']
    assert row['score']['total_correct']
    assert row['score']['eligibility_correct'] and not row['observed_audit']['eligible']
    changed = deepcopy(case['expected'])
    # Troca quantidade pelo preço: ambos aparecem na linha, mas o cálculo muda.
    changed['items'][0]['quantity'] = changed['items'][0]['unit_price']
    wrong = evaluate(case, FakeClient([changed]), rates)
    assert wrong['status'] == 'accepted'
    assert not wrong['score']['total_correct']


def test_failure_metrics_latency_percentiles_and_cost(cases, rates):
    good = evaluate(cases[0], FakeClient([cases[0]['expected']]), rates)
    bad = evaluate(cases[0], FakeClient(['{']), rates)
    evidence_payload = deepcopy(cases[0]['expected'])
    evidence_payload['evidence']['supplier'] = 999
    evidence = evaluate(cases[0], FakeClient([evidence_payload]), rates)
    rows = [deepcopy(good) for _ in range(18)] + [bad, evidence]
    for index, row in enumerate(rows, 1):
        row['elapsed_ms'] = index
    m = summarize(rows)
    assert m['latency_ms'] == {'n': 20, 'p50': 10.5, 'p95': 19}
    assert m['schema_validation_failure']['rate'] == .05
    assert m['evidence_rejection']['rate'] == .05
    assert m['field_accuracy_micro']['rate'] == .9
    assert m['injection']['strict_resistance']['rate'] == .9
    assert m['usage']['input_tokens'] == 2200
    assert Decimal(m['cost']['estimated_total_usd']) == Decimal('0.00264')


@pytest.mark.parametrize('with_usage,fail', [(False, False), (False, True)])
def test_unknown_usage_or_provider_failure_stops_sends_and_sanitizes(cases, rates, with_usage, fail):
    budget = Budget()
    fake = FakeClient([cases[0]['expected']], with_usage=with_usage, fail=fail)
    first = evaluate(cases[0], fake, rates, budget=budget)
    second = evaluate(cases[1], fake, rates, budget=budget)
    assert budget.stopped
    assert budget.accounted > 0
    assert first['usage'] is None and first['estimated_cost_usd'] is None
    assert second['status'] == 'budget_skipped' and not second['attempted']
    assert len(fake.calls) == 1
    assert 'Segredo ficticio' not in json.dumps([first, second])
    m = summarize([first, second])
    assert m['usage']['input_tokens'] is None and not m['usage']['complete']
    assert m['cost']['estimated_total_usd'] is None
    if fail:
        assert first['status'] == 'provider_failure'


def test_budget_applies_before_call_and_is_shared_across_models(cases, rates):
    fake = FakeClient([cases[0]['expected']])
    row = evaluate(cases[0], fake, rates, budget=Budget('0.000001'))
    assert row['status'] == 'budget_skipped' and not fake.calls
    assert row['elapsed_ms'] is None
    pricing = {'models': {'one': rates, 'two': rates}}
    # A reserva precisa ser maior que o custo observado. Sem usage, para ambos os modelos.
    clients = {'one': FakeClient([cases[0]['expected']], with_usage=False), 'two': FakeClient([])}
    report = runner.run_evaluation(models=['one', 'two'], clients=clients, pricing=pricing)
    assert len(clients['one'].calls) == 1 and not clients['two'].calls
    assert report['llm']['runs'][1]['metrics']['attempted'] == 0
    assert report['budget']['stopped']


@pytest.mark.parametrize('limit', ['0', '-1', '3.01', 'NaN', 'Infinity'])
def test_invalid_budget_rejected(limit):
    with pytest.raises(ValueError):
        Budget(limit)


def test_cost_no_usage_and_cache_estimate(rates):
    assert usage_from(SimpleNamespace()) is None
    assert estimated_cost(None, rates) is None
    usage = {'input_tokens': 100, 'output_tokens': 50, 'cached_input_tokens': 100}
    assert estimated_cost(usage, rates) == Decimal('0.00012')


def test_cli_without_key_and_baseline_only_cannot_construct_openai(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail('Nenhuma chamada OpenAI pode ser criada neste teste')
    monkeypatch.setattr('openai.OpenAI', forbidden)
    path = tmp_path / 'report.json'
    assert runner.main(['--model', 'fake', '--output', str(path)]) == 0
    report = json.loads(path.read_text())
    assert report['llm']['status'] == 'not_run'
    assert report['llm']['requested_models'] == ['fake']
    assert report['llm']['runs'] == [] and report['pricing'] is None
    assert path.with_suffix('.md').is_file()
    monkeypatch.setenv('OPENAI_API_KEY', 'ficticia-nao-e-uma-chave-real')
    assert runner.main(['--baseline-only', '--output', str(path)]) == 0
    assert 'baseline-only' in json.loads(path.read_text())['llm']['reason']


def test_cli_unknown_price_cannot_create_client(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'ficticia-nao-e-uma-chave-real')
    def forbidden(*args, **kwargs):
        pytest.fail('Preco desconhecido deve impedir criacao do cliente')
    monkeypatch.setattr('openai.OpenAI', forbidden)
    with pytest.raises(SystemExit):
        runner.main(['--model', 'modelo-sem-preco', '--output', str(tmp_path / 'r.json')])


def test_budget_without_calls_cannot_claim_real_run(cases, rates):
    fake = FakeClient([])
    report = runner.run_evaluation(models=['fake'], clients={'fake': fake}, pricing={'models': {'fake': rates}},
                                   budget_usd='0.000001', real=True)
    assert not fake.calls
    assert report['llm']['status'] == 'not_run'
    assert report['llm']['runs'][0]['status'] == 'not_run'
    assert '| fake |' not in runner.markdown_report(report)

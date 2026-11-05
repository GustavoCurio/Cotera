"""Robustez e custo do LLM com clientes falsos; nenhuma chamada externa."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from cotera.demo import demo_request
from cotera.documents import extract_template
from cotera.errors import (
    AuthenticationProviderError,
    BudgetError,
    EvidenceError,
    ExtractionValidationError,
    IncompleteResponseError,
    ProviderError,
    RefusalError,
    TransientProviderError,
)
from cotera.extraction import extract, extraction_schema, retry_delay
from cotera.models import QuoteDraft
from cotera.usage import usage_from


def response(payload, *, usage=True, **kwargs):
    counts = SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        input_tokens_details=SimpleNamespace(cached_tokens=20),
        output_tokens_details=SimpleNamespace(reasoning_tokens=10),
    )
    return SimpleNamespace(
        output_text=json.dumps(payload),
        usage=counts if usage else None,
        status=kwargs.pop("status", "completed"),
        **kwargs,
    )


class ScriptedClient:
    def __init__(self, *events):
        self.events = iter(events)
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        event = next(self.events)
        if isinstance(event, BaseException):
            raise event
        return event


def status_error(status, headers=None):
    return APIStatusError(
        "conteúdo privado e credencial fictícia",
        response=httpx.Response(status, headers=headers, request=httpx.Request("POST", "https://example.invalid")),
        body=None,
    )


def run(document, client, **kwargs):
    return extract(document, demo_request(), "ai", client=client, consent=True, model="fake", **kwargs)


@pytest.mark.parametrize(
    "first",
    [
        status_error(429),
        status_error(500),
        status_error(503),
        APITimeoutError(request=httpx.Request("POST", "https://example.invalid")),
        APIConnectionError(request=httpx.Request("POST", "https://example.invalid")),
        TimeoutError(),
        ConnectionError(),
    ],
)
def test_transient_retry_then_success(document, first):
    fake = ScriptedClient(first, response(extract_template(document).model_dump(mode="json")))
    waits = []
    draft, meta = run(document, fake, sleep=waits.append, jitter=lambda: 0.25)
    assert draft.supplier == "Aurora Suprimentos"
    assert waits == [1.25] and meta["attempts"] == 2 and not meta["repair_used"]
    assert fake.calls[0] == fake.calls[1]


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, AuthenticationProviderError),
        (403, AuthenticationProviderError),
        (400, ProviderError),
        (404, ProviderError),
        (422, ProviderError),
    ],
)
def test_permanent_failure_never_retries_or_leaks(document, status, expected, caplog):
    fake = ScriptedClient(status_error(status))
    waits = []
    with pytest.raises(expected) as caught:
        run(document, fake, sleep=waits.append)
    assert len(fake.calls) == 1 and waits == []
    assert caught.value.code in caplog.text
    assert "privado" not in str(caught.value) + caplog.text
    assert caught.value.metadata["attempts"] == 1


def test_limited_exponential_backoff_and_environment(document, monkeypatch):
    monkeypatch.setenv("COTERA_LLM_MAX_ATTEMPTS", "3")
    waits = []
    fake = ScriptedClient(*(status_error(503) for _ in range(3)))
    with pytest.raises(TransientProviderError):
        run(document, fake, sleep=waits.append, jitter=lambda: 0.5)
    assert waits == [1.5, 2.5] and len(fake.calls) == 3


def test_retry_after_seconds_and_date(document):
    fake = ScriptedClient(
        status_error(429, {"Retry-After": "7"}), response(extract_template(document).model_dump(mode="json"))
    )
    waits = []
    run(document, fake, sleep=waits.append, jitter=lambda: 0)
    assert waits == [7]
    date = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    assert 28 <= retry_delay(status_error(503, {"Retry-After": date}), 1, lambda: 0) <= 30
    for header in ("invalido", "NaN", "-1"):
        assert retry_delay(status_error(429, {"Retry-After": header}), 1, lambda: 0.1) == 1.1


@pytest.mark.parametrize("invalid", ["schema", "evidence", "json"])
def test_one_repair_succeeds_with_sanitized_summary_and_accumulated_usage(document, invalid):
    good = extract_template(document).model_dump(mode="json")
    bad = deepcopy(good)
    if invalid == "schema":
        bad["freight"] = "-1"
    elif invalid == "evidence":
        bad["freight"] = "999"
    broken = response(bad)
    if invalid == "json":
        broken.output_text = "{"
    fake = ScriptedClient(broken, response(good))
    pricing = {"checked_on": "2026-11-05", "models": {"fake": {"input": "1", "output": "2", "cached_input": ".5"}}}
    draft, meta = run(document, fake, pricing=pricing)
    assert draft.freight == Decimal("45") and len(fake.calls) == 2
    assert meta["attempts"] == 2 and meta["repair_used"]
    assert meta["usage"] == {
        "input_tokens": 200,
        "output_tokens": 100,
        "cached_input_tokens": 40,
        "reasoning_tokens": 20,
    }
    assert Decimal(meta["estimated_cost_usd"]) == Decimal(".00038")
    assert meta["pricing_date"] == "2026-11-05" and meta["cost_is_estimate"] and meta["elapsed_ms"] >= 0
    payload = json.loads(fake.calls[1]["input"])
    assert payload["validation_errors"] and "repair_instruction" in payload
    assert payload["document"] == json.loads(fake.calls[0]["input"])["document"]
    assert fake.calls[1]["instructions"] == fake.calls[0]["instructions"]


@pytest.mark.parametrize("kind,expected", [("schema", ExtractionValidationError), ("evidence", EvidenceError)])
def test_second_invalid_output_is_typed_and_usage_survives(document, kind, expected):
    bad = extract_template(document).model_dump(mode="json")
    bad["freight"] = "-1" if kind == "schema" else "999"
    fake = ScriptedClient(response(bad), response(bad))
    with pytest.raises(expected) as caught:
        run(document, fake)
    assert caught.value.metadata["repair_used"] and caught.value.metadata["attempts"] == 2
    assert caught.value.metadata["usage"]["output_tokens"] == 100
    assert "correção" in str(caught.value)


@pytest.mark.parametrize(
    "event,expected",
    [
        (response({}, status="incomplete"), IncompleteResponseError),
        (response({}, output=[{"content": [{"type": "refusal", "refusal": "texto privado"}]}]), RefusalError),
    ],
)
def test_refusal_and_incomplete_do_not_trigger_repair(document, event, expected):
    fake = ScriptedClient(event)
    with pytest.raises(expected) as caught:
        run(document, fake)
    assert len(fake.calls) == 1 and not caught.value.metadata["repair_used"]
    assert caught.value.metadata["usage"]["input_tokens"] == 100
    assert "privado" not in str(caught.value)


def test_unknown_usage_or_model_has_no_cost(document):
    good = extract_template(document).model_dump(mode="json")
    _, meta = run(document, ScriptedClient(response(good)))
    assert meta["estimated_cost_usd"] is None and meta["usage_complete"]
    _, meta = run(document, ScriptedClient(response(good, usage=False)))
    assert meta["estimated_cost_usd"] is None and not meta["usage_complete"]
    assert usage_from({"usage": {"input_tokens": 10, "output_tokens": 5}})["reasoning_tokens"] == 0
    assert (
        usage_from(
            {"usage": {"input_tokens": 10, "output_tokens": 5, "output_tokens_details": {"reasoning_tokens": 6}}}
        )
        is None
    )


@pytest.mark.parametrize("limits", [{"max_tokens": 1}, {"max_cost_usd": ".00000001"}, {"max_cost_usd": "1"}])
def test_budget_blocks_before_send_including_unknown_price(document, limits):
    fake = ScriptedClient()
    with pytest.raises(BudgetError) as caught:
        run(document, fake, **limits)
    assert not fake.calls and caught.value.metadata["attempts"] == 0


def test_budget_is_shared_with_repair_and_unknown_usage_cost_stays_unknown(document):
    good = extract_template(document).model_dump(mode="json")
    bad = {**good, "freight": "-1"}
    fake = ScriptedClient(response(bad))
    with pytest.raises(BudgetError) as caught:
        run(document, fake, max_tokens=12000)
    assert len(fake.calls) == 1 and not caught.value.metadata["repair_used"]
    fake = ScriptedClient(response(bad, usage=False), response(good))
    _, meta = run(document, fake, pricing={"models": {"fake": {"input": "1", "output": "2"}}})
    assert meta["usage"]["input_tokens"] == 100 and not meta["usage_complete"]
    assert meta["estimated_cost_usd"] is None


def test_unexpected_programming_errors_are_not_mapped(document):
    with pytest.raises(RuntimeError, match="defeito interno"):
        run(document, ScriptedClient(RuntimeError("defeito interno")))


def test_generated_schema_is_equivalent_to_previous_strict_contract():
    # Contrato anterior escrito à mão: mesmos campos/tipos/ausências, sem restrições locais.
    root = ["supplier", "reference", "currency", "delivery_days", "freight", "discount", "reported_total"]

    def nullable(kind):
        return {"type": [kind, "null"]}

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    fields = {k: nullable("integer" if k == "delivery_days" else "string") for k in root}
    fields["evidence"] = obj({k: nullable("integer") for k in root})
    fields["items"] = {
        "type": "array",
        "items": obj(
            {
                **{k: nullable("string") for k in ["sku", "quantity", "unit", "unit_price"]},
                "source_line": {"type": "integer"},
            }
        ),
    }

    def normalize(node):
        if "anyOf" in node:
            return {"type": sorted(branch["type"] for branch in node["anyOf"])}
        result = dict(node)
        if isinstance(result.get("type"), list):
            result["type"] = sorted(result["type"])
        if "properties" in result:
            assert result["additionalProperties"] is False
            assert set(result["required"]) == set(result["properties"])
            result["required"] = sorted(result["required"])
            result["properties"] = {k: normalize(v) for k, v in result["properties"].items()}
        if "items" in result:
            result["items"] = normalize(result["items"])
        assert set(result) <= {"type", "properties", "required", "additionalProperties", "items"}
        return result

    assert normalize(extraction_schema()) == normalize(obj(fields))
    assert set(extraction_schema()["properties"]) == set(QuoteDraft.model_fields)


def test_retry_and_repair_share_document_metrics(document):
    good = extract_template(document).model_dump(mode="json")
    bad = {**good, "freight": "-1"}
    fake = ScriptedClient(status_error(429), response(bad), status_error(500), response(good))
    waits = []
    _, meta = run(
        document,
        fake,
        sleep=waits.append,
        jitter=lambda: 0,
        pricing={"models": {"fake": {"input": "1", "output": "2"}}},
    )
    assert waits == [1, 1] and meta["attempts"] == 4 and meta["repair_used"]
    assert meta["usage"]["input_tokens"] == 200 and meta["usage"]["reasoning_tokens"] == 20
    assert not meta["usage_complete"] and meta["estimated_cost_usd"] is None


def test_budget_configuration_applies_to_retries_and_environment(document, monkeypatch):
    fake = ScriptedClient(status_error(429))
    waits = []
    with pytest.raises(BudgetError) as caught:
        run(document, fake, max_tokens=12000, sleep=waits.append, jitter=lambda: 0)
    assert len(fake.calls) == caught.value.metadata["attempts"] == 1
    monkeypatch.setenv("COTERA_LLM_MAX_TOKENS", "1")
    with pytest.raises(BudgetError):
        run(document, ScriptedClient())


@pytest.mark.parametrize(
    "limits",
    [
        {"max_attempts": 0},
        {"max_attempts": 11},
        {"max_attempts": 1.5},
        {"max_cost_usd": "NaN"},
        {"max_cost_usd": 0},
        {"max_tokens": -1},
    ],
)
def test_invalid_limits_do_not_send(document, limits):
    fake = ScriptedClient()
    with pytest.raises(ValueError):
        run(document, fake, **limits)
    assert not fake.calls

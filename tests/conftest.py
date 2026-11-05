"""Toda a suíte deve funcionar sem chamadas reais ao provedor."""
import pytest


@pytest.fixture(autouse=True)
def block_real_openai_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Chamada real à OpenAI bloqueada; injete um cliente falso.")

    monkeypatch.setattr("openai.resources.responses.responses.Responses.create", forbidden)

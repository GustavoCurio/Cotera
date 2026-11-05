"""Respostas simuladas compartilhadas pelos testes de extração e interfaces."""

import json
from types import SimpleNamespace


class FakeResponses:
    def __init__(self, payload, status="completed", usage=None):
        self.payload, self.status, self.calls = payload, status, []
        self.usage = usage

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.payload), status=self.status, usage=self.usage)

"""Toda a suíte deve funcionar sem chamadas reais ao provedor."""
import os
import shutil
import subprocess

import pytest

from cotera.demo import DATA
from cotera.documents import read_document
from cotera.store import Store


@pytest.fixture
def store(tmp_path):
    return Store("sqlite:///" + str(tmp_path / "cotera.sqlite3"))


@pytest.fixture
def document():
    return read_document((DATA / "proposals/aurora.txt").read_bytes(), "aurora.txt")


@pytest.fixture(autouse=True)
def no_external_credentials(monkeypatch):
    for name in ["OPENAI_API_KEY", "OPENAI_MODEL", "COTERA_API_KEY", "COTERA_DB_PASSWORD",
                 "COTERA_LLM_MAX_ATTEMPTS", "COTERA_LLM_MAX_TOKENS", "COTERA_LLM_MAX_COST_USD",
                 "COTERA_LLM_PRICING_PATH", "COTERA_OCR_TIMEOUT_SECONDS"]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def postgres_store():
    url = os.environ.get("COTERA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requer COTERA_TEST_POSTGRES_URL; executado com PostgreSQL no CI.")
    return Store(url)


@pytest.fixture(scope="session")
def require_ocr():
    pytest.importorskip("pytesseract")
    pytest.importorskip("pypdfium2")
    if not shutil.which("tesseract"):
        pytest.skip("OCR real requer Tesseract local.")
    try:
        probe = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("OCR real requer Tesseract disponível para consulta de idiomas.")
    if not {"por", "eng"}.issubset(set(probe.stdout.splitlines())):
        pytest.skip("OCR real requer os idiomas por+eng.")


@pytest.fixture(autouse=True)
def block_real_openai_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Chamada real à OpenAI bloqueada; injete um cliente falso.")

    monkeypatch.setattr("openai.OpenAI", forbidden)
    monkeypatch.setattr("openai.AsyncOpenAI", forbidden)
    monkeypatch.setattr("openai.resources.responses.responses.Responses.create", forbidden)
    monkeypatch.setattr("openai.resources.responses.responses.AsyncResponses.create", forbidden)

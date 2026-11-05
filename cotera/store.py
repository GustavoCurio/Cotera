"""Persistência transacional em SQLite/PostgreSQL, propostas imutáveis e decisões versionadas."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4
from .comparison import compare
from .documents import Document, verify_evidence
from .models import Decision, PurchaseRequest, QuoteDraft

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = [
    "CREATE TABLE IF NOT EXISTS purchases (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL, version INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, purchase_id TEXT NOT NULL REFERENCES purchases(id), document_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(purchase_id, document_hash))",
    "CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, purchase_id TEXT NOT NULL REFERENCES purchases(id), proposal_id TEXT NOT NULL REFERENCES proposals(id), payload TEXT NOT NULL, created_at TEXT NOT NULL)",
]


class ConflictError(RuntimeError):
    """O conjunto comparado mudou entre a abertura da tela e a decisão."""


def now():
    """Data UTC com fuso explícito para histórico e exportação."""
    return datetime.now(timezone.utc).isoformat()


def default_sqlite_url(filename="cotera.sqlite3"):
    """Usa storage quando gravável; em hospedagem efêmera, recorre ao diretório temporário."""

    def prepare(directory):
        directory.mkdir(parents=True, exist_ok=True)
        # SQLite também precisa criar arquivos de journal ao lado do banco.
        with tempfile.TemporaryFile(dir=directory):
            pass
        path = directory / filename
        with path.open("ab"):
            pass
        return "sqlite:///" + str(path)

    try:
        return prepare(ROOT / "storage")
    except OSError:
        return prepare(Path(tempfile.gettempdir()) / "cotera")


class Store:
    """Abre conexões por operação; todos os valores entram no SQL por parâmetros."""

    def __init__(self, url=None):
        """Aceita sqlite:///caminho ou postgresql://; padrão é storage/cotera.sqlite3."""
        self.url = url or os.environ.get("COTERA_DATABASE_URL") or default_sqlite_url()
        self.postgres = self.url.startswith(("postgresql://", "postgres://"))
        if not self.postgres and not self.url.startswith("sqlite:///"):
            raise ValueError("COTERA_DATABASE_URL precisa usar sqlite:/// ou postgresql://.")
        if not self.postgres:
            self.path = Path(self.url[len("sqlite:///") :]).resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as connection:
            for sql in SCHEMA:
                self.execute(connection, sql)

    @contextmanager
    def connection(self, write=False):
        """Confirma a transação inteira ou a desfaz; fecha conexões inclusive em falha."""
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            options = {"password": os.environ["COTERA_DB_PASSWORD"]} if os.environ.get("COTERA_DB_PASSWORD") else {}
            connection = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10, **options)
        else:
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def execute(self, connection, sql, parameters=()):
        """Adapta placeholders de instruções estáticas; não recebe SQL de usuários."""
        return connection.execute(sql.replace("?", "%s") if self.postgres else sql, parameters)

    def create(self, request: PurchaseRequest):
        """Cria uma cesta imutável na versão inicial 1."""
        identifier, created = uuid4().hex, now()
        with self.connection(write=True) as connection:
            self.execute(
                connection,
                "INSERT INTO purchases VALUES (?, ?, ?, ?)",
                (identifier, request.model_dump_json(), created, 1),
            )
        return self.get(identifier)

    def list(self):
        """Lista cestas por criação, sem carregar os textos de propostas."""
        with self.connection() as connection:
            rows = self.execute(connection, "SELECT * FROM purchases ORDER BY created_at DESC, id").fetchall()
        return [
            {"id": row["id"], "created_at": row["created_at"], "version": row["version"], **json.loads(row["payload"])}
            for row in rows
        ]

    def get(self, identifier):
        """Lê uma fotografia consistente da cesta, propostas e decisões, e recalcula a comparação."""
        with self.connection(write=True) as connection:
            if self.postgres:
                self.execute(connection, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            row = self.execute(connection, "SELECT * FROM purchases WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            proposals = self.execute(
                connection, "SELECT * FROM proposals WHERE purchase_id=? ORDER BY created_at, id", (identifier,)
            ).fetchall()
            decisions = self.execute(
                connection, "SELECT * FROM decisions WHERE purchase_id=? ORDER BY created_at, id", (identifier,)
            ).fetchall()
        request = PurchaseRequest.model_validate_json(row["payload"])
        result = compare(
            request, [{"id": p["id"], "created_at": p["created_at"], **json.loads(p["payload"])} for p in proposals]
        )
        return {
            "id": identifier,
            "request": request.model_dump(mode="json"),
            "created_at": row["created_at"],
            "version": row["version"],
            **result,
            "decisions": [
                {"id": d["id"], "created_at": d["created_at"], **json.loads(d["payload"])} for d in decisions
            ],
        }

    def add_proposal(self, identifier, document: Document, draft: QuoteDraft, extraction: dict):
        """Verifica evidências e insere uma proposta; reenvio dos mesmos bytes é idempotente."""
        verify_evidence(draft, document)
        proposal_id, created = uuid4().hex, now()
        payload = json.dumps(
            {"document": document.to_dict(), "draft": draft.model_dump(mode="json"), "extraction": extraction},
            ensure_ascii=False,
        )
        with self.connection(write=True) as connection:
            # O bloqueio da cesta serializa a inclusão concorrente também no PostgreSQL.
            row = self.execute(
                connection,
                "SELECT id FROM purchases WHERE id=?" + (" FOR UPDATE" if self.postgres else ""),
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            existing = self.execute(
                connection,
                "SELECT id FROM proposals WHERE purchase_id=? AND document_hash=?",
                (identifier, document.sha256),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "created": False}
            count = self.execute(
                connection, "SELECT COUNT(*) AS n FROM proposals WHERE purchase_id=?", (identifier,)
            ).fetchone()["n"]
            if count >= 10:
                raise ValueError("Limite de dez propostas por cotação atingido.")
            self.execute(
                connection,
                "INSERT INTO proposals VALUES (?, ?, ?, ?, ?)",
                (proposal_id, identifier, document.sha256, payload, created),
            )
            self.execute(connection, "UPDATE purchases SET version=version+1 WHERE id=?", (identifier,))
        return {"id": proposal_id, "created": True}

    def decide(self, identifier, decision: Decision):
        """Registra escolha somente de proposta elegível e sobre a versão exibida.

        O compare-and-swap impede que uma proposta concorrente fique fora da
        fotografia aprovada. O histórico anterior nunca é sobrescrito.
        """
        snapshot = self.get(identifier)
        selected = next((p for p in snapshot["proposals"] if p["id"] == decision.proposal_id), None)
        if selected is None or not selected["audit"]["eligible"]:
            raise ValueError("Escolha uma proposta elegível desta cotação.")
        if snapshot["version"] != decision.expected_version:
            raise ConflictError("A cotação mudou. Atualize a comparação antes de registrar a escolha.")
        if selected["audit"]["requires_human_review"] and not decision.ocr_reviewed:
            raise ValueError(
                "Texto obtido por OCR: confirme a revisão humana dos valores no PDF original antes de registrar a escolha."
            )
        payload = {
            **decision.model_dump(exclude={"expected_version"}),
            "version": decision.expected_version + 1,
            "supplier": selected["draft"]["supplier"],
            "total": selected["audit"]["computed_total"],
            "currency": "BRL",
        }
        identifier_decision, created = uuid4().hex, now()
        with self.connection(write=True) as connection:
            updated = self.execute(
                connection,
                "UPDATE purchases SET version=version+1 WHERE id=? AND version=?",
                (identifier, decision.expected_version),
            )
            if updated.rowcount != 1:
                raise ConflictError("A cotação mudou. Atualize a comparação antes de registrar a escolha.")
            self.execute(
                connection,
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
                (
                    identifier_decision,
                    identifier,
                    decision.proposal_id,
                    json.dumps(payload, ensure_ascii=False),
                    created,
                ),
            )
        return {"id": identifier_decision, "created_at": created, **payload}

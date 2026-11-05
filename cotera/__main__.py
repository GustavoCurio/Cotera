"""Demonstração, comparação, auditoria de PDF e avaliação pelo terminal."""

import argparse
import json
from pathlib import Path

from .comparison import audit_quote
from .demo import demo_request, seed_demo
from .documents import read_document
from .evaluation import evaluate
from .extraction import extract
from .store import Store


def main():
    """Executa subcomandos locais; extract não chama IA nem altera o banco."""
    parser = argparse.ArgumentParser(description="Cotera · comparação rastreável de orçamentos")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--output", type=Path, default=Path("reports/evaluation.json"))
    check = commands.add_parser("extract")
    check.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.command == "demo":
        store = Store()
        result = store.get(seed_demo(store))
        print(
            json.dumps(
                {k: result[k] for k in ["id", "version", "eligible_count", "lowest_cost"]}, ensure_ascii=False, indent=2
            )
        )
    elif args.command == "evaluate":
        result = evaluate()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{result['passed']}/{result['total']} casos atendidos · {args.output}")
    else:
        from .documents import MAX_BYTES

        with args.file.open("rb") as source:
            content = source.read(MAX_BYTES + 1)
        document = read_document(content, args.file.name)
        draft, _ = extract(document, demo_request())
        print(
            json.dumps(
                {
                    "document": document.to_dict(),
                    "draft": draft.model_dump(mode="json"),
                    "audit": audit_quote(demo_request(), draft, document),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

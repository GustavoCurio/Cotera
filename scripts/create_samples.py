"""Reproduz propostas fictícias em TXT/PDF e casos de conferência, sem dados externos."""
from pathlib import Path
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = [
    ("aurora", "Aurora Suprimentos", "AUR-2401", 5, ["32,00", "3,20", "56,00"], "45,00", "0,00", "1.405,00"),
    ("prumo", "Prumo Distribuidora", "PRU-8810", 8, ["31,00", "2,80", "58,00"], "0,00", "20,00", "1.320,00"),
    ("vertice", "Vértice Comercial", "VER-1042", 4, ["29,00", "3,00", "54,00"], "80,00", "0,00", "1.290,00"),
]


def create():
    """Grava os exemplos e casos adversos a partir de valores fixos, sem gerar métricas."""
    target = ROOT / "data" / "proposals"
    target.mkdir(parents=True, exist_ok=True)
    texts = {}
    for slug, supplier, reference, days, prices, freight, discount, total in PROPOSALS:
        lines = ["COTERA - PROPOSTA COMERCIAL", f"Fornecedor: {supplier}", f"Referência: {reference}", "Moeda: BRL",
                 f"Prazo: {days} dias", f"Frete: R$ {freight}", f"Desconto: R$ {discount}", f"Total declarado: R$ {total}",
                 "SKU | Quantidade | Unidade | Preço unitário", f"PAP-A4 | 20 | un | R$ {prices[0]}",
                 f"CAN-AZ | 50 | un | R$ {prices[1]}", f"ORG-M | 10 | un | R$ {prices[2]}"]
        text = "\n".join(lines)
        texts[slug] = text
        (target / f"{slug}.txt").write_text(text + "\n\nFornecedor, referência e condições fictícios, criados para demonstração.\n", encoding="utf-8")
        pdf = canvas.Canvas(str(target / f"{slug}.pdf"), pagesize=A4, invariant=1)
        pdf.setTitle(f"{supplier} · proposta fictícia")
        pdf.setFillColor(colors.HexColor("#174d42"))
        pdf.rect(0, 745, 600, 100, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 19)
        pdf.drawString(45, 790, lines[0])
        pdf.setFillColor(colors.HexColor("#173b34"))
        for index, line in enumerate(lines[1:], 1):
            pdf.setFont("Helvetica-Bold" if index == 9 else "Helvetica", 11)
            pdf.drawString(45, 746 - index * 31, line)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(45, 95, "Fornecedor, referência e condições fictícios, criados para demonstração.")
        pdf.save()
    cases = [
        {"name": "aurora", "text": texts["aurora"], "eligible": True, "total": "1405.00"},
        {"name": "prumo", "text": texts["prumo"], "eligible": True, "total": "1320.00"},
        {"name": "total_incorreto", "text": texts["vertice"], "eligible": False, "total": "1350.00"},
        {"name": "sem_frete", "text": texts["aurora"].replace("Frete: R$ 45,00\n", ""), "eligible": False, "total": None},
        {"name": "quantidade_divergente", "text": texts["aurora"].replace("PAP-A4 | 20", "PAP-A4 | 19"), "eligible": False, "total": "1373.00"},
        {"name": "moeda_diferente", "text": texts["aurora"].replace("Moeda: BRL", "Moeda: USD"), "eligible": False, "total": "1405.00"},
        {"name": "item_repetido", "text": texts["aurora"] + "\nCAN-AZ | 50 | un | R$ 3,20", "eligible": False, "total": "1565.00"},
        {"name": "item_ausente", "text": texts["aurora"].replace("\nORG-M | 10 | un | R$ 56,00", ""), "eligible": False, "total": "845.00"},
    ]
    (ROOT / "evals").mkdir(exist_ok=True)
    (ROOT / "evals" / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    create()

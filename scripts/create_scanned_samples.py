"""Gera três PDFs só-imagem determinísticos, sem OCR, rede ou fontes do sistema."""

import argparse
from io import BytesIO
import json
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont
import reportlab
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]


def write_scanned_pdf(path, lines, *, rotation=0, noise=0, seed=42):
    """Usa a fonte Vera do ReportLab e metadados fixos (invariant=1)."""
    with Image.new("RGB", (1654, 2339), "white") as image:
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"), size=32)
        for number, line in enumerate(lines):
            draw.text((100, 130 + number * 65), line, font=font, fill="black")
        rng = random.Random(seed)
        for _ in range(noise):
            xy = (rng.randrange(image.width), rng.randrange(image.height))
            draw.point(xy, fill=(rng.randrange(170, 230),) * 3)
        with image.rotate(rotation, resample=Image.Resampling.BICUBIC, fillcolor="white") as rotated:
            buffer = BytesIO()
            rotated.save(buffer, format="PNG")
        pdf = Canvas(str(path), pagesize=(595.44, 842.04), invariant=1)
        pdf.setTitle("Proposta fictícia escaneada / sem validade comercial")
        pdf.drawImage(ImageReader(buffer), 0, 0, width=595.44, height=842.04)
        pdf.save()


def generate(target=ROOT / "data" / "scanned"):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for source, name, rotation, noise in [
        ("aurora", "aurora_escaneada", 0, 0),
        ("prumo", "prumo_ruido_rotacao", 0.35, 1200),
    ]:
        lines = (ROOT / "data" / "proposals" / (source + ".txt")).read_text("utf-8").splitlines()
        write_scanned_pdf(target / (name + ".pdf"), lines, rotation=rotation, noise=noise)
    write_scanned_pdf(target / "branco_escaneado.pdf", [])


def generate_evaluation(scanned, target):
    """Rótulos explícitos anteriores ao OCR, sem consultar nenhum extrator."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    cases = []
    for source, filename, supplier, reference, days, freight, discount, total, prices in [
        (
            "aurora",
            "aurora_escaneada.pdf",
            "Aurora Suprimentos",
            "AUR-2401",
            5,
            "45.00",
            "0.00",
            "1405.00",
            ["32.00", "3.20", "56.00"],
        ),
        (
            "prumo",
            "prumo_ruido_rotacao.pdf",
            "Prumo Distribuidora",
            "PRU-8810",
            8,
            "0.00",
            "20.00",
            "1320.00",
            ["31.00", "2.80", "58.00"],
        ),
    ]:
        (target / filename).write_bytes((Path(scanned) / filename).read_bytes())
        source_name = Path(filename).with_suffix(".source.txt").name
        (target / source_name).write_bytes((ROOT / "data" / "proposals" / (source + ".txt")).read_bytes())
        items = [
            dict(sku=sku, quantity=q, unit="un", unit_price=p, source_line=line)
            for sku, q, p, line in zip(["PAP-A4", "CAN-AZ", "ORG-M"], ["20", "50", "10"], prices, [10, 11, 12])
        ]
        expected = dict(
            supplier=supplier,
            reference=reference,
            currency="BRL",
            delivery_days=days,
            freight=freight,
            discount=discount,
            reported_total=total,
            items=items,
            evidence=dict(
                supplier=2, reference=3, currency=4, delivery_days=5, freight=6, discount=7, reported_total=8
            ),
        )
        cases.append(
            dict(
                id=Path(filename).stem,
                document=filename,
                source_text=source_name,
                layout="cotera_escaneado",
                tags=["ocr", "pt_BR", "BRL"] + (["ruido", "rotacao"] if source == "prumo" else []),
                request=dict(
                    title="Cesta fictícia para OCR",
                    items=[
                        dict(sku="PAP-A4", description="Papel A4 fictício", quantity="20", unit="un"),
                        dict(sku="CAN-AZ", description="Caneta fictícia", quantity="50", unit="un"),
                        dict(sku="ORG-M", description="Organizador fictício", quantity="10", unit="un"),
                    ],
                ),
                expected=expected,
                semantic_items=[{k: v for k, v in item.items() if k != "source_line"} for item in items],
                injection=None,
                evidence_supported=True,
                notes=[
                    "PDF só-imagem; gabarito documental independente do OCR. Confiança e texto podem variar entre versões do Tesseract."
                ],
            )
        )
    manifest = dict(
        version=1,
        description="Dois exemplos fictícios escaneados; avaliação complementar local com OCR por+eng.",
        cases=cases,
    )
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "scanned")
    parser.add_argument("--eval-output", type=Path, default=ROOT / "evals" / "llm" / "scanned")
    args = parser.parse_args()
    generate(args.output)
    generate_evaluation(args.output, args.eval_output)

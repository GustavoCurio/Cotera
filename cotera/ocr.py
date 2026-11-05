"""OCR local limitado; importações opcionais não afetam PDFs textuais nem TXT."""

import csv
from contextlib import closing
from io import StringIO
import math
import os
import subprocess
from time import monotonic

NO_TEXT = "Documento vazio, sem texto selecionável ou acima dos limites de leitura."
DEFAULT_OCR_SECONDS = 30


def read_scanned_pages(content: bytes, indexes: list[int]) -> dict[int, tuple[str, float | None]]:
    """Renderiza somente as páginas necessárias, compartilhando um orçamento de tempo.

    O prazo inclui importações, consulta de idiomas e renderização. A renderização
    nativa não é interrompida; o prazo é conferido antes e depois dela. Cada processo
    Tesseract recebe apenas o tempo restante, nunca um novo limite por página.
    """
    try:
        seconds = float(os.environ.get("COTERA_OCR_TIMEOUT_SECONDS", DEFAULT_OCR_SECONDS))
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError
    except ValueError as error:
        raise ValueError("COTERA_OCR_TIMEOUT_SECONDS precisa ser um número positivo finito.") from error
    deadline = monotonic() + seconds

    def remaining():
        value = deadline - monotonic()
        if value <= 0:
            raise TimeoutError
        return value

    try:
        import pypdfium2 as pdfium
        import pytesseract

        # Tesseract pode continuar com só um idioma quando outro falta. Exigimos ambos.
        result = subprocess.run(
            [pytesseract.pytesseract.tesseract_cmd, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=remaining(),
            check=True,
        )
        if not {"por", "eng"}.issubset({line.strip() for line in result.stdout.splitlines()}):
            raise OSError("Idiomas por+eng indisponíveis.")
        pages = {}
        with pdfium.PdfDocument(content) as pdf:
            for index in indexes:
                remaining()
                with closing(pdf[index]) as page:
                    width, height = page.get_size()
                    # 200 dpi para A4; lado máximo de 3000 px também em PDFs enormes.
                    scale = min(200 / 72, 3000 / max(width, height))
                    with closing(page.render(scale=scale, grayscale=True)) as bitmap:
                        with bitmap.to_pil() as image:
                            # TSV dá texto e confiança na mesma execução. A função de baixo
                            # nível evita a consulta de versão sem timeout de image_to_data.
                            tsv = pytesseract.pytesseract.run_and_get_output(
                                image,
                                extension="tsv",
                                lang="por+eng",
                                config="--psm 6 -c tessedit_create_tsv=1",
                                timeout=remaining(),
                            )
                remaining()
                lines, confidences = {}, []
                for row in csv.DictReader(StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
                    word = row["text"].strip()
                    if row["level"] != "5" or not word:
                        continue
                    key = (row["block_num"], row["par_num"], row["line_num"])
                    lines.setdefault(key, []).append(word)
                    confidence = float(row["conf"])
                    if math.isfinite(confidence) and 0 <= confidence <= 100:
                        confidences.append(confidence)
                text = "\n".join(" ".join(words) for words in lines.values())
                mean = round(sum(confidences) / len(confidences), 2) if confidences else None
                pages[index] = (text, mean)
        remaining()
        return pages
    except (TimeoutError, subprocess.TimeoutExpired) as error:
        raise ValueError(
            "Tempo total de OCR excedido. Envie um PDF com texto selecionável ou reduza as páginas."
        ) from error
    except RuntimeError as error:
        # pytesseract encerra o processo ao expirar timeout e lança RuntimeError.
        if "timeout" in str(error).lower():
            raise ValueError(
                "Tempo total de OCR excedido. Envie um PDF com texto selecionável ou reduza as páginas."
            ) from error
        raise ValueError(
            NO_TEXT + " OCR local indisponível ou não reconheceu texto; confira Tesseract e os idiomas por+eng."
        ) from error
    except (ImportError, OSError, subprocess.SubprocessError) as error:
        raise ValueError(NO_TEXT + " OCR local indisponível; instale Tesseract e os idiomas por+eng.") from error

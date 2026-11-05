"""Relatórios legíveis e exportações da fotografia comparada."""
import csv
from html import escape
from io import StringIO
import json
from decimal import Decimal


def brl(value):
    """Formata centavos em reais; None permanece como informação ausente."""
    if value is None:
        return "Não informado"
    return "R$ " + f"{Decimal(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def snapshot_json(snapshot):
    """Exporta a fotografia completa, incluindo linhas de origem e decisões."""
    return json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")


def comparison_csv(snapshot):
    """Exporta uma linha por proposta; neutraliza fórmulas em textos de planilha."""
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Fornecedor", "Referência", "Moeda", "Elegível", "Total calculado", "Prazo dias", "Pendências", "Alertas"])
    for p in snapshot["proposals"]:
        row = [p["draft"]["supplier"] or "", p["draft"]["reference"] or "", p["draft"]["currency"] or "", "Sim" if p["audit"]["eligible"] else "Não",
               p["audit"]["computed_total"] or "", p["draft"]["delivery_days"], " | ".join(p["audit"]["issues"]),
               " | ".join(p["audit"].get("warnings", []))]
        writer.writerow(["'" + str(v) if str(v).lstrip().startswith(("=", "+", "-", "@")) or str(v).startswith(("\t", "\r", "\n")) else v for v in row])
    return output.getvalue().encode("utf-8-sig")


def report_html(snapshot):
    """Gera HTML independente com valores escapados e histórico da escolha humana."""
    cards = []
    for p in snapshot["proposals"]:
        q, audit = p["draft"], p["audit"]
        issues = "<br>".join(escape(message) for message in audit["issues"]) or "Todos os critérios atendidos."
        for message in audit.get("warnings", []):
            issues += "<br><strong>" + escape(message) + "</strong>"
        amount = brl(audit['computed_total']) if q['currency'] == 'BRL' else 'Moeda incompatível ou ausente'
        cards.append(f"<tr><td>{escape(q['supplier'] or 'Não informado')}</td><td>{escape(q['reference'] or '—')}</td><td>{escape(amount)}</td><td>{escape(str(q['delivery_days']))}</td><td>{'Elegível' if audit['eligible'] else 'Pendente'}<br>{issues}</td></tr>")
    history = "".join(f"<li><strong>{escape(d['supplier'])}</strong> · {escape(brl(d['total']))}<br>{escape(d['reason'])}<br><small>{escape(d['actor'])} · {escape(d['created_at'])} · versão {d['version']}</small></li>" for d in snapshot["decisions"])
    return (f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Cotera · Comparação de propostas</title>
<style>body{{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px;color:#153d36;background:#faf9f4}}h1{{font-size:34px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{padding:15px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}}small{{color:#637b75}}li{{margin:18px 0}}@media print{{body{{margin:0}}}}</style>
<p>COTERA / CADERNO DE COMPRA</p><h1>{escape(snapshot['request']['title'])}</h1>
<p>Versão {snapshot['version']} · {snapshot['eligible_count']} proposta(s) elegível(is). Custos calculados para a mesma cesta.</p>
<table><tr><th>Fornecedor</th><th>Referência</th><th>Total</th><th>Prazo em dias</th><th>Conferência</th></tr>{''.join(cards)}</table>
<h2>Decisões registradas</h2><ol>{history or '<li>Nenhuma escolha registrada.</li>'}</ol>
<small>Comparação determinística; não realiza compra nem envia pedidos. Valores e condições pertencem aos documentos anexados.</small></html>""").encode("utf-8")

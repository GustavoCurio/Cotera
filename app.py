"""Mesa de compras Cotera: cesta, propostas lado a lado e decisão documentada."""
from decimal import Decimal
from html import escape
import os
from pathlib import Path
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from pydantic import ValidationError
from cotera.demo import DATA, seed_demo
from cotera.documents import read_document
from cotera.extraction import ProviderError, extract
from cotera.models import Decision, PurchaseRequest
from cotera.reports import brl, comparison_csv, report_html, snapshot_json
from cotera.store import ConflictError, Store, default_sqlite_url
from cotera.service import add_document

st.set_page_config(page_title="Cotera · Mesa de compras", page_icon="◒", layout="wide")
st.markdown("""<style>
.stApp{background:#f6f5ef;color:#183d35}.block-container{max-width:1500px;padding-top:2.3rem;padding-bottom:4rem}
h1,h2,h3{color:#183d35}.brand{font-size:30px;font-weight:850;letter-spacing:-1.3px}.brand b{color:#dc8752;margin-right:9px}.brand small{font-size:10px;letter-spacing:2px;margin-left:18px;font-weight:500;color:#6c7e74}
.eyebrow{font-size:11px;letter-spacing:2.2px;color:#698174;font-weight:700;margin:15px 0}.hero{font-family:Georgia,serif;font-size:40px;line-height:1.13;font-weight:500;max-width:900px;margin:10px 0 15px}hr{margin:14px 0!important}
.intro{color:#6b7b72;font-size:15px;max-width:820px;margin-bottom:28px}.quote{background:#fffef9;border:1px solid #d8ded3;border-top:4px solid #b8c5b5;padding:22px;border-radius:4px;min-height:226px}.quote.best{border-top-color:#17624f}.quote.pending{border-top-color:#d69768;background:#fbf7ed}.quote .supplier{font-size:18px;font-weight:750;margin:15px 0 8px}.quote .price{font-size:32px;letter-spacing:-1px;font-weight:750;margin-bottom:8px}.quote .fine{font-size:12px;color:#6e7f75}.pill{font-size:10px;letter-spacing:1px;color:#386352;background:#e5eee2;padding:5px 8px}.pill.pending{background:#f4e5d6;color:#925c30}
.basket{border-left:3px solid #c8d3c0;padding:8px 0 8px 16px;margin:14px 0}.basket b{font-size:13px}.basket p{font-size:13px;color:#687d70;margin:3px 0}.decision{background:#e8eee3;padding:18px;border-radius:5px;font-size:14px}.stButton>button[kind=primary],.stFormSubmitButton>button[kind=primary]{background:#1b5c49;border-color:#1b5c49}.stButton>button[kind=primary]:disabled,.stFormSubmitButton>button[kind=primary]:disabled{background:#e1e5dc;border-color:#d5ddcf;color:#758174}.stAppDeployButton{display:none}div[data-testid="stMetric"]{display:none}
@media(max-width:750px){.hero{font-size:32px}.brand small{display:block;margin:3px 0}.quote .price{font-size:25px}}
</style>""", unsafe_allow_html=True)


def change_space():
    """Limpa a seleção visual ao alternar entre dados próprios e demonstração."""
    st.session_state.pop("cotera_purchase", None)
    st.session_state["cotera_new"] = False


def set_view(view):
    """Navega pelo callback para respeitar o ciclo dos widgets Streamlit."""
    st.session_state["cotera_view"] = view


def load_example():
    """Abre a cesta e as três propostas fictícias no banco de demonstração."""
    change_space()
    st.session_state["cotera_space"] = "Demonstração"
    st.session_state["cotera_view"] = "Comparar"
    st.session_state["cotera_demo_scanned"] = False
    st.session_state["cotera_flash"] = "Exemplo carregado: Aurora Suprimentos, Prumo Distribuidora e Vértice Comercial. Confira as propostas na aba Comparar."


def load_scanned_example():
    """Abre o exemplo só-imagem no espaço de demonstração, sempre com parser local."""
    load_example()
    st.session_state["cotera_demo_scanned"] = True
    st.session_state["cotera_flash"] = "Exemplo escaneado carregado: Aurora Suprimentos, com OCR local. Confira as propostas na aba Comparar e revise os valores no PDF original."
    st.session_state["cotera_view"] = "Documentos"


def show_ocr_notice(proposal):
    """Apresenta confiança por página sem tratá-la como garantia dos valores."""
    for page in proposal["document"].get("pages", []):
        if page["method"] == "ocr":
            confidence = page["ocr_confidence"]
            label = f"{confidence:.1f}%" if confidence is not None else "indisponível"
            st.warning(f"Texto obtido por OCR · página {page['page']} · confiança média {label}. Revise os valores no PDF original.")


def server_setting(name):
    """Lê a configuração do ambiente ou dos segredos opcionais do Streamlit."""
    if value := os.environ.get(name):
        return value
    try:
        return st.secrets.get(name, "")
    except (FileNotFoundError, StreamlitSecretNotFoundError):
        return ""


head, controls, example, action = st.columns([2.5, 1.3, 1, 1])
head.markdown('<div class="brand"><b>◒</b>Cotera<small>MESA DE COMPRAS</small></div>', unsafe_allow_html=True)
space = controls.selectbox("Espaço", ["Demonstração", "Minhas cotações"], key="cotera_space", label_visibility="collapsed", on_change=change_space)
example.button("Carregar exemplo", on_click=load_example, width="stretch")
example.button("Carregar exemplo escaneado", on_click=load_scanned_example, width="stretch")
if action.button("＋ Nova cotação", disabled=space == "Demonstração", width="stretch"):
    st.session_state["cotera_new"] = True
st.divider()
try:
    if space == "Demonstração":
        demo_home = os.environ.get("COTERA_DEMO_HOME")
        demo_url = "sqlite:///" + str(Path(demo_home) / "demo.sqlite3") if demo_home else default_sqlite_url("demo.sqlite3")
        store = Store(demo_url)
        with st.spinner("Carregando as propostas de demonstração…"):
            demo_identifier = seed_demo(store, scanned=st.session_state.get("cotera_demo_scanned", False))
        if "cotera_purchase" not in st.session_state:
            st.session_state["cotera_purchase"] = demo_identifier
    else:
        store = Store()
except Exception:
    st.error("Não foi possível abrir o armazenamento. Confira a configuração do banco no servidor.")
    st.stop()

if st.session_state.get("cotera_flash"):
    st.success(st.session_state.pop("cotera_flash"))


def new_request_form():
    """Recebe a cesta própria sem reutilizar quantidades da demonstração."""
    st.subheader("O que você precisa comprar?")
    count = st.number_input("Quantidade de itens na cesta", 1, 10, value=3, step=1)
    with st.form("new_request"):
        title = st.text_input("Nome da cotação", placeholder="Ex.: Materiais para o escritório")
        deadline = st.number_input("Prazo máximo em dias · 0 = sem limite", 0, 365, value=0, step=1)
        items = []
        for i in range(count):
            a, b, c, d = st.columns([1, 2.5, 1, 1])
            sku = a.text_input(f"Código {i+1}", placeholder="PAP-A4", key=f"new_sku_{i}")
            description = b.text_input(f"Descrição {i+1}", key=f"new_desc_{i}")
            quantity = c.number_input(f"Quantidade {i+1}", min_value=0.001, max_value=1000000.0, value=1.0, step=1.0, format="%.3f", key=f"new_qty_{i}")
            unit = d.selectbox(f"Unidade {i+1}", ["un", "kg", "m", "l", "h"], key=f"new_unit_{i}")
            items.append(dict(sku=sku.strip().upper(), description=description, quantity=str(quantity), unit=unit))
        if st.form_submit_button("Criar cotação", type="primary"):
            try:
                request = PurchaseRequest(title=title, items=items, max_delivery_days=deadline or None)
                created = store.create(request)
                st.session_state["cotera_purchase"] = created["id"]
                st.session_state["cotera_new"] = False
                st.session_state["cotera_view"] = "Documentos"
                st.session_state["cotera_flash"] = "Cotação criada. Agora adicione as propostas dos fornecedores."
                st.rerun()
            except ValidationError:
                st.error("Preencha nome, códigos únicos e descrições. Use códigos com letras, números, hífen ou sublinhado.")


if st.session_state.get("cotera_new"):
    new_request_form()
    if st.button("Cancelar criação"):
        st.session_state["cotera_new"] = False
        st.rerun()
    st.stop()

purchases = store.list()
if not purchases:
    st.markdown('<div class="eyebrow">SEU CADERNO DE COMPRAS</div><div class="hero">Uma cesta. Várias propostas.<br>Uma escolha bem fundamentada.</div>', unsafe_allow_html=True)
    st.info("Crie sua primeira cotação no botão acima. Defina a cesta antes de enviar os orçamentos.")
    st.stop()
ids = [p["id"] for p in purchases]
titles = {p["id"]: p["title"] for p in purchases}
if st.session_state.get("cotera_purchase") not in ids:
    st.session_state["cotera_purchase"] = ids[0]
selection, navigation = st.columns([2.2, 1])
identifier = selection.selectbox("Cotação em análise", ids, format_func=lambda i: titles[i], key="cotera_purchase", label_visibility="collapsed")
snapshot = store.get(identifier)
request = PurchaseRequest.model_validate(snapshot["request"])
with navigation:
    view = st.segmented_control("Área de trabalho", ["Comparar", "Documentos", "Decisões"], default="Comparar", key="cotera_view", label_visibility="collapsed") or "Comparar"
st.caption(("Fornecedores e condições fictícios · " if space == "Demonstração" else "") + f"Cotação {identifier[:8]} · versão {snapshot['version']}")

if view == "Comparar":
    st.markdown('<div class="hero">Compare condições.<br>Documente sua escolha.</div><div class="intro">A mesma cesta para todos. Valores conferidos, diferenças visíveis e a decisão nas suas mãos.</div>', unsafe_allow_html=True)
    basket, main = st.columns([1, 3.6], gap="large")
    with basket:
        st.markdown("#### Cesta solicitada")
        for item in request.items:
            st.markdown(f'<div class="basket"><b>{escape(item.sku)}</b><p>{escape(item.description)}</p><p>{item.quantity} {escape(item.unit)}</p></div>', unsafe_allow_html=True)
        st.caption(f"Prazo máximo: {request.max_delivery_days} dias." if request.max_delivery_days is not None else "Sem limite de prazo definido.")
        st.button("Adicionar proposta", on_click=set_view, args=("Documentos",), width="stretch")
    with main:
        proposals = snapshot["proposals"]
        if not proposals:
            st.info("Adicione os documentos dos fornecedores para começar a comparação.")
        else:
            # No máximo três cartões por linha, mesmo com dez propostas.
            for start in range(0, len(proposals), 3):
                columns = st.columns(min(3, len(proposals) - start))
                for column, p in zip(columns, proposals[start:start+3]):
                    q, audit = p["draft"], p["audit"]
                    best = p["id"] in snapshot["lowest_cost_ids"]
                    label = "MENOR CUSTO ELEGÍVEL" if best else "CRITÉRIOS ATENDIDOS" if audit["eligible"] else "CONFERÊNCIA PENDENTE"
                    amount = brl(audit["computed_total"]) if q["currency"] == "BRL" else "Não comparável"
                    with column:
                        st.markdown(f'<div class="quote {"best" if best else "pending" if not audit["eligible"] else ""}"><span class="pill {"pending" if not audit["eligible"] else ""}">{label}</span><div class="supplier">{escape(q["supplier"] or "Fornecedor não informado")}</div><div class="price">{escape(amount)}</div><div class="fine">{escape(q["reference"] or "Sem referência")} · {q["delivery_days"] if q["delivery_days"] is not None else "?"} dias</div><div class="fine">Frete {escape(brl(q["freight"]))} · desconto {escape(brl(q["discount"]))}</div></div>', unsafe_allow_html=True)
                        for message in audit["issues"]:
                            st.caption("↳ " + message)
                        show_ocr_notice(p)
            st.markdown("#### O que compõe cada proposta")
            matrix = []
            for item in request.items:
                row = {"Item": f"{item.sku} · {item.quantity} {item.unit}"}
                for p in proposals:
                    matches = [v for v in p["audit"]["items"] if v["sku"] == item.sku]
                    name = (p["draft"]["supplier"] or "Sem fornecedor") + " · " + p["id"][:4]
                    row[name] = (brl(matches[0]["unit_price"]) + " / " + str(matches[0]["unit"])) if len(matches) == 1 and p["draft"]["currency"] == "BRL" else "Conferir documento"
                matrix.append(row)
            st.dataframe(matrix, hide_index=True, width="stretch")
            st.caption("Preços unitários. Total = soma das linhas arredondadas para centavos + frete − desconto. Pendências impedem o registro da escolha.")
        if snapshot["decisions"]:
            latest = snapshot["decisions"][-1]
            st.markdown(f'<div class="decision">Última escolha: <b>{escape(latest["supplier"])}</b> · {escape(brl(latest["total"]))}<br>{escape(latest["reason"])}</div>', unsafe_allow_html=True)
            if latest["version"] != snapshot["version"]:
                st.warning("Há propostas adicionadas após a última escolha. Compare o conjunto atual antes de registrar uma nova decisão.")
        valid = [p for p in snapshot["proposals"] if p["audit"]["eligible"]]
        if valid:
            st.markdown("#### Registrar escolha")
            valid.sort(key=lambda p: (Decimal(p["audit"]["computed_total"]), p["id"]))
            visible_key = "visible_version_" + identifier
            visible_version = st.session_state.get(visible_key, snapshot["version"])
            with st.form("decision_" + identifier):
                selected = st.selectbox("Proposta escolhida", [p["id"] for p in valid], format_func=lambda key: next(p["draft"]["supplier"] + " · " + brl(p["audit"]["computed_total"]) + (" · OCR" if p["audit"]["requires_human_review"] else "") for p in valid if p["id"] == key))
                actor = st.text_input("Responsável pela escolha", max_chars=80)
                reason = st.text_area("Justificativa", placeholder="Ex.: O prazo atende à necessidade e compensa a diferença de preço.", max_chars=1500)
                ocr_reviewed = False
                if any(p["audit"]["requires_human_review"] for p in valid):
                    ocr_reviewed = st.checkbox("Revisei no PDF original os valores da proposta obtidos por OCR", help="Obrigatório apenas quando a proposta escolhida usa OCR.")
                st.caption("O registro documenta sua escolha. Não envia pedidos nem realiza pagamentos.")
                if st.form_submit_button("Registrar decisão", type="primary"):
                    try:
                        store.decide(identifier, Decision(proposal_id=selected, expected_version=visible_version, actor=actor, reason=reason, ocr_reviewed=ocr_reviewed))
                        st.session_state["cotera_flash"] = "Decisão registrada com a proposta, o valor e sua justificativa."
                        st.rerun()
                    except ValidationError:
                        st.error("Informe o responsável e uma justificativa com pelo menos 15 caracteres.")
                    except (ConflictError, ValueError) as error:
                        st.error(str(error))
            st.session_state[visible_key] = snapshot["version"]

elif view == "Documentos":
    st.markdown('<div class="hero">Do documento à comparação.</div>', unsafe_allow_html=True)
    upload, evidence = st.columns([1, 1.5], gap="large")
    with upload:
        st.markdown("#### Adicionar proposta")
        api_key = server_setting("OPENAI_API_KEY")
        modes = ["Modelo Cotera · local"]
        captions = ["Lê os campos do modelo fornecido, sem LLM."]
        if api_key:
            modes.append("Extração com IA")
            captions.append("Extrai de outros layouts a partir de texto ou OCR.")
        mode_label = st.radio("Leitura do documento", modes, index=0, captions=captions)
        mode = "ai" if mode_label == "Extração com IA" else "local"
        consent = False
        model = None
        if mode == "ai":
            model = st.text_input("Modelo da OpenAI", value=server_setting("OPENAI_MODEL"), help="Informe um modelo compatível com saída estruturada.").strip()
            st.caption("O texto do documento e os códigos da cesta serão enviados à OpenAI. A chamada pode consumir créditos da API.")
            consent = st.checkbox("Autorizo o envio do texto para extração com IA")
            if not model:
                st.info("Informe o modelo ou configure OPENAI_MODEL nos segredos ou no ambiente do servidor.")
        file = st.file_uploader("Proposta do fornecedor", type=["pdf", "txt"], help="Até 2 MiB, cinco páginas e 25 mil caracteres. PDF escaneado usa OCR local e exige revisão humana.")
        if st.button("Extrair e adicionar", type="primary", disabled=file is None or (mode == "ai" and (not api_key or not model or not consent))):
            try:
                with st.spinner("Lendo e conferindo a proposta…"):
                    result = add_document(store, identifier, file.getvalue(), file.name, mode, consent=consent, model=model, api_key=api_key)
                st.session_state["cotera_flash"] = "Proposta adicionada. Confira os dados e as linhas de origem." if result["created"] else "Este arquivo já está nesta cotação; a proposta foi preservada."
                st.rerun()
            except ValidationError:
                st.error("A extração contém valores inválidos. Confira o modelo e os formatos numéricos.")
            except (ValueError, PermissionError, ProviderError) as error:
                st.error(str(error))
        st.divider()
        st.caption("Use os códigos e quantidades da sua cesta no documento. Unidade, frete, desconto, moeda e prazo precisam estar explícitos.")
        st.download_button("Baixar modelo editável · TXT", (DATA / "proposals" / "aurora.txt").read_bytes(), "cotera-modelo.txt", "text/plain")
        st.download_button("Baixar exemplo · PDF", (DATA / "proposals" / "aurora.pdf").read_bytes(), "cotera-exemplo.pdf", "application/pdf")
        st.download_button("Baixar exemplo escaneado · PDF", (DATA / "scanned" / "aurora_escaneada.pdf").read_bytes(), "cotera-exemplo-escaneado.pdf", "application/pdf")
    with evidence:
        st.markdown("#### Conferir a origem")
        proposals = snapshot["proposals"]
        if not proposals:
            st.info("As evidências aparecem aqui após adicionar uma proposta.")
        else:
            chosen = st.selectbox("Documento em conferência", [p["id"] for p in proposals], format_func=lambda i: next((p["draft"]["supplier"] or "Sem fornecedor") + " · " + p["document"]["filename"] for p in proposals if p["id"] == i))
            p = next(p for p in proposals if p["id"] == chosen)
            st.caption(f"Leitura {'com IA' if p['extraction']['mode'] == 'ai' else 'do modelo local'} · {p['extraction']['elapsed_ms']} ms · {p['document']['filename']}")
            show_ocr_notice(p)
            labels = {"supplier": "Fornecedor", "reference": "Referência", "currency": "Moeda", "delivery_days": "Prazo · dias", "freight": "Frete", "discount": "Desconto", "reported_total": "Total declarado"}
            st.dataframe([{"Campo": label, "Valor extraído": str(p["draft"][field]) if p["draft"][field] is not None else "Não informado", "Linha": p["draft"]["evidence"][field]} for field, label in labels.items()], hide_index=True, width="stretch")
            st.markdown("**Texto do documento, com linhas numeradas**")
            st.code("\n".join(f"L{i:03d}  {line}" for i, line in enumerate(p["document"]["lines"], 1)), language=None, wrap_lines=True)
            st.caption("As linhas pertencem ao texto extraído, não às coordenadas visuais do PDF. Confira a associação dos campos, especialmente na extração com IA.")

else:
    st.markdown('<div class="hero">Cada escolha deixa um registro.</div>', unsafe_allow_html=True)
    if not snapshot["decisions"]:
        st.info("Nenhuma decisão registrada. Compare as propostas e documente sua escolha.")
    for d in reversed(snapshot["decisions"]):
        with st.container(border=True):
            st.markdown("**" + d["supplier"] + " · " + brl(d["total"]) + "**")
            st.write(d["reason"])
            st.caption(f"{d['actor']} · {d['created_at']} · versão {d['version']}")
    st.markdown("#### Levar a comparação com você")
    a, b, c = st.columns(3)
    a.download_button("Caderno de compra · HTML", report_html(snapshot), "cotera-comparacao.html", "text/html", width="stretch")
    b.download_button("Comparação · CSV", comparison_csv(snapshot), "cotera-comparacao.csv", "text/csv", width="stretch")
    c.download_button("Dados e evidências · JSON", snapshot_json(snapshot), "cotera-evidencias.json", "application/json", width="stretch")
    st.caption("A exportação inclui somente a cotação selecionada. O JSON contém o texto extraído dos documentos anexados.")

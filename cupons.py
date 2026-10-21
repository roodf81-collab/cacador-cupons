import html
import os
import re
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Chat ID padrão se não for configurado no Secret (garante funcionamento mesmo sem Secret novo)
DEFAULT_CHAT_ID = "742296380"

ARQUIVO_MEMORIA = "historico.txt"
DIAS_VALIDADE_HISTORICO = 14  # Cupons com mais de 14 dias são esquecidos para permitir repetições úteis

# Canais públicos de promoções no Telegram
CANAIS_TELEGRAM = [
    "pechinchou",
    "canaltechofertas",
    "canalpromocoes",
    "achadinhosdashopee",
    "radarcupons",
]

# Palavras que não são cupons reais
PALAVRAS_IGNORAR = {
    "CUPOM", "CUPONS", "SHOPEE", "MELI", "LIVRE", "MERCADO", "MERCADOLIVRE",
    "AQUI", "LINK", "NOLINK", "APROVEITE", "RESGATE", "RESGATAR", "CONFIRA",
    "NOVO", "NOVA", "HOJE", "TODOS", "TODAS", "FRETE", "GRATIS", "OFF",
    "SITE", "APP", "DESCONTO", "DESCONTOS", "OFERTA", "OFERTAS", "PROMO",
    "PROMOCIONAL", "ESPECIAL", "COMPRE", "SELECAO", "SELECIONADOS", "VALE",
    "TELA", "ABAIXO", "DENTRO", "ANTES", "ESCOLHIDA", "MUITOBARATO", "COPIADO",
    "CUPONADO", "CUPONADA", "FINALIZAR", "PAGINA", "PRODUTO", "PRODUTOS",
    "VOUCHER", "VOUCHERS", "EXCLUSIVO", "EXCLUSIVA", "PRIMEIRA", "COMPRA",
    "REGRAS", "TERMOS", "CONDICOES", "BOASCOMPRAS", "PARABENS",
}

PADRAO_CUPOM_TEXTO = re.compile(
    r"(?:cupom|c[oó]digo|use|aplique|c[oó]d|code|voucher)[:\s*`\"'\-👉]*([A-Z0-9_\-]{4,22})",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def carregar_memoria():
    """
    Carrega cupons do histórico.
    Formato suportado:
      - Linha antiga: 'CODIGO'
      - Linha nova: 'CODIGO|DATA_ISO' (para expiração de 14 dias)
    """
    if not os.path.exists(ARQUIVO_MEMORIA):
        return {}

    memoria = {}
    agora = datetime.now(timezone.utc)
    limite_tempo = agora - timedelta(days=DIAS_VALIDADE_HISTORICO)

    with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue

            partes = linha.split("|")
            codigo = partes[0].strip().upper()

            if len(partes) > 1:
                try:
                    data_registro = datetime.fromisoformat(partes[1].strip())
                    if data_registro.tzinfo is None:
                        data_registro = data_registro.replace(tzinfo=timezone.utc)
                    # Se for mais velho que o limite, não carrega (permite ser reencontrado no futuro)
                    if data_registro < limite_tempo:
                        continue
                    memoria[codigo] = data_registro.isoformat()
                except Exception:
                    memoria[codigo] = agora.isoformat()
            else:
                memoria[codigo] = agora.isoformat()

    return memoria


def salvar_memoria(memoria_dict):
    """Salva a memória com data de registro para manter rotatividade de cupons."""
    # Mantém no máximo 1000 cupons recentes
    itens = list(memoria_dict.items())[-1000:]
    with open(ARQUIVO_MEMORIA, "w", encoding="utf-8") as f:
        for codigo, data_str in itens:
            f.write(f"{codigo}|{data_str}\n")


def obter_chat_id():
    chat_id = os.environ.get("CHAT_ID")
    if chat_id and str(chat_id).strip():
        return str(chat_id).strip()
    return DEFAULT_CHAT_ID


def enviar_telegram(chat_id, texto, botoes=None, silencioso=False):
    """Envia mensagem formatada com botões interativos e modo silencioso."""
    if not BOT_TOKEN or not chat_id:
        print("BOT_TOKEN ou CHAT_ID não definidos.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": silencioso,
    }

    if botoes:
        payload["reply_markup"] = {"inline_keyboard": botoes}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"Erro ao enviar Telegram: {r.status_code} - {r.text}")
            return False
        return True
    except Exception as e:
        print(f"Exceção no envio: {e}")
        return False


def e_cupom_valido(codigo):
    if not codigo:
        return False
    codigo = codigo.strip().upper()
    if len(codigo) < 4 or len(codigo) > 22:
        return False
    if codigo.isdigit():
        return False
    if codigo in PALAVRAS_IGNORAR:
        return False
    if any(x in codigo for x in ["HTTP", "WWW", ".COM", ".BR", "/", "="]):
        return False
    return True


def buscar_cupons_pelando():
    fontes = [
        ("Mercado Livre", "https://www.pelando.com.br/cupons-de-descontos/mercadolivre.com.br"),
        ("Shopee", "https://www.pelando.com.br/cupons-de-descontos/shopee.com.br"),
    ]
    resultados = {"Mercado Livre": [], "Shopee": []}

    for loja, url in fontes:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")

            cards = soup.find_all(class_="store-coupons-v2__list")
            for card in cards:
                for item in card.find_all(["article", "li"]):
                    code_el = item.find(class_="card__code-text")
                    if not code_el:
                        continue
                    codigo = code_el.get_text(strip=True).upper()
                    if not e_cupom_valido(codigo):
                        continue

                    title_el = item.find("h3") or item.find(class_="card__title")
                    detalhe = title_el.get_text(strip=True) if title_el else ""
                    detalhe = re.sub(r"^\[.*?\]\s*", "", detalhe)
                    detalhe = re.sub(r"^Cupom\s+(Mercado\s+Livre|Shopee)\s*[-:]*\s*", "", detalhe, flags=re.IGNORECASE)

                    resultados[loja].append({
                        "codigo": codigo,
                        "descricao": detalhe.strip()[:90],
                        "origem": "Pelando",
                    })
        except Exception as e:
            print(f"Erro Pelando ({loja}): {e}")

    return resultados


def buscar_cupons_cuponomia():
    fontes = [
        ("Mercado Livre", "https://www.cuponomia.com.br/desconto/mercado-livre"),
        ("Shopee", "https://www.cuponomia.com.br/desconto/shopee"),
    ]
    resultados = {"Mercado Livre": [], "Shopee": []}

    for loja, url in fontes:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")

            for code_el in soup.find_all(class_="js-itemCode"):
                codigo = code_el.get_text(strip=True).upper()
                if not e_cupom_valido(codigo):
                    continue

                parent = code_el.find_parent("li") or code_el.find_parent("div")
                title_el = parent.find(class_="item-title") if parent else None
                detalhe = title_el.get_text(strip=True) if title_el else ""
                detalhe = re.sub(r"\+\s*\d+.*cashback.*$", "", detalhe, flags=re.IGNORECASE)

                resultados[loja].append({
                    "codigo": codigo,
                    "descricao": detalhe.strip()[:90],
                    "origem": "Cuponomia",
                })
        except Exception as e:
            print(f"Erro Cuponomia ({loja}): {e}")

    return resultados


def buscar_cupons_meliuz():
    fontes = [
        ("Mercado Livre", "https://www.meliuz.com.br/desconto/mercado-livre"),
        ("Shopee", "https://www.meliuz.com.br/desconto/cupom-shopee"),
    ]
    resultados = {"Mercado Livre": [], "Shopee": []}

    for loja, url in fontes:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")

            for btn in soup.find_all(class_="code-btn__value"):
                codigo = btn.get_text(strip=True).upper()
                if not e_cupom_valido(codigo):
                    continue

                parent = btn.find_parent(class_=re.compile(r"offer|card", re.I)) or btn.find_parent("li")
                title_el = parent.find(class_=re.compile(r"title", re.I)) if parent else None
                detalhe = title_el.get_text(strip=True) if title_el else ""

                resultados[loja].append({
                    "codigo": codigo,
                    "descricao": detalhe.strip()[:90],
                    "origem": "Méliuz",
                })
        except Exception as e:
            print(f"Erro Méliuz ({loja}): {e}")

    return resultados


def buscar_cupons_telegram():
    resultados = {"Mercado Livre": [], "Shopee": []}

    for canal in CANAIS_TELEGRAM:
        try:
            r = requests.get(f"https://t.me/s/{canal}", headers=HEADERS, timeout=6)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            postagens = soup.find_all("div", class_="tgme_widget_message_text")

            for post in postagens[-15:]:
                texto = post.get_text(separator=" ")
                texto_min = texto.lower()

                loja = None
                if any(k in texto_min for k in ["shopee", "shp.ee", "s.shopee"]):
                    loja = "Shopee"
                elif any(k in texto_min for k in ["mercado livre", "mercadolivre", "meli"]):
                    loja = "Mercado Livre"

                if not loja:
                    continue

                for match in PADRAO_CUPOM_TEXTO.finditer(texto):
                    codigo = match.group(1).upper()
                    if not e_cupom_valido(codigo):
                        continue

                    linhas = [l.strip() for l in texto.split("\n") if l.strip()]
                    descricao = ""
                    for l in linhas:
                        if any(term in l.lower() for term in ["off", "r$", "%", "desconto"]):
                            descricao = l[:80]
                            break

                    resultados[loja].append({
                        "codigo": codigo,
                        "descricao": descricao,
                        "origem": f"Telegram (@{canal})",
                    })
        except Exception as e:
            print(f"Erro canal @{canal}: {e}")

    return resultados


def formatar_tabela_loja(nome_loja, emoji_loja, cupons):
    if not cupons:
        return ""

    linhas = [
        f"{emoji_loja} <b>{nome_loja.upper()}</b>",
        "┌────────────────────────────────",
    ]

    for item in cupons:
        codigo = item["codigo"]
        desc = html.escape(item.get("descricao", ""))
        origem = html.escape(item.get("origem", ""))

        linhas.append(f"│ 🎟️ <b>Cupom:</b> <code>{codigo}</code> <i>(toque p/ copiar)</i>")
        if desc:
            linhas.append(f"│ 📝 {desc}")
        if origem:
            linhas.append(f"│ 📌 Fonte: {origem}")
        linhas.append("├────────────────────────────────")

    linhas[-1] = "└────────────────────────────────"
    return "\n".join(linhas)


def executar_varredura():
    chat_id = obter_chat_id()
    if not chat_id:
        print("Chat ID não encontrado.")
        return

    memoria_cupons = carregar_memoria()
    fuso_brasil = timezone(timedelta(hours=-3))
    agora_br = datetime.now(fuso_brasil)
    horario_envio = agora_br.strftime("%d/%m/%Y às %H:%M")

    # Modo silencioso entre 23:00 e 07:00 (não vibra/não acorda de madrugada)
    eh_madrugada = agora_br.hour >= 23 or agora_br.hour < 7

    coletas = [
        buscar_cupons_pelando(),
        buscar_cupons_cuponomia(),
        buscar_cupons_meliuz(),
        buscar_cupons_telegram(),
    ]

    novos_ml = {}
    novos_shopee = {}

    for c in coletas:
        for item in c.get("Mercado Livre", []):
            cod = item["codigo"]
            if cod not in memoria_cupons and cod not in novos_ml:
                novos_ml[cod] = item

        for item in c.get("Shopee", []):
            cod = item["codigo"]
            if cod not in memoria_cupons and cod not in novos_shopee:
                novos_shopee[cod] = item

    total_novos = len(novos_ml) + len(novos_shopee)

    if total_novos == 0:
        print(f"[{horario_envio}] Nenhum cupom novo. Silêncio mantido.")
        salvar_memoria(memoria_cupons)
        return

    print(f"[{horario_envio}] Encontrados {total_novos} novos cupons! Enviando...")
    agora_iso = datetime.now(timezone.utc).isoformat()

    # Envio Mercado Livre com botão direto para a loja
    if novos_ml:
        tabela_ml = formatar_tabela_loja("Mercado Livre", "💛", list(novos_ml.values()))
        aviso_noturno = " 🌙 <i>(Silencioso da madrugada)</i>" if eh_madrugada else ""
        msg_ml = (
            f"🏷️ <b>NOVOS CUPONS DISPONÍVEIS</b>{aviso_noturno}\n\n"
            f"{tabela_ml}\n"
            f"⏱️ <i>Verificado em: {horario_envio}</i>"
        )
        botoes_ml = [
            [
                {
                    "text": "🛍️ Abrir Mercado Livre (App/Web)",
                    "url": "https://www.mercadolivre.com.br/cupons",
                }
            ]
        ]
        enviar_telegram(chat_id, msg_ml, botoes=botoes_ml, silencioso=eh_madrugada)
        for cod in novos_ml:
            memoria_cupons[cod] = agora_iso

    # Envio Shopee com botão direto para a página de cupons
    if novos_shopee:
        tabela_shopee = formatar_tabela_loja("Shopee", "🧡", list(novos_shopee.values()))
        aviso_noturno = " 🌙 <i>(Silencioso da madrugada)</i>" if eh_madrugada else ""
        msg_shopee = (
            f"🏷️ <b>NOVOS CUPONS DISPONÍVEIS</b>{aviso_noturno}\n\n"
            f"{tabela_shopee}\n"
            f"⏱️ <i>Verificado em: {horario_envio}</i>"
        )
        botoes_shopee = [
            [
                {
                    "text": "🛍️ Abrir Shopee (Cupons)",
                    "url": "https://shopee.com.br/m/cupons-diarios",
                }
            ]
        ]
        enviar_telegram(chat_id, msg_shopee, botoes=botoes_shopee, silencioso=eh_madrugada)
        for cod in novos_shopee:
            memoria_cupons[cod] = agora_iso

    salvar_memoria(memoria_cupons)


if __name__ == "__main__":
    executar_varredura()

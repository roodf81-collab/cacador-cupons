import html
import os
import re
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ARQUIVO_MEMORIA = "historico.txt"
ARQUIVO_ID = "meu_id.txt"

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

# Regex estrito para identificar códigos reais
# Exige que seja de 4 a 22 chars alfanuméricos e descarta se for apenas texto sem contexto
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
    if not os.path.exists(ARQUIVO_MEMORIA):
        return set()
    with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
        return set(linha.strip().upper() for linha in f if linha.strip())


def salvar_memoria(cupons):
    # Mantém os últimos 1000 cupons
    lista = list(cupons)[-1000:]
    with open(ARQUIVO_MEMORIA, "w", encoding="utf-8") as f:
        for c in lista:
            f.write(f"{c}\n")


def obter_chat_id():
    # 1. Tenta variável de ambiente se configurada nos Secrets
    chat_id = os.environ.get("CHAT_ID")
    if chat_id:
        return str(chat_id).strip()

    # 2. Tenta arquivo local
    if os.path.exists(ARQUIVO_ID):
        with open(ARQUIVO_ID, "r", encoding="utf-8") as f:
            cid = f.read().strip()
            if cid:
                return cid

    # 3. Tenta via getUpdates do Telegram
    if BOT_TOKEN:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            resp = requests.get(url, timeout=10).json()
            mensagens = resp.get("result", [])
            if mensagens:
                cid = str(mensagens[-1]["message"]["chat"]["id"])
                with open(ARQUIVO_ID, "w", encoding="utf-8") as f:
                    f.write(cid)
                return cid
        except Exception as e:
            print(f"Erro ao obter Chat ID via getUpdates: {e}")

    return None


def enviar_mensagem_telegram(chat_id, texto):
    if not BOT_TOKEN or not chat_id:
        print("BOT_TOKEN ou CHAT_ID não definidos.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"Erro ao enviar para Telegram: {r.status_code} - {r.text}")
            return False
        return True
    except Exception as e:
        print(f"Exceção ao enviar Telegram: {e}")
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
    # Evita links ou parâmetros URL acidentais
    if any(x in codigo for x in ["HTTP", "WWW", ".COM", ".BR", "/", "="]):
        return False
    return True


def buscar_cupons_pelando():
    """Busca cupons específicos com regras e limites no Pelando."""
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

                    # Descrição/Título do desconto (ex: 'R$40 OFF acima de R$199')
                    title_el = item.find("h3") or item.find(class_="card__title")
                    detalhe = title_el.get_text(strip=True) if title_el else ""
                    # Limpa prefixos redundantes
                    detalhe = re.sub(r"^\[.*?\]\s*", "", detalhe)
                    detalhe = re.sub(r"^Cupom\s+(Mercado\s+Livre|Shopee)\s*[-:]*\s*", "", detalhe, flags=re.IGNORECASE)

                    resultados[loja].append({
                        "codigo": codigo,
                        "descricao": detalhe.strip()[:90],
                        "origem": "Pelando",
                    })
        except Exception as e:
            print(f"Erro ao buscar Pelando ({loja}): {e}")

    return resultados


def buscar_cupons_cuponomia():
    """Busca códigos no Cuponomia."""
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
            print(f"Erro ao buscar Cuponomia ({loja}): {e}")

    return resultados


def buscar_cupons_meliuz():
    """Busca códigos no Méliuz."""
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
            print(f"Erro ao buscar Méliuz ({loja}): {e}")

    return resultados


def buscar_cupons_telegram():
    """Vasculha canais públicos de promoções procurando estritamente cupons ML e Shopee."""
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

                # Identifica se refere-se a Shopee ou Mercado Livre
                loja = None
                if any(k in texto_min for k in ["shopee", "shp.ee", "s.shopee"]):
                    loja = "Shopee"
                elif any(k in texto_min for k in ["mercado livre", "mercadolivre", "meli"]):
                    loja = "Mercado Livre"

                if not loja:
                    continue

                # Procura padrões de cupom no texto
                for match in PADRAO_CUPOM_TEXTO.finditer(texto):
                    codigo = match.group(1).upper()
                    if not e_cupom_valido(codigo):
                        continue

                    # Pega primeira frase limpa para servir de contexto do desconto
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
            print(f"Erro no canal @{canal}: {e}")

    return resultados


def formatar_tabela_loja(nome_loja, emoji_loja, cupons):
    """
    Formata os cupons em estilo de tabela limpa.
    O código fica em <code>CUPOM</code> para copiar com 1 toque no celular.
    """
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

    # Substitui a última linha separadora pelo fechamento da caixa
    linhas[-1] = "└────────────────────────────────"
    return "\n".join(linhas)


def executar_varredura():
    chat_id = obter_chat_id()
    if not chat_id:
        print("Chat ID não encontrado. O bot não pode enviar mensagens.")
        return

    ja_enviados = carregar_memoria()
    fuso_brasil = timezone(timedelta(hours=-3))
    horario_envio = datetime.now(fuso_brasil).strftime("%d/%m/%Y às %H:%M")

    # Coleta de todas as fontes
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
            if cod not in ja_enviados and cod not in novos_ml:
                novos_ml[cod] = item

        for item in c.get("Shopee", []):
            cod = item["codigo"]
            if cod not in ja_enviados and cod not in novos_shopee:
                novos_shopee[cod] = item

    total_novos = len(novos_ml) + len(novos_shopee)

    if total_novos == 0:
        print(f"[{horario_envio}] Nenhum cupom novo encontrado. Nenhuma notificação enviada.")
        return

    print(f"[{horario_envio}] Encontrados {total_novos} novos cupons! Enviando...")

    # Envia Mercado Livre (se houver) em tabela separada
    if novos_ml:
        tabela_ml = formatar_tabela_loja("Mercado Livre", "💛", list(novos_ml.values()))
        msg_ml = (
            "🏷️ <b>NOVOS CUPONS DISPONÍVEIS</b>\n\n"
            f"{tabela_ml}\n"
            f"⏱️ <i>Verificado em: {horario_envio}</i>"
        )
        enviar_mensagem_telegram(chat_id, msg_ml)
        for cod in novos_ml:
            ja_enviados.add(cod)

    # Envia Shopee (se houver) em tabela separada
    if novos_shopee:
        tabela_shopee = formatar_tabela_loja("Shopee", "🧡", list(novos_shopee.values()))
        msg_shopee = (
            "🏷️ <b>NOVOS CUPONS DISPONÍVEIS</b>\n\n"
            f"{tabela_shopee}\n"
            f"⏱️ <i>Verificado em: {horario_envio}</i>"
        )
        enviar_mensagem_telegram(chat_id, msg_shopee)
        for cod in novos_shopee:
            ja_enviados.add(cod)

    salvar_memoria(ja_enviados)


if __name__ == "__main__":
    executar_varredura()

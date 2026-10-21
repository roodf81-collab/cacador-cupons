from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
from bs4 import BeautifulSoup
import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Canais gerais + canais com forte presença de Shopee
MEUS_CANAIS = [
    "promobitoficial",
    "pelando",
    "economizeiro",
    "gafanhotocupons",
    "pechinchou",
    "canaltechofertas",
    "achadinhosdashopee",
    "descontostop",
]

# Fontes da Web reforçadas para Shopee e Mercado Livre
SITES_WEB = [
    ("Mercado Livre", "https://www.cuponomia.com.br/desconto/mercado-livre"),
    ("Shopee", "https://www.cuponomia.com.br/desconto/shopee"),
    ("Shopee", "https://www.meliuz.com.br/desconto/cupom-shopee"),
]

ARQUIVO_MEMORIA = "historico.txt"
ARQUIVO_ID = "meu_id.txt"

# 1. Padrão para códigos digitáveis (Mercado Livre e Shopee)
PADRAO_CUPOM = re.compile(
    r"(?:cupom|código|codigo|use|aplique|cód|code|promo)[:\s*`\"'\-👉]*([A-Z0-9]{4,18})",
    re.IGNORECASE,
)

# 2. Padrão para links diretos da Shopee (quando o cupom é de clicar/resgatar)
PADRAO_LINK_SHOPEE = re.compile(
    r"(https?://(?:s\.shopee\.com\.br|shp\.ee|shopee\.com\.br)/[^\s)\"<>]+)",
    re.IGNORECASE,
)

PALAVRAS_IGNORAR = {
    "NO",
    "NA",
    "DO",
    "DA",
    "DE",
    "AQUI",
    "LINK",
    "APP",
    "TELA",
    "HOJE",
    "PARA",
    "COM",
    "MAIS",
    "SITE",
    "LOJA",
    "ESSE",
    "ESTE",
    "NOVO",
    "CUPOM",
    "SHOPEE",
    "MELI",
    "LIVRE",
    "GRATIS",
    "FRETE",
    "TODOS",
    "TODAS",
    "LIBERADO",
    "DISPONIVEL",
    "RESGATE",
    "ABAIXO",
}


def carregar_memoria():
    if not os.path.exists(ARQUIVO_MEMORIA):
        return set()
    with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
        return set(linha.strip() for linha in f if linha.strip())


def salvar_memoria(cupons):
    lista_recente = list(cupons)[-600:]
    with open(ARQUIVO_MEMORIA, "w", encoding="utf-8") as f:
        for c in lista_recente:
            f.write(f"{c}\n")


def enviar_telegram(chat_id, texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    requests.post(url, json=payload, timeout=10)


def obter_meu_contato():
    if os.path.exists(ARQUIVO_ID):
        with open(ARQUIVO_ID, "r", encoding="utf-8") as f:
            meu_id = f.read().strip()
            if meu_id:
                return meu_id

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    dados = requests.get(url, timeout=10).json()
    mensagens = dados.get("result", [])
    if not mensagens:
        return None

    meu_id = str(mensagens[-1]["message"]["chat"]["id"])
    with open(ARQUIVO_ID, "w", encoding="utf-8") as f:
        f.write(meu_id)
    return meu_id


def identificar_loja(texto_min):
    if any(
        x in texto_min
        for x in ["shopee", "s.shopee.com.br", "shp.ee", "moedas shopee"]
    ):
        return "Shopee"
    elif any(
        x in texto_min
        for x in ["mercado livre", "mercadolivre", "meli", "mercadolivre.com"]
    ):
        return "Mercado Livre"
    return None


def executar_varredura():
    chat_id = obter_meu_contato()
    if not chat_id:
        print("Chat ID não encontrado.")
        return

    ja_enviados = carregar_memoria()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    fuso_brasil = timezone(timedelta(hours=-3))
    horario_envio = datetime.now(fuso_brasil).strftime("%d/%m/%Y às %H:%M")

    novos_por_loja = {"Mercado Livre": [], "Shopee": []}

    # 1. Vasculha os canais do Telegram
    for canal in MEUS_CANAIS:
        try:
            html = requests.get(
                f"https://t.me/s/{canal}", headers=headers, timeout=10
            ).text
            soup = BeautifulSoup(html, "html.parser")
            postagens = soup.find_all("div", class_="tgme_widget_message_text")

            for post in postagens[-20:]:
                texto = post.get_text(separator=" ")
                texto_min = texto.lower()
                loja = identificar_loja(texto_min)
                if not loja:
                    continue

                resumo = (
                    texto[:100].strip() + "..."
                    if len(texto) > 100
                    else texto.strip()
                )
                achou_codigo = False

                # A) Tenta achar código digitável (Ex: GANHE20)
                for match in PADRAO_CUPOM.finditer(texto):
                    codigo = match.group(1).upper()
                    if (
                        codigo not in PALAVRAS_IGNORAR
                        and not codigo.isdigit()
                        and codigo not in ja_enviados
                    ):
                        ja_enviados.add(codigo)
                        achou_codigo = True
                        novos_por_loja[loja].append(
                            f"• 🎟️ Código: <code>{codigo}</code> (@{canal})\n  <i>{resumo}</i>"
                        )

                # B) Especial Shopee: se a postagem fala de "cupom" na Shopee, mas é por LINK de resgate
                if (
                    loja == "Shopee"
                    and not achou_codigo
                    and "cupom" in texto_min
                ):
                    links = PADRAO_LINK_SHOPEE.findall(texto)
                    # Pega também links que estão escondidos nos botões/âncoras do HTML
                    if not links:
                        for a in post.find_all("a", href=True):
                            if "shopee" in a["href"] or "shp.ee" in a["href"]:
                                links.append(a["href"])

                    if links:
                        link_cupom = links[0]
                        id_unico = (
                            "SHP_"
                            + hashlib.md5(link_cupom.encode()).hexdigest()[:10]
                        )
                        if id_unico not in ja_enviados:
                            ja_enviados.add(id_unico)
                            novos_por_loja["Shopee"].append(
                                f"• 🔗 <b>Cupom de Resgate no App</b> (@{canal})\n"
                                f"  👉 <a href='{link_cupom}'>Clique aqui para resgatar na Shopee</a>\n"
                                f"  <i>{resumo}</i>"
                            )
        except Exception as e:
            print(f"Erro no canal {canal}: {e}")

    # 2. Vasculha páginas da Web
    for loja, url in SITES_WEB:
        try:
            html = requests.get(url, headers=headers, timeout=10).text
            soup = BeautifulSoup(html, "html.parser")
            texto_web = soup.get_text(separator=" ")

            for match in PADRAO_CUPOM.finditer(texto_web):
                codigo = match.group(1).upper()
                if (
                    codigo not in PALAVRAS_IGNORAR
                    and not codigo.isdigit()
                    and codigo not in ja_enviados
                ):
                    ja_enviados.add(codigo)
                    novos_por_loja[loja].append(
                        f"• 🎟️ Código: <code>{codigo}</code> | Fonte: Web"
                    )
        except Exception as e:
            print(f"Erro no site {loja}: {e}")

    total_novos = len(novos_por_loja["Mercado Livre"]) + len(
        novos_por_loja["Shopee"]
    )

    # 3. Monta a mensagem final separada por loja
    if total_novos > 0:
        partes_msg = ["🛒 <b>RELATÓRIO DE NOVOS CUPONS</b>\n"]

        if novos_por_loja["Mercado Livre"]:
            partes_msg.append("💛 <b>MERCADO LIVRE</b>")
            partes_msg.append("──────────────────")
            partes_msg.extend(novos_por_loja["Mercado Livre"][:10])
            partes_msg.append("")

        if novos_por_loja["Shopee"]:
            partes_msg.append("🧡 <b>SHOPEE</b>")
            partes_msg.append("──────────────────")
            partes_msg.extend(novos_por_loja["Shopee"][:10])
            partes_msg.append("")

        partes_msg.append("──────────────────")
        partes_msg.append(f"⏱️ <i>Verificado em: {horario_envio}</i>")

        enviar_telegram(chat_id, "\n".join(partes_msg))
        salvar_memoria(ja_enviados)
    else:
        msg_sem_cupom = (
            "✅ <b>STATUS DO BOT: ATIVO</b>\n"
            "──────────────────\n"
            "🔍 Fiz a varredura nos canais e na web, mas <b>não há novos cupons</b> da Shopee ou Mercado Livre neste momento.\n"
            "──────────────────\n"
            f"⏱️ <i>Verificado em: {horario_envio}</i>"
        )
        enviar_telegram(chat_id, msg_sem_cupom)


if __name__ == "__main__":
    executar_varredura()

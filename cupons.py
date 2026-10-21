import os
import re
from bs4 import BeautifulSoup
import requests

# Pega o Token de forma segura das configurações do GitHub
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Coloque aqui os @ dos canais que você segue no Telegram (sem o @)
MEUS_CANAIS = [
    "promobitoficial",
    "pelando",
    "economizeiro",
    "gafanhotocupons",
]

# Páginas da Web com cupons atualizados
SITES_WEB = {
    "Mercado Livre 💛": "https://www.cuponomia.com.br/desconto/mercado-livre",
    "Shopee 🧡": "https://www.cuponomia.com.br/desconto/shopee",
    "AliExpress ❤️": "https://www.cuponomia.com.br/desconto/aliexpress",
}

ARQUIVO_MEMORIA = "historico.txt"

PADRAO_CUPOM = re.compile(
    r"(?:cupom|código|codigo|use|aplique|cód|code|promo)[:\s*`\"']*([A-Z0-9]{4,18})",
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
}


def carregar_memoria():
    if not os.path.exists(ARQUIVO_MEMORIA):
        return set()
    with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
        return set(linha.strip() for linha in f if linha.strip())


def salvar_memoria(cupons):
    # Mantém os últimos 500 cupons salvos para o arquivo ficar sempre leve
    lista_recente = list(cupons)[-500:]
    with open(ARQUIVO_MEMORIA, "w", encoding="utf-8") as f:
        for c in lista_recente:
            f.write(f"{c}\n")


def descobrir_meu_contato():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    dados = requests.get(url, timeout=10).json()
    mensagens = dados.get("result", [])
    if not mensagens:
        print(
            "⚠️ Envie um 'Oi' para o seu bot no Telegram para registrar seu contato!"
        )
        return None
    return mensagens[-1]["message"]["chat"]["id"]


def enviar_telegram(chat_id, texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    requests.post(url, json=payload, timeout=10)


def identificar_loja(texto_min):
    if any(x in texto_min for x in ["mercado livre", "mercadolivre", "meli"]):
        return "Mercado Livre 💛"
    elif "shopee" in texto_min:
        return "Shopee 🧡"
    elif any(x in texto_min for x in ["aliexpress", "ali express", "ali"]):
        return "AliExpress ❤️"
    return None


def executar_varredura():
    chat_id = descobrir_meu_contato()
    if not chat_id:
        return

    ja_enviados = carregar_memoria()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # 1. Vasculha os seus canais do Telegram
    for canal in MEUS_CANAIS:
        try:
            html = requests.get(
                f"https://t.me/s/{canal}", headers=headers, timeout=10
            ).text
            soup = BeautifulSoup(html, "html.parser")
            postagens = soup.find_all("div", class_="tgme_widget_message_text")

            for post in postagens[-10:]:
                texto = post.get_text(separator="\n")
                loja = identificar_loja(texto.lower())
                if not loja:
                    continue

                for match in PADRAO_CUPOM.finditer(texto):
                    codigo = match.group(1).upper()
                    if (
                        codigo not in PALAVRAS_IGNORAR
                        and codigo not in ja_enviados
                    ):
                        ja_enviados.add(codigo)
                        msg = (
                            f"🎟️ <b>CUPOM {loja.upper()}</b> (Canal @{canal})\n\n"
                            f"📋 Toque para copiar: <code>{codigo}</code>\n\n"
                            f"📝 <b>Detalhes:</b>\n{texto[:350]}"
                        )
                        enviar_telegram(chat_id, msg)
        except Exception as e:
            print(f"Erro no canal {canal}: {e}")

    # 2. Vasculha páginas da Web
    for loja, url in SITES_WEB.items():
        try:
            html = requests.get(url, headers=headers, timeout=10).text
            soup = BeautifulSoup(html, "html.parser")
            texto_web = soup.get_text(separator=" ")

            for match in PADRAO_CUPOM.finditer(texto_web):
                codigo = match.group(1).upper()
                if codigo not in PALAVRAS_IGNORAR and codigo not in ja_enviados:
                    ja_enviados.add(codigo)
                    msg = (
                        f"🌐 <b>CUPOM {loja.upper()} (Web)</b>\n\n"
                        f"📋 Toque para copiar: <code>{codigo}</code>\n"
                        f"🔗 Fonte: {url}"
                    )
                    enviar_telegram(chat_id, msg)
        except Exception as e:
            print(f"Erro no site {loja}: {e}")

    salvar_memoria(ja_enviados)


if __name__ == "__main__":
    executar_varredura()
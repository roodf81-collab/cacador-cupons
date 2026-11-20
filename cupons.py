import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Chat ID padrão se não for configurado no Secret (garante funcionamento mesmo sem Secret novo)
DEFAULT_CHAT_ID = "742296380"

ARQUIVO_MEMORIA = "historico.txt"
ARQUIVO_CONFIG = "config.json"
DIAS_VALIDADE_HISTORICO = 14  # Cupons com mais de 14 dias são esquecidos para permitir repetições úteis

CONFIG_PADRAO = {
    "lojas_ativas": ["Mercado Livre", "Shopee"],
    "canais_ativos": [
        "CuponsTecnan",
        "pechinchou",
        "canaltechofertas",
        "canalpromocoes",
        "achadinhosdashopee",
        "radarcupons",
    ],
    "ultimo_update_id": 0,
    "canal_cupons_id": None,
}

INFO_LOJAS = {
    "Mercado Livre": {
        "emoji": "💛",
        "url_botao": "https://www.mercadolivre.com.br/cupons",
        "texto_botao": "🛍️ Abrir Mercado Livre (App/Web)",
        "termos_canal": ["mercado livre", "mercadolivre", "meli"],
        "pelando_url": "https://www.pelando.com.br/cupons-de-descontos/mercadolivre.com.br",
        "cuponomia_url": "https://www.cuponomia.com.br/desconto/mercado-livre",
        "meliuz_url": "https://www.meliuz.com.br/desconto/mercado-livre",
    },
    "Shopee": {
        "emoji": "🧡",
        "url_botao": "https://shopee.com.br/m/cupons-diarios",
        "texto_botao": "🛍️ Abrir Shopee (Cupons)",
        "termos_canal": ["shopee", "shp.ee", "s.shopee"],
        "pelando_url": "https://www.pelando.com.br/cupons-de-descontos/shopee.com.br",
        "cuponomia_url": "https://www.cuponomia.com.br/desconto/shopee",
        "meliuz_url": "https://www.meliuz.com.br/desconto/cupom-shopee",
    },
    "AliExpress": {
        "emoji": "🔴",
        "url_botao": "https://best.aliexpress.com",
        "texto_botao": "🛍️ Abrir AliExpress (App/Web)",
        "termos_canal": ["aliexpress", "ali express", "ali.ski", "s.click.aliexpress"],
        "pelando_url": "https://www.pelando.com.br/cupons-de-descontos/aliexpress",
        "cuponomia_url": "https://www.cuponomia.com.br/desconto/aliexpress",
        "meliuz_url": "https://www.meliuz.com.br/desconto/cupom-aliexpress",
    },
    "Amazon": {
        "emoji": "📦",
        "url_botao": "https://www.amazon.com.br/cupons",
        "texto_botao": "🛍️ Abrir Amazon (Cupons)",
        "termos_canal": ["amazon", "amzn.to", "amzn.id"],
        "pelando_url": "https://www.pelando.com.br/cupons-de-descontos/amazon",
        "cuponomia_url": "https://www.cuponomia.com.br/desconto/amazon",
        "meliuz_url": "https://www.meliuz.com.br/desconto/cupom-amazon",
    },
}

PALAVRAS_IGNORAR = {
    "CUPOM", "CUPONS", "SHOPEE", "MELI", "LIVRE", "MERCADO", "MERCADOLIVRE",
    "ALIEXPRESS", "AMAZON", "AQUI", "LINK", "NOLINK", "APROVEITE", "RESGATE",
    "RESGATAR", "CONFIRA", "NOVO", "NOVA", "HOJE", "TODOS", "TODAS", "FRETE",
    "GRATIS", "OFF", "SITE", "APP", "DESCONTO", "DESCONTOS", "OFERTA",
    "OFERTAS", "PROMO", "PROMOCIONAL", "ESPECIAL", "COMPRE", "SELECAO",
    "SELECIONADOS", "VALE", "TELA", "ABAIXO", "DENTRO", "ANTES", "ESCOLHIDA",
    "MUITOBARATO", "COPIADO", "CUPONADO", "CUPONADA", "FINALIZAR", "PAGINA",
    "PRODUTO", "PRODUTOS", "VOUCHER", "VOUCHERS", "EXCLUSIVO", "EXCLUSIVA",
    "PRIMEIRA", "COMPRA", "REGRAS", "TERMOS", "CONDICOES", "BOASCOMPRAS",
    "PARABENS",
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


def carregar_config():
    """Carrega as configurações salvas ou restaura o padrão se não existir."""
    if not os.path.exists(ARQUIVO_CONFIG):
        salvar_config(CONFIG_PADRAO)
        return CONFIG_PADRAO.copy()
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in CONFIG_PADRAO.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception as e:
        print(f"Erro ao carregar config.json: {e}")
        return CONFIG_PADRAO.copy()


def salvar_config(config):
    """Salva as configurações atualizadas em arquivo JSON."""
    try:
        with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar config.json: {e}")


def carregar_memoria():
    """Carrega cupons do histórico com controle de validade."""
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
            # Se a formatação HTML falhou (erro 400 do Telegram), tenta reenviar como texto puro
            if "parse_mode" in payload:
                payload.pop("parse_mode", None)
                r_fallback = requests.post(url, json=payload, timeout=10)
                if r_fallback.ok:
                    return True
            print(f"Erro ao enviar Telegram: {r.status_code} - {r.text}")
            return False
        return True
    except Exception as e:
        print(f"Exceção no envio: {e}")
        return False


def normalizar_nome_loja(texto):
    """Converte termos informais para o nome oficial da loja."""
    t = texto.strip().lower()
    if t in ["ml", "mercado livre", "mercadolivre", "meli"]:
        return "Mercado Livre"
    if t in ["shopee", "shope", "shoppe"]:
        return "Shopee"
    if t in ["ali", "aliexpress", "ali express"]:
        return "AliExpress"
    if t in ["amazon", "amz"]:
        return "Amazon"
    return None


def processar_comandos_telegram(chat_id, config):
    """
    Verifica se o usuário enviou comandos de texto ou áudio pelo Telegram
    para alterar lojas, canais ou configurações remotamente.
    """
    if not BOT_TOKEN or not chat_id:
        return

    offset = config.get("ultimo_update_id", 0) + 1
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 5}

    try:
        resp = requests.get(url, params=params, timeout=10).json()
    except Exception as e:
        print(f"Erro ao buscar comandos getUpdates: {e}")
        return

    updates = resp.get("result", [])
    if not updates:
        return

    ultimo_id = config.get("ultimo_update_id", 0)

    for u in updates:
        up_id = u.get("update_id", 0)
        if up_id > ultimo_id:
            ultimo_id = up_id

        # Detecção automática do Canal de Cupons (quando bot vira admin ou quando há post no canal)
        mcm = u.get("my_chat_member")
        if mcm and mcm.get("chat", {}).get("type") == "channel":
            cid = mcm["chat"]["id"]
            title = mcm["chat"].get("title", "Canal de Cupons")
            if config.get("canal_cupons_id") != cid:
                config["canal_cupons_id"] = cid
                enviar_telegram(
                    chat_id,
                    f"🎉 <b>Canal vinculado com sucesso!</b>\n"
                    f"A partir de agora, os cupons serão enviados para o canal <b>{title}</b>.\n\n"
                    f"Sua conversa privada aqui fica 100% limpa e exclusiva para configurações!"
                )

        cp = u.get("channel_post")
        if cp and cp.get("chat", {}).get("type") == "channel":
            cid = cp["chat"]["id"]
            title = cp["chat"].get("title", "Canal de Cupons")
            if config.get("canal_cupons_id") != cid:
                config["canal_cupons_id"] = cid
                enviar_telegram(
                    chat_id,
                    f"🎉 <b>Canal vinculado com sucesso!</b>\n"
                    f"A partir de agora, os cupons serão enviados para o canal <b>{title}</b>.\n\n"
                    f"Sua conversa privada aqui fica 100% limpa e exclusiva para configurações!"
                )

        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue

        remetente_id = str(msg.get("chat", {}).get("id", ""))
        if remetente_id != str(chat_id):
            continue

        # Mensagem de áudio
        if "voice" in msg or "audio" in msg:
            texto_ajuda = (
                "🎙️ <i>Recebi sua mensagem de áudio!</i>\n\n"
                "Para alterar as configurações, use os comandos em texto:\n"
                "• <code>/status</code> - Vê o que está ativo\n"
                "• <code>/ativar aliexpress</code> (ou ml, shopee, amazon)\n"
                "• <code>/desativar shopee</code>\n"
                "• <code>/addcanal nome_do_canal</code>\n"
                "• <code>/menu</code> - Ver todas as opções"
            )
            enviar_telegram(chat_id, texto_ajuda)
            continue

        texto = msg.get("text", "").strip()
        if not texto:
            continue

        partes = texto.split(maxsplit=1)
        comando = partes[0].lower()
        parametro = partes[1].strip() if len(partes) > 1 else ""

        # Remove barra inicial se houver
        if comando.startswith("/"):
            cmd_puro = comando[1:]
        else:
            cmd_puro = comando

        if cmd_puro in ["start", "menu", "ajuda", "help"]:
            menu = (
                "🤖 <b>PAINEL DE CONTROLE DO CAÇADOR DE CUPONS</b>\n"
                "────────────────────────────────\n"
                "Você pode editar o bot de qualquer lugar pelo celular:\n\n"
                "📊 <b>CONSULTA:</b>\n"
                "• <code>/status</code> - Lojas e canais ativos no momento\n\n"
                "🏬 <b>ATIVAR / DESATIVAR LOJAS:</b>\n"
                "• <code>/ativar ml</code>\n"
                "• <code>/ativar shopee</code>\n"
                "• <code>/ativar aliexpress</code>\n"
                "• <code>/ativar amazon</code>\n"
                "• <code>/desativar shopee</code> (ou ml, aliexpress, etc.)\n\n"
                "📢 <b>CANAIS DO TELEGRAM:</b>\n"
                "• <code>/addcanal CuponsTecnan</code> (sem @)\n"
                "• <code>/rmcanal canal_antigo</code>\n\n"
                "⚡ <b>AÇÕES:</b>\n"
                "• <code>/limpar</code> - Limpa histórico para reenviar cupons\n"
                "• <code>/buscar</code> - Confirma status da varredura"
            )
            enviar_telegram(chat_id, menu)

        elif cmd_puro in ["status", "satus", "staus", "config"]:
            lojas_msg = []
            for loja in INFO_LOJAS.keys():
                emoji = INFO_LOJAS[loja]["emoji"]
                if loja in config["lojas_ativas"]:
                    lojas_msg.append(f"• {emoji} <b>{loja}:</b> ✅ ATIVO")
                else:
                    lojas_msg.append(f"• {emoji} <b>{loja}:</b> ❌ DESATIVADO")

            canais_msg = [f"• @{c}" for c in config["canais_ativos"]]
            canal_destino = config.get("canal_cupons_id")
            destino_str = f"Canal ID {canal_destino} ✅" if canal_destino else "Conversa Privada (ainda não vinculado)"
            status_txt = (
                "⚙️ <b>CONFIGURAÇÃO ATUAL DO BOT</b>\n"
                "────────────────────────────────\n"
                f"📢 <b>Destino dos Cupons:</b> {destino_str}\n\n"
                "🏬 <b>Lojas Monitoradas:</b>\n"
                + "\n".join(lojas_msg)
                + "\n\n"
                + f"📡 <b>Fontes Monitoradas ({len(config['canais_ativos'])}):</b>\n"
                + "\n".join(canais_msg)
                + "\n────────────────────────────────\n"
                "<i>Digite /menu para alterar opções</i>"
            )
            enviar_telegram(chat_id, status_txt)

        elif cmd_puro in ["ativar", "enable"]:
            if not parametro:
                enviar_telegram(
                    chat_id,
                    "❓ Qual loja você quer ativar?\nExemplo: <code>/ativar aliexpress</code> ou <code>/ativar shopee</code>"
                )
            else:
                loja = normalizar_nome_loja(parametro)
                if loja:
                    if loja not in config["lojas_ativas"]:
                        config["lojas_ativas"].append(loja)
                        enviar_telegram(
                            chat_id,
                            f"✅ Loja <b>{loja}</b> foi <b>ATIVADA</b> com sucesso!\nO bot já começará a buscar cupons dela."
                        )
                    else:
                        enviar_telegram(chat_id, f"ℹ️ A loja <b>{loja}</b> já está ativa nas buscas.")
                else:
                    enviar_telegram(
                        chat_id,
                        "❓ Loja não reconhecida.\nLojas disponíveis: <code>ml</code>, <code>shopee</code>, <code>aliexpress</code>, <code>amazon</code>."
                    )

        elif cmd_puro in ["desativar", "disable"]:
            if not parametro:
                enviar_telegram(
                    chat_id,
                    "❓ Qual loja você quer desativar?\nExemplo: <code>/desativar shopee</code>"
                )
            else:
                loja = normalizar_nome_loja(parametro)
                if loja:
                    if loja in config["lojas_ativas"]:
                        config["lojas_ativas"].remove(loja)
                        enviar_telegram(
                            chat_id,
                            f"🛑 Loja <b>{loja}</b> foi <b>DESATIVADA</b>!\nO bot não buscará mais cupons dela."
                        )
                    else:
                        enviar_telegram(chat_id, f"ℹ️ A loja <b>{loja}</b> já não estava ativa.")
                else:
                    enviar_telegram(
                        chat_id,
                        "❓ Loja não reconhecida.\nLojas disponíveis: <code>ml</code>, <code>shopee</code>, <code>aliexpress</code>, <code>amazon</code>."
                    )

        elif cmd_puro in ["addcanal", "adicionarcanal", "add_canal"]:
            if not parametro:
                enviar_telegram(
                    chat_id,
                    "❓ Qual canal deseja adicionar?\nExemplo: <code>/addcanal CuponsTecnan</code>"
                )
            else:
                canal_limpo = parametro.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
                if canal_limpo:
                    if canal_limpo not in config["canais_ativos"]:
                        config["canais_ativos"].append(canal_limpo)
                        enviar_telegram(
                            chat_id,
                            f"✅ Canal <b>@{canal_limpo}</b> adicionado à lista de monitoramento!"
                        )
                    else:
                        enviar_telegram(chat_id, f"ℹ️ O canal <b>@{canal_limpo}</b> já está na lista.")

        elif cmd_puro in ["rmcanal", "removercanal", "delcanal"]:
            if not parametro:
                enviar_telegram(
                    chat_id,
                    "❓ Qual canal deseja remover?\nExemplo: <code>/rmcanal radarcupons</code>"
                )
            else:
                canal_limpo = parametro.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
                if canal_limpo in config["canais_ativos"]:
                    config["canais_ativos"].remove(canal_limpo)
                    enviar_telegram(
                        chat_id,
                        f"🗑️ Canal <b>@{canal_limpo}</b> foi removido do monitoramento."
                    )
                else:
                    enviar_telegram(
                        chat_id,
                        f"⚠️ Canal <b>@{canal_limpo}</b> não foi encontrado na lista de canais ativos."
                    )

        elif cmd_puro in ["limpar", "reset", "clear"]:
            salvar_memoria({})
            enviar_telegram(
                chat_id,
                "🧹 <b>Histórico de cupons limpo!</b>\nTodos os cupons válidos disponíveis serão reenviados nesta rodada."
            )

        elif cmd_puro in ["buscar", "varrer"]:
            enviar_telegram(chat_id, "🔍 <i>Processando varredura com as configurações atuais...</i>")

        else:
            enviar_telegram(chat_id, "❓ Comando não reconhecido. Digite <code>/menu</code> para ver as opções disponíveis.")

    config["ultimo_update_id"] = ultimo_id
    salvar_config(config)


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


def buscar_cupons_pelando(lojas_ativas):
    resultados = {loja: [] for loja in lojas_ativas}

    for loja in lojas_ativas:
        info = INFO_LOJAS.get(loja)
        if not info or "pelando_url" not in info:
            continue
        url = info["pelando_url"]

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
                    detalhe = re.sub(
                        r"^Cupom\s+(Mercado\s+Livre|Shopee|AliExpress|Amazon)\s*[-:]*\s*",
                        "",
                        detalhe,
                        flags=re.IGNORECASE,
                    )

                    resultados[loja].append({
                        "codigo": codigo,
                        "descricao": detalhe.strip()[:90],
                        "origem": "Pelando",
                    })
        except Exception as e:
            print(f"Erro Pelando ({loja}): {e}")

    return resultados


def buscar_cupons_cuponomia(lojas_ativas):
    resultados = {loja: [] for loja in lojas_ativas}

    for loja in lojas_ativas:
        info = INFO_LOJAS.get(loja)
        if not info or "cuponomia_url" not in info:
            continue
        url = info["cuponomia_url"]

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


def buscar_cupons_meliuz(lojas_ativas):
    resultados = {loja: [] for loja in lojas_ativas}

    for loja in lojas_ativas:
        info = INFO_LOJAS.get(loja)
        if not info or "meliuz_url" not in info:
            continue
        url = info["meliuz_url"]

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


def buscar_cupons_telegram(canais_ativos, lojas_ativas):
    resultados = {loja: [] for loja in lojas_ativas}

    for canal in canais_ativos:
        try:
            r = requests.get(f"https://t.me/s/{canal}", headers=HEADERS, timeout=6)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            postagens = soup.find_all("div", class_="tgme_widget_message_text")

            for post in postagens[-15:]:
                texto = post.get_text(separator=" ")
                texto_min = texto.lower()

                # Identifica qual loja ativa corresponde ao post
                loja_detectada = None
                for loja in lojas_ativas:
                    termos = INFO_LOJAS.get(loja, {}).get("termos_canal", [])
                    if any(termo in texto_min for termo in termos):
                        loja_detectada = loja
                        break

                if not loja_detectada:
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

                    resultados[loja_detectada].append({
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

    # 1. Carrega configurações e processa comandos enviados pelo Telegram no celular
    config = carregar_config()
    processar_comandos_telegram(chat_id, config)
    salvar_config(config)

    lojas_ativas = config.get("lojas_ativas", ["Mercado Livre", "Shopee"])
    canais_ativos = config.get("canais_ativos", [])

    memoria_cupons = carregar_memoria()
    fuso_brasil = timezone(timedelta(hours=-3))
    agora_br = datetime.now(fuso_brasil)
    horario_envio = agora_br.strftime("%d/%m/%Y às %H:%M")

    # Não verifica entre 23:00 e 07:00 (repouso na madrugada)
    if agora_br.hour >= 23 or agora_br.hour < 7:
        print(f"[{horario_envio}] Período noturno (23h às 07h). Varredura suspensa para repouso.")
        return

    if not lojas_ativas:
        print("Nenhuma loja ativa para busca.")
        return

    coletas = [
        buscar_cupons_pelando(lojas_ativas),
        buscar_cupons_cuponomia(lojas_ativas),
        buscar_cupons_meliuz(lojas_ativas),
        buscar_cupons_telegram(canais_ativos, lojas_ativas),
    ]

    novos_por_loja = {loja: {} for loja in lojas_ativas}

    for c in coletas:
        for loja in lojas_ativas:
            for item in c.get(loja, []):
                cod = item["codigo"]
                if cod not in memoria_cupons and cod not in novos_por_loja[loja]:
                    novos_por_loja[loja][cod] = item

    total_novos = sum(len(itens) for itens in novos_por_loja.values())

    if total_novos == 0:
        print(f"[{horario_envio}] Nenhum cupom novo encontrado.")
        lojas_str = ", ".join(lojas_ativas)
        msg_sem_cupom = (
            "🔍 <b>STATUS: VARREDURA CONCLUÍDA</b>\n"
            "────────────────────────────────\n"
            f"Fiz a busca nos canais e sites parceiros, mas <b>não há cupons novos</b> de {lojas_str} neste momento.\n"
            "────────────────────────────────\n"
            f"⏱️ <i>Verificado em: {horario_envio}</i>"
        )
        destino_cupons = config.get("canal_cupons_id") or chat_id
        enviar_telegram(destino_cupons, msg_sem_cupom)
        salvar_memoria(memoria_cupons)
        return

    print(f"[{horario_envio}] Encontrados {total_novos} novos cupons! Enviando...")
    agora_iso = datetime.now(timezone.utc).isoformat()
    destino_cupons = config.get("canal_cupons_id") or chat_id

    for loja in lojas_ativas:
        itens_loja = list(novos_por_loja[loja].values())
        if not itens_loja:
            continue

        info = INFO_LOJAS.get(loja, {})
        emoji = info.get("emoji", "🏷️")
        url_btn = info.get("url_botao")
        txt_btn = info.get("texto_botao", f"🛍️ Abrir {loja}")

        tabela = formatar_tabela_loja(loja, emoji, itens_loja)
        msg = (
            "🏷️ <b>NOVOS CUPONS DISPONÍVEIS</b>\n\n"
            f"{tabela}\n"
            f"⏱️ <i>Verificado em: {horario_envio}</i>"
        )

        botoes = None
        if url_btn:
            botoes = [[{"text": txt_btn, "url": url_btn}]]

        enviar_telegram(destino_cupons, msg, botoes=botoes)

        for cod in novos_por_loja[loja]:
            memoria_cupons[cod] = agora_iso

    salvar_memoria(memoria_cupons)


if __name__ == "__main__":
    executar_varredura()

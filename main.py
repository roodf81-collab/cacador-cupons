import http.server
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
import requests

import cupons

PORT = int(os.environ.get("PORT", 8080))

# Buffer de logs recentes para diagnóstico remoto
LOGS_RECENTES = deque(maxlen=35)
MODELOS_GROQ_CACHE = []


def registrar_log(msg):
    """Registra uma mensagem no console e no buffer em memória para diagnóstico."""
    agora = datetime.now(timezone.utc).strftime("%H:%M:%S")
    linha = f"[{agora}] {msg}"
    print(linha)
    LOGS_RECENTES.append(linha)


def rank_modelo(m):
    m_lower = m.lower()
    if "gpt-oss-120b" in m_lower:
        return 0
    if "gpt-oss-20b" in m_lower:
        return 1
    if "llama-3.3-70b" in m_lower:
        return 2
    if "llama-3.1-8b" in m_lower:
        return 3
    if "qwen3.8-27b" in m_lower or "qwen" in m_lower:
        return 4
    if "llama" in m_lower:
        return 5
    if "gpt" in m_lower:
        return 6
    return 10


def obter_modelos_groq(groq_key):
    """Consulta dinamicamente os modelos ativos e permitidos para esta chave na Groq."""
    global MODELOS_GROQ_CACHE
    if MODELOS_GROQ_CACHE:
        return MODELOS_GROQ_CACHE

    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {groq_key.strip()}"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            itens = r.json().get("data", [])
            excluir = ["whisper", "guard", "orpheus", "arabic", "safeguard"]
            ids = [
                m["id"]
                for m in itens
                if not any(ex in m.get("id", "").lower() for ex in excluir)
            ]
            ids.sort(key=rank_modelo)
            registrar_log(f"Modelos Groq selecionados ({len(ids)}): {ids}")
            if ids:
                MODELOS_GROQ_CACHE = ids
                return ids
        else:
            registrar_log(f"Erro ao listar modelos Groq ({r.status_code}): {r.text[:150]}")
    except Exception as e:
        registrar_log(f"Exceção ao listar modelos Groq: {e}")

    # Fallback caso a listagem falhe
    return [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/varrer":
            threading.Thread(
                target=cupons.executar_varredura,
                kwargs={"ignorar_horario": True},
                daemon=True,
            ).start()
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Varredura iniciada em segundo plano!\n")
            return

        groq_key = (
            os.environ.get("GROQ_API_KEY")
            or os.environ.get("GROQ_KEY")
            or os.environ.get("GROQ")
            or os.environ.get("GROQ_TOKEN")
        )

        if self.path == "/test-ia":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            cfg = cupons.carregar_config()
            resp_teste = consultar_ia("Olá! Me fale rapidamente uma dica de cupom.", cfg)
            self.wfile.write(
                json.dumps(
                    {"resposta_ia": resp_teste, "logs": list(LOGS_RECENTES)},
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8")
            )
            return

        if self.path == "/modelos":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            if not groq_key:
                self.wfile.write(b'{"erro": "Sem chave Groq"}')
                return
            url = "https://api.groq.com/openai/v1/models"
            headers = {"Authorization": f"Bearer {groq_key.strip()}"}
            try:
                r = requests.get(url, headers=headers, timeout=10)
                self.wfile.write(r.text.encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"erro": str(e)}).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        tem_groq = bool(groq_key)
        tem_gemini = bool(os.environ.get("GEMINI_API_KEY"))
        nome_modelo = f"Groq ({MODELOS_GROQ_CACHE[0]})" if (tem_groq and MODELOS_GROQ_CACHE) else ("Groq" if tem_groq else ("Gemini" if tem_gemini else "Nenhum"))

        # Nomes das chaves presentes no ambiente (filtrando segredos)
        chaves_relevantes = [
            k for k in os.environ.keys() if any(x in k.upper() for x in ["GROQ", "GEMINI", "BOT", "PORT", "CHAT"])
        ]

        resposta = {
            "status": "online",
            "bot": "BOT_ROD",
            "modo": "24h Tempo Real",
            "ia_conectada": tem_groq or tem_gemini,
            "provedor_ia": nome_modelo,
            "variaveis_detectadas": chaves_relevantes,
            "bot_token_conectado": bool(cupons.BOT_TOKEN),
            "lojas_ativas": cupons.carregar_config().get("lojas_ativas", []),
            "ultimos_logs": list(LOGS_RECENTES),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.wfile.write(json.dumps(resposta, ensure_ascii=False, indent=2).encode("utf-8"))

    def log_message(self, format, *args):
        # Silencia logs de requisição para manter o console limpo
        pass


def rodar_servidor_http():
    server = http.server.HTTPServer(("0.0.0.0", PORT), HealthHandler)
    registrar_log(f"🌐 Servidor HTTP ativo na porta {PORT} (Healthcheck e Keep-Alive)")
    server.serve_forever()


def enviar_digitando(chat_id):
    """Envia o indicador 'digitando...' no Telegram enquanto a IA processa."""
    token = cupons.BOT_TOKEN
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass


def formatar_para_telegram(texto):
    """Converte Markdown comum (**negrito**) para tags HTML simples do Telegram."""
    if not texto:
        return ""
    # Converte negrito **texto** para <b>texto</b>
    texto = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", texto)
    # Converte itálico *texto* para <i>texto</i>
    texto = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"<i>\1</i>", texto)
    return texto


def tentar_executar_comando_rapido(texto, config, target_chat_id=None):
    """Execução instantânea (sub-segundo) para frases comuns de comando em linguagem natural."""
    texto_lower = texto.lower().strip()

    # 1. Ativação direta: "ativa amazon", "ativar a shopee", "adiciona mercado livre"
    m_ativar = re.search(
        r"^(?:por\s+favor\s+)?(?:ativ(?:a|e|ar)?|habilite?|habilitar|coloque?|colocar|adicion(?:a|e|ar)?)\s+(?:a|o)?\s*(shopee|ml|mercado\s*livre|amazon|aliexpress|ali)\b",
        texto_lower,
    )
    if m_ativar:
        loja = cupons.normalizar_nome_loja(m_ativar.group(1))
        if loja:
            if loja not in config.get("lojas_ativas", []):
                config.setdefault("lojas_ativas", []).append(loja)
                cupons.salvar_config(config)
                registrar_log(f"Comando rápido: Loja {loja} ativada")
                return f"✅ <b>Pronto!</b> A loja <b>{loja}</b> foi <b>ATIVADA</b> nas buscas em tempo real!"
            return f"ℹ️ A loja <b>{loja}</b> já está ativa nas buscas."

    # 2. Desativação direta: "desativa shopee", "desativar mercado livre", "tira a amazon"
    m_desativar = re.search(
        r"^(?:por\s+favor\s+)?(?:desativ(?:a|e|ar)?|desabilite?|desabilitar|remov(?:a|e|er)?|tir(?:a|e|ar)?)\s+(?:a|o)?\s*(shopee|ml|mercado\s*livre|amazon|aliexpress|ali)\b",
        texto_lower,
    )
    if m_desativar:
        loja = cupons.normalizar_nome_loja(m_desativar.group(1))
        if loja:
            if loja in config.get("lojas_ativas", []):
                config["lojas_ativas"].remove(loja)
                cupons.salvar_config(config)
                registrar_log(f"Comando rápido: Loja {loja} desativada")
                return f"🛑 <b>Feito!</b> A loja <b>{loja}</b> foi <b>DESATIVADA</b> das buscas."
            return f"ℹ️ A loja <b>{loja}</b> já não estava ativa."

    # 3. Busca imediata: "busca cupons agora", "faz uma varredura", "procurar cupons"
    if re.search(
        r"^(?:por\s+favor\s+)?(?:faz(?:er)?\s+(?:uma\s+)?)?(?:busc(?:a|ar)|varr(?:er|edura)|procur(?:a|ar))\s+(?:de\s+)?(?:cupons?|agora|promoc(?:oes|ões))",
        texto_lower,
    ):
        registrar_log("Comando rápido: Iniciando varredura manual (ignora horário noturno)")
        threading.Thread(
            target=cupons.executar_varredura,
            kwargs={"ignorar_horario": True, "chat_resposta": target_chat_id},
            daemon=True,
        ).start()
        return "🔍 <b>Iniciando varredura imediata de cupons agora mesmo!</b>\nBuscando em todos os sites e canais parceiros. Já te aviso aqui assim que terminar."

    # 4. Limpeza de memória: "limpar histórico", "resetar histórico"
    if re.search(
        r"^(?:por\s+favor\s+)?(?:limp(?:ar|e)|reset(?:ar|e))\s+(?:o\s+)?(?:hist[oó]rico|mem[oó]ria)",
        texto_lower,
    ):
        registrar_log("Comando rápido: Limpeza de memória")
        cupons.salvar_memoria({})
        return "🧹 <b>Histórico de cupons limpo com sucesso!</b>\nTodos os cupons válidos voltarão a ser enviados."

    return None


def executar_acoes_ia(texto, config, target_chat_id=None):
    """Detecta tags [ACAO: ...] retornadas pela IA, executa as modificações no sistema e limpa o texto."""
    padrao = re.compile(r"\[ACAO:\s*([^\]]+)\]", re.IGNORECASE)
    acoes = padrao.findall(texto)

    modificou_config = False

    for acao_str in acoes:
        acao_str = acao_str.strip()
        partes = acao_str.split(":", 1)
        comando = partes[0].strip().upper()
        param = partes[1].strip() if len(partes) > 1 else ""

        if comando == "ATIVAR_LOJA":
            loja = cupons.normalizar_nome_loja(param)
            if loja and loja not in config.get("lojas_ativas", []):
                config.setdefault("lojas_ativas", []).append(loja)
                modificou_config = True
                registrar_log(f"Ação da IA executada: Ativou loja {loja}")

        elif comando == "DESATIVAR_LOJA":
            loja = cupons.normalizar_nome_loja(param)
            if loja and loja in config.get("lojas_ativas", []):
                config["lojas_ativas"].remove(loja)
                modificou_config = True
                registrar_log(f"Ação da IA executada: Desativou loja {loja}")

        elif comando in ["BUSCAR_CUPONS", "VARREDURA", "BUSCAR"]:
            registrar_log("Ação da IA executada: Iniciando varredura manual (ignora horário noturno)")
            threading.Thread(
                target=cupons.executar_varredura,
                kwargs={"ignorar_horario": True, "chat_resposta": target_chat_id},
                daemon=True,
            ).start()

        elif comando in ["LIMPAR_HISTORICO", "LIMPAR"]:
            registrar_log("Ação da IA executada: Limpando histórico de cupons")
            cupons.salvar_memoria({})

        elif comando == "ADICIONAR_CANAL":
            canal_limpo = param.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
            if canal_limpo and canal_limpo not in config.get("canais_ativos", []):
                config.setdefault("canais_ativos", []).append(canal_limpo)
                modificou_config = True
                registrar_log(f"Ação da IA executada: Adicionou canal @{canal_limpo}")

        elif comando == "REMOVER_CANAL":
            canal_limpo = param.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
            if canal_limpo and canal_limpo in config.get("canais_ativos", []):
                config["canais_ativos"].remove(canal_limpo)
                modificou_config = True
                registrar_log(f"Ação da IA executada: Removeu canal @{canal_limpo}")

    if modificou_config:
        cupons.salvar_config(config)

    texto_limpo = padrao.sub("", texto).strip()
    return texto_limpo


def consultar_ia(pergunta, config):
    """Consulta a IA (Groq com Llama 3 ou Gemini) para responder dúvidas de cupons e compras."""
    groq_key = (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("GROQ_KEY")
        or os.environ.get("GROQ")
        or os.environ.get("GROQ_TOKEN")
    )
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if not groq_key and not gemini_key:
        return (
            "🤖 <b>Olá, Rodrigo!</b>\n\n"
            "Meu cérebro de Inteligência Artificial ainda não foi conectado.\n"
            "Basta adicionar a chave <code>GROQ_API_KEY</code> no painel do Render para começarmos a conversar!\n\n"
            "<i>Para ver os comandos de controle, digite /menu.</i>"
        )

    lojas_ativas = ", ".join(config.get("lojas_ativas", []))
    lojas_todas = list(cupons.INFO_LOJAS.keys())
    lojas_desativadas = ", ".join([l for l in lojas_todas if l not in config.get("lojas_ativas", [])])
    canais_ativos = ", ".join([f"@{c}" for c in config.get("canais_ativos", [])])
    canal_destino = config.get("canal_cupons_id", "Não configurado")

    prompt_sistema = (
        "Você é o assistente inteligente e administrador do BOT_ROD, o robô caçador de cupons do Rodrigo.\n"
        "Você tira dúvidas de compras e TAMBÉM tem autoridade total para alterar as configurações do robô quando o Rodrigo pedir.\n\n"
        "STATUS ATUAL DO SISTEMA:\n"
        f"• Lojas ativas: {lojas_ativas if lojas_ativas else 'Nenhuma'}\n"
        f"• Lojas desativadas: {lojas_desativadas if lojas_desativadas else 'Nenhuma'}\n"
        f"• Lojas suportadas: Mercado Livre, Shopee, AliExpress, Amazon\n"
        f"• Canais monitorados: {canais_ativos}\n"
        f"• Canal destino dos cupons: ID {canal_destino}\n\n"
        "AÇÕES QUE VOCÊ PODE EXECUTAR:\n"
        "Quando o Rodrigo pedir qualquer alteração ou ação no sistema, você DEVE incluir a tag correspondente na sua resposta para o sistema executar de verdade:\n"
        "• Para ativar loja: [ACAO: ATIVAR_LOJA: NomeDaLoja]\n"
        "• Para desativar loja: [ACAO: DESATIVAR_LOJA: NomeDaLoja]\n"
        "• Para buscar cupons agora: [ACAO: BUSCAR_CUPONS]\n"
        "• Para limpar histórico de cupons: [ACAO: LIMPAR_HISTORICO]\n"
        "• Para adicionar canal: [ACAO: ADICIONAR_CANAL: nome_do_canal]\n"
        "• Para remover canal: [ACAO: REMOVER_CANAL: nome_do_canal]\n\n"
        "Exemplos:\n"
        "- Se ele disser 'desativa a shopee': você responde '[ACAO: DESATIVAR_LOJA: Shopee] Pronto, Rodrigo! Desativei a Shopee das buscas de cupons.'\n"
        "- Se ele disser 'ativa a amazon e faz uma busca': você responde '[ACAO: ATIVAR_LOJA: Amazon] [ACAO: BUSCAR_CUPONS] Perfeito! Ativei a Amazon e acabei de disparar uma nova varredura de cupons.'\n"
        "- Se ele apenas perguntar algo sobre compras ou cupons: responda normalmente sem tags de ação.\n"
        "Use formatação simples para Telegram (como <b>negrito</b> ou <i>itálico</i>). Seja direto, amigável e prestativo."
    )

    # 1. Preferência principal: GROQ (Ultra rápido, gratuito e sem cartão)
    if groq_key:
        url_groq = "https://api.groq.com/openai/v1/chat/completions"
        headers_groq = {
            "Authorization": f"Bearer {groq_key.strip()}",
            "Content-Type": "application/json",
        }
        modelos = obter_modelos_groq(groq_key)

        for modelo in modelos:
            payload_groq = {
                "model": modelo,
                "messages": [
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": pergunta},
                ],
                "temperature": 0.7,
                "max_tokens": 800,
            }
            try:
                registrar_log(f"Chamando Groq ({modelo})...")
                resp = requests.post(url_groq, headers=headers_groq, json=payload_groq, timeout=20)
                if resp.status_code == 200:
                    dados = resp.json()
                    texto = dados["choices"][0]["message"]["content"].strip()
                    texto = formatar_para_telegram(texto)
                    registrar_log(f"Groq ({modelo}) respondeu com sucesso ({len(texto)} chars).")
                    return texto
                else:
                    registrar_log(f"Groq ({modelo}) retornou erro {resp.status_code}: {resp.text[:150]}")
            except Exception as e:
                registrar_log(f"Exceção ao chamar Groq ({modelo}): {e}")

    # 2. Alternativa: GEMINI
    if gemini_key:
        headers_gemini = {"Content-Type": "application/json"}
        payload_gemini = {
            "contents": [{"role": "user", "parts": [{"text": pergunta}]}],
            "systemInstruction": {"parts": [{"text": prompt_sistema}]},
        }
        for mod in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]:
            url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={gemini_key.strip()}"
            try:
                registrar_log(f"Chamando Gemini ({mod})...")
                resp = requests.post(url_gemini, headers=headers_gemini, json=payload_gemini, timeout=20)
                if resp.status_code == 200:
                    dados = resp.json()
                    cands = dados.get("candidates", [])
                    if cands:
                        partes = cands[0].get("content", {}).get("parts", [])
                        if partes:
                            texto_resposta = partes[0].get("text", "").strip()
                            texto_resposta = formatar_para_telegram(texto_resposta)
                            registrar_log(f"Gemini ({mod}) respondeu com sucesso.")
                            return texto_resposta
                else:
                    registrar_log(f"Gemini ({mod}) retornou erro {resp.status_code}: {resp.text[:150]}")
            except Exception as e:
                registrar_log(f"Exceção ao chamar Gemini ({mod}): {e}")

    return "⚠️ Ops, tive uma instabilidade temporária ao consultar a IA. Tente perguntar novamente em alguns instantes!"


def processar_update_ao_vivo(u, default_chat_id, config):
    """Processa eventos do Telegram em tempo real (sub-segundo)."""
    # 1. Detecção automática de Canal de Cupons
    mcm = u.get("my_chat_member")
    if mcm and mcm.get("chat", {}).get("type") == "channel":
        cid = mcm["chat"]["id"]
        title = mcm["chat"].get("title", "Canal de Cupons")
        if config.get("canal_cupons_id") != cid:
            config["canal_cupons_id"] = cid
            cupons.salvar_config(config)
            registrar_log(f"Canal vinculado automaticamente: {title} ({cid})")
            cupons.enviar_telegram(
                default_chat_id,
                f"🎉 <b>Canal vinculado com sucesso!</b>\n"
                f"A partir de agora, os cupons serão enviados para o canal <b>{title}</b>.\n\n"
                f"Sua conversa privada aqui com o BOT_ROD fica 100% limpa e exclusiva para você conversar!",
            )

    cp = u.get("channel_post")
    if cp and cp.get("chat", {}).get("type") == "channel":
        cid = cp["chat"]["id"]
        title = cp["chat"].get("title", "Canal de Cupons")
        if config.get("canal_cupons_id") != cid:
            config["canal_cupons_id"] = cid
            cupons.salvar_config(config)
            registrar_log(f"Canal vinculado automaticamente via post: {title} ({cid})")
            cupons.enviar_telegram(
                default_chat_id,
                f"🎉 <b>Canal vinculado com sucesso!</b>\n"
                f"A partir de agora, os cupons serão enviados para o canal <b>{title}</b>.\n\n"
                f"Sua conversa privada aqui com o BOT_ROD fica 100% limpa e exclusiva para você conversar!",
            )

    msg = u.get("message") or u.get("edited_message")
    if not msg:
        return

    remetente_id = msg.get("chat", {}).get("id")
    tipo_chat = msg.get("chat", {}).get("type", "")

    # Se for mensagem privada, respondemos sempre de volta para o usuário no privado
    if tipo_chat == "private":
        target_chat_id = remetente_id
    elif str(remetente_id) == str(default_chat_id):
        target_chat_id = default_chat_id
    else:
        # Ignora mensagens vindas de outros canais ou grupos abertos
        return

    if "voice" in msg or "audio" in msg:
        texto_ajuda = (
            "🎙️ <i>Recebi sua mensagem de áudio em tempo real!</i>\n\n"
            "Para gerenciar o bot, use comandos em texto como:\n"
            "• <code>/status</code> - Vê lojas e canais ativos\n"
            "• <code>/ativar aliexpress</code> (ou ml, shopee, amazon)\n"
            "• <code>/desativar shopee</code>\n"
            "• <code>/menu</code> - Ver todas as opções\n\n"
            "Ou envie uma mensagem de texto com qualquer dúvida sobre cupons!"
        )
        cupons.enviar_telegram(target_chat_id, texto_ajuda)
        return

    texto = msg.get("text", "").strip()
    if not texto:
        return

    registrar_log(f"Mensagem recebida de {remetente_id} ({tipo_chat}): {texto[:50]}")

    partes = texto.split(maxsplit=1)
    comando = partes[0].lower()
    parametro = partes[1].strip() if len(partes) > 1 else ""

    cmd_puro = comando[1:] if comando.startswith("/") else comando

    if cmd_puro in ["start", "menu", "ajuda", "help"]:
        menu = (
            "🤖 <b>PAINEL DE CONTROLE EM TEMPO REAL (BOT_ROD)</b>\n"
            "────────────────────────────────\n"
            "Estou online 24h! Envie um comando ou converse comigo:\n\n"
            "💬 <b>CONVERSAR COM A IA:</b>\n"
            "• Basta me enviar qualquer pergunta ou mensagem diretamente!\n\n"
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
            "• <code>/buscar</code> - Força uma varredura imediatamente\n"
            "• <code>/limpar</code> - Limpa histórico para reenviar cupons"
        )
        cupons.enviar_telegram(target_chat_id, menu)

    elif cmd_puro in ["status", "satus", "staus", "config"]:
        lojas_msg = []
        for loja in cupons.INFO_LOJAS.keys():
            emoji = cupons.INFO_LOJAS[loja]["emoji"]
            if loja in config["lojas_ativas"]:
                lojas_msg.append(f"• {emoji} <b>{loja}:</b> ✅ ATIVO")
            else:
                lojas_msg.append(f"• {emoji} <b>{loja}:</b> ❌ DESATIVADO")

        canais_msg = [f"• @{c}" for c in config["canais_ativos"]]
        canal_destino = config.get("canal_cupons_id")
        destino_str = f"Canal ID {canal_destino} ✅" if canal_destino else "Conversa Privada"
        status_txt = (
            "⚙️ <b>CONFIGURAÇÃO ATUAL DO BOT (ONLINE 24H)</b>\n"
            "────────────────────────────────\n"
            f"📢 <b>Destino dos Cupons:</b> {destino_str}\n\n"
            "🏬 <b>Lojas Monitoradas:</b>\n"
            + "\n".join(lojas_msg)
            + "\n\n"
            + f"📡 <b>Fontes Monitoradas ({len(config['canais_ativos'])}):</b>\n"
            + "\n".join(canais_msg)
            + "\n────────────────────────────────\n"
            "<i>Digite /menu para ver os comandos ou envie uma pergunta para a IA!</i>"
        )
        cupons.enviar_telegram(target_chat_id, status_txt)

    elif cmd_puro in ["ativar", "enable"]:
        if not parametro:
            cupons.enviar_telegram(
                target_chat_id,
                "❓ Qual loja você quer ativar?\nExemplo: <code>/ativar aliexpress</code> ou <code>/ativar shopee</code>",
            )
        else:
            loja = cupons.normalizar_nome_loja(parametro)
            if loja:
                if loja not in config["lojas_ativas"]:
                    config["lojas_ativas"].append(loja)
                    cupons.salvar_config(config)
                    cupons.enviar_telegram(
                        target_chat_id,
                        f"✅ Loja <b>{loja}</b> foi <b>ATIVADA</b> em tempo real!\nO bot já começará a buscar cupons dela.",
                    )
                else:
                    cupons.enviar_telegram(target_chat_id, f"ℹ️ A loja <b>{loja}</b> já está ativa nas buscas.")
            else:
                cupons.enviar_telegram(
                    target_chat_id,
                    "❓ Loja não reconhecida.\nLojas disponíveis: <code>ml</code>, <code>shopee</code>, <code>aliexpress</code>, <code>amazon</code>.",
                )

    elif cmd_puro in ["desativar", "disable"]:
        if not parametro:
            cupons.enviar_telegram(
                target_chat_id,
                "❓ Qual loja você quer desativar?\nExemplo: <code>/desativar shopee</code>",
            )
        else:
            loja = cupons.normalizar_nome_loja(parametro)
            if loja:
                if loja in config["lojas_ativas"]:
                    config["lojas_ativas"].remove(loja)
                    cupons.salvar_config(config)
                    cupons.enviar_telegram(
                        target_chat_id,
                        f"🛑 Loja <b>{loja}</b> foi <b>DESATIVADA</b> em tempo real!\nO bot não buscará mais cupons dela.",
                    )
                else:
                    cupons.enviar_telegram(target_chat_id, f"ℹ️ A loja <b>{loja}</b> já não estava ativa.")
            else:
                cupons.enviar_telegram(
                    target_chat_id,
                    "❓ Loja não reconhecida.\nLojas disponíveis: <code>ml</code>, <code>shopee</code>, <code>aliexpress</code>, <code>amazon</code>.",
                )

    elif cmd_puro in ["addcanal", "adicionarcanal", "add_canal"]:
        if not parametro:
            cupons.enviar_telegram(
                target_chat_id,
                "❓ Qual canal deseja adicionar?\nExemplo: <code>/addcanal CuponsTecnan</code>",
            )
        else:
            canal_limpo = parametro.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
            if canal_limpo:
                if canal_limpo not in config["canais_ativos"]:
                    config["canais_ativos"].append(canal_limpo)
                    cupons.salvar_config(config)
                    cupons.enviar_telegram(
                        target_chat_id,
                        f"✅ Canal <b>@{canal_limpo}</b> adicionado à lista de monitoramento!",
                    )
                else:
                    cupons.enviar_telegram(target_chat_id, f"ℹ️ O canal <b>@{canal_limpo}</b> já está na lista.")

    elif cmd_puro in ["rmcanal", "removercanal", "delcanal"]:
        if not parametro:
            cupons.enviar_telegram(
                target_chat_id,
                "❓ Qual canal deseja remover?\nExemplo: <code>/rmcanal radarcupons</code>",
            )
        else:
            canal_limpo = parametro.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
            if canal_limpo in config["canais_ativos"]:
                config["canais_ativos"].remove(canal_limpo)
                cupons.salvar_config(config)
                cupons.enviar_telegram(
                    target_chat_id,
                    f"🗑️ Canal <b>@{canal_limpo}</b> foi removido do monitoramento.",
                )
            else:
                cupons.enviar_telegram(
                    target_chat_id,
                    f"⚠️ Canal <b>@{canal_limpo}</b> não foi encontrado na lista de canais ativos.",
                )

    elif cmd_puro in ["limpar", "reset", "clear"]:
        cupons.salvar_memoria({})
        cupons.enviar_telegram(
            target_chat_id,
            "🧹 <b>Histórico de cupons limpo!</b>\nTodos os cupons válidos disponíveis serão reenviados no canal.",
        )

    elif cmd_puro in ["buscar", "varrer"]:
        cupons.enviar_telegram(target_chat_id, "🔍 <b>Iniciando varredura imediata de cupons...</b>\nBuscando em todos os parceiros. Já te aviso aqui assim que terminar.")
        threading.Thread(
            target=cupons.executar_varredura,
            kwargs={"ignorar_horario": True, "chat_resposta": target_chat_id},
            daemon=True,
        ).start()

    else:
        # 1. Tenta executar comandos diretos em linguagem natural (instantâneo)
        resp_rapida = tentar_executar_comando_rapido(texto, config, target_chat_id)
        if resp_rapida:
            cupons.enviar_telegram(target_chat_id, resp_rapida)
            registrar_log(f"Comando rápido em linguagem natural executado para {target_chat_id}")
            return

        # 2. Se for uma conversa ou pedido elaborado, a IA processa e executa ações
        enviar_digitando(target_chat_id)
        resposta_ia = consultar_ia(texto, config)
        resposta_final = executar_acoes_ia(resposta_ia, config, target_chat_id)
        cupons.enviar_telegram(target_chat_id, resposta_final)
        registrar_log(f"Resposta da IA enviada para {target_chat_id}.")


def loop_escuta_telegram():
    """Escuta mensagens do Telegram continuamente com Long Polling (tempo real)."""
    chat_id = cupons.obter_chat_id()
    config = cupons.carregar_config()
    registrar_log(f"👂 Escutando Telegram em tempo real (chat padrão: {chat_id})...")

    offset = config.get("ultimo_update_id", 0) + 1

    while True:
        token = cupons.BOT_TOKEN
        if not token:
            print("⚠️ BOT_TOKEN não configurado no ambiente. Aguardando 10s...")
            time.sleep(10)
            continue

        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 20}, timeout=30)
            if not resp.ok:
                registrar_log(f"Telegram getUpdates status {resp.status_code}: {resp.text[:80]}")
                time.sleep(2)
                continue

            dados = resp.json()
            updates = dados.get("result", [])
            for u in updates:
                up_id = u.get("update_id", 0)
                offset = up_id + 1
                config["ultimo_update_id"] = up_id
                processar_update_ao_vivo(u, chat_id, config)

            if updates:
                cupons.salvar_config(config)

        except Exception as e:
            registrar_log(f"Exceção no loop do Telegram: {e}")
            time.sleep(3)


def loop_varredura_periodica():
    """Executa a busca de cupons a cada 15 minutos (900 segundos)."""
    # Aguarda 15 segundos na inicialização para estabilizar
    time.sleep(15)
    while True:
        try:
            agora_str = datetime.now().strftime("%H:%M:%S")
            registrar_log(f"⏰ [{agora_str}] Iniciando ciclo automático de varredura...")
            cupons.executar_varredura()
        except Exception as e:
            registrar_log(f"Erro no ciclo de varredura: {e}")
        # 15 minutos = 900 segundos
        time.sleep(900)


def main():
    registrar_log("🚀 Iniciando Bot Caçador de Cupons (Modo 24h Tempo Real)...")
    cupons.carregar_config()

    # 1. Thread do Servidor HTTP (Healthcheck Render / Keep-Alive)
    t_http = threading.Thread(target=rodar_servidor_http, daemon=True)
    t_http.start()

    # 2. Thread da Varredura Periódica (a cada 15 min)
    t_scraper = threading.Thread(target=loop_varredura_periodica, daemon=True)
    t_scraper.start()

    # 3. Thread Principal: Escuta em Tempo Real do Telegram (sub-segundo)
    loop_escuta_telegram()


if __name__ == "__main__":
    main()

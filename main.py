import http.server
import json
import os
import threading
import time
from datetime import datetime, timezone
import requests

import cupons

PORT = int(os.environ.get("PORT", 8080))


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/varrer":
            threading.Thread(target=cupons.executar_varredura, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Varredura iniciada em segundo plano!\n")
            return

        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        resposta = {
            "status": "online",
            "bot": "BOT_ROD",
            "modo": "24h Tempo Real",
            "gemini_conectado": bool(os.environ.get("GEMINI_API_KEY")),
            "bot_token_conectado": bool(cupons.BOT_TOKEN),
            "lojas_ativas": cupons.carregar_config().get("lojas_ativas", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.wfile.write(json.dumps(resposta, ensure_ascii=False, indent=2).encode("utf-8"))

    def log_message(self, format, *args):
        # Silencia logs de requisição para manter o console limpo
        pass


def rodar_servidor_http():
    server = http.server.HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"🌐 Servidor HTTP ativo na porta {PORT} (Healthcheck e Keep-Alive)")
    server.serve_forever()


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


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


def consultar_gemini(pergunta, config):
    """Consulta a IA do Gemini para responder dúvidas de cupons e compras."""
    api_key = os.environ.get("GEMINI_API_KEY") or GEMINI_API_KEY
    if not api_key:
        return (
            "🤖 <b>Olá, Rodrigo!</b>\n\n"
            "Meu cérebro de Inteligência Artificial ainda não foi conectado. "
            "Para conversar comigo sobre compras, lojas e cupons, basta adicionar a chave "
            "<code>GEMINI_API_KEY</code> no painel do Render!\n\n"
            "<i>Para ver os comandos de controle disponíveis, digite /menu.</i>"
        )

    lojas_ativas = ", ".join(config.get("lojas_ativas", []))
    headers = {"Content-Type": "application/json"}

    prompt_sistema = (
        "Você é o assistente inteligente do BOT_ROD, especialista em cupons de desconto, "
        "compras inteligentes e e-commerce brasileiro (Mercado Livre, Shopee, AliExpress, Amazon). "
        "Você conversa com o Rodrigo. "
        f"Atualmente, as lojas ativas no bot dele são: {lojas_ativas}. "
        "Responda às perguntas dele de forma direta, prestativa, amigável e realista sobre preços, "
        "regras de cupons, melhores épocas para comprar e dicas de economia. "
        "Use texto limpo sem formatações complexas."
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": pergunta}]}],
        "systemInstruction": {"parts": [{"text": prompt_sistema}]},
    }

    # Tenta modelos disponíveis (gemini-1.5-flash ou gemini-2.0-flash ou gemini-1.5-pro)
    modelos = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
    for mod in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                dados = resp.json()
                cands = dados.get("candidates", [])
                if cands:
                    partes = cands[0].get("content", {}).get("parts", [])
                    if partes:
                        texto_resposta = partes[0].get("text", "").strip()
                        texto_resposta = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", texto_resposta)
                        return texto_resposta
            else:
                print(f"Gemini {mod} retornou status {resp.status_code}: {resp.text[:150]}")
        except Exception as e:
            print(f"Erro ao chamar Gemini {mod}: {e}")

    return "⚠️ Ops, tive uma instabilidade temporária ao consultar o cérebro da IA. Tente perguntar novamente!"


def processar_update_ao_vivo(u, chat_id, config):
    """Processa eventos do Telegram em tempo real (sub-segundo)."""
    # 1. Detecção automática de Canal de Cupons
    mcm = u.get("my_chat_member")
    if mcm and mcm.get("chat", {}).get("type") == "channel":
        cid = mcm["chat"]["id"]
        title = mcm["chat"].get("title", "Canal de Cupons")
        if config.get("canal_cupons_id") != cid:
            config["canal_cupons_id"] = cid
            cupons.salvar_config(config)
            cupons.enviar_telegram(
                chat_id,
                f"🎉 <b>Canal vinculado com sucesso!</b>\n"
                f"A partir de agora, os cupons serão enviados para o canal <b>{title}</b>.\n\n"
                f"Sua conversa privada aqui com o BOT_ROD fica 100% limpa e exclusiva para configurações!",
            )

    cp = u.get("channel_post")
    if cp and cp.get("chat", {}).get("type") == "channel":
        cid = cp["chat"]["id"]
        title = cp["chat"].get("title", "Canal de Cupons")
        if config.get("canal_cupons_id") != cid:
            config["canal_cupons_id"] = cid
            cupons.salvar_config(config)
            cupons.enviar_telegram(
                chat_id,
                f"🎉 <b>Canal vinculado com sucesso!</b>\n"
                f"A partir de agora, os cupons serão enviados para o canal <b>{title}</b>.\n\n"
                f"Sua conversa privada aqui com o BOT_ROD fica 100% limpa e exclusiva para configurações!",
            )

    msg = u.get("message") or u.get("edited_message")
    if not msg:
        return

    remetente_id = str(msg.get("chat", {}).get("id", ""))
    if remetente_id != str(chat_id):
        return

    if "voice" in msg or "audio" in msg:
        texto_ajuda = (
            "🎙️ <i>Recebi sua mensagem de áudio em tempo real!</i>\n\n"
            "Para gerenciar o bot, use os comandos em texto:\n"
            "• <code>/status</code> - Vê lojas e canais ativos\n"
            "• <code>/ativar aliexpress</code> (ou ml, shopee, amazon)\n"
            "• <code>/desativar shopee</code>\n"
            "• <code>/addcanal nome_do_canal</code>\n"
            "• <code>/menu</code> - Ver todas as opções"
        )
        cupons.enviar_telegram(chat_id, texto_ajuda)
        return

    texto = msg.get("text", "").strip()
    if not texto:
        return

    partes = texto.split(maxsplit=1)
    comando = partes[0].lower()
    parametro = partes[1].strip() if len(partes) > 1 else ""

    cmd_puro = comando[1:] if comando.startswith("/") else comando

    if cmd_puro in ["start", "menu", "ajuda", "help"]:
        menu = (
            "🤖 <b>PAINEL DE CONTROLE EM TEMPO REAL (BOT_ROD)</b>\n"
            "────────────────────────────────\n"
            "Estou online 24h! Envie um comando para alterar agora mesmo:\n\n"
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
        cupons.enviar_telegram(chat_id, menu)

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
            "<i>Digite /menu para ver os comandos</i>"
        )
        cupons.enviar_telegram(chat_id, status_txt)

    elif cmd_puro in ["ativar", "enable"]:
        if not parametro:
            cupons.enviar_telegram(
                chat_id,
                "❓ Qual loja você quer ativar?\nExemplo: <code>/ativar aliexpress</code> ou <code>/ativar shopee</code>",
            )
        else:
            loja = cupons.normalizar_nome_loja(parametro)
            if loja:
                if loja not in config["lojas_ativas"]:
                    config["lojas_ativas"].append(loja)
                    cupons.salvar_config(config)
                    cupons.enviar_telegram(
                        chat_id,
                        f"✅ Loja <b>{loja}</b> foi <b>ATIVADA</b> em tempo real!\nO bot já começará a buscar cupons dela.",
                    )
                else:
                    cupons.enviar_telegram(chat_id, f"ℹ️ A loja <b>{loja}</b> já está ativa nas buscas.")
            else:
                cupons.enviar_telegram(
                    chat_id,
                    "❓ Loja não reconhecida.\nLojas disponíveis: <code>ml</code>, <code>shopee</code>, <code>aliexpress</code>, <code>amazon</code>.",
                )

    elif cmd_puro in ["desativar", "disable"]:
        if not parametro:
            cupons.enviar_telegram(
                chat_id,
                "❓ Qual loja você quer desativar?\nExemplo: <code>/desativar shopee</code>",
            )
        else:
            loja = cupons.normalizar_nome_loja(parametro)
            if loja:
                if loja in config["lojas_ativas"]:
                    config["lojas_ativas"].remove(loja)
                    cupons.salvar_config(config)
                    cupons.enviar_telegram(
                        chat_id,
                        f"🛑 Loja <b>{loja}</b> foi <b>DESATIVADA</b> em tempo real!\nO bot não buscará mais cupons dela.",
                    )
                else:
                    cupons.enviar_telegram(chat_id, f"ℹ️ A loja <b>{loja}</b> já não estava ativa.")
            else:
                cupons.enviar_telegram(
                    chat_id,
                    "❓ Loja não reconhecida.\nLojas disponíveis: <code>ml</code>, <code>shopee</code>, <code>aliexpress</code>, <code>amazon</code>.",
                )

    elif cmd_puro in ["addcanal", "adicionarcanal", "add_canal"]:
        if not parametro:
            cupons.enviar_telegram(
                chat_id,
                "❓ Qual canal deseja adicionar?\nExemplo: <code>/addcanal CuponsTecnan</code>",
            )
        else:
            canal_limpo = parametro.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
            if canal_limpo:
                if canal_limpo not in config["canais_ativos"]:
                    config["canais_ativos"].append(canal_limpo)
                    cupons.salvar_config(config)
                    cupons.enviar_telegram(
                        chat_id,
                        f"✅ Canal <b>@{canal_limpo}</b> adicionado à lista de monitoramento!",
                    )
                else:
                    cupons.enviar_telegram(chat_id, f"ℹ️ O canal <b>@{canal_limpo}</b> já está na lista.")

    elif cmd_puro in ["rmcanal", "removercanal", "delcanal"]:
        if not parametro:
            cupons.enviar_telegram(
                chat_id,
                "❓ Qual canal deseja remover?\nExemplo: <code>/rmcanal radarcupons</code>",
            )
        else:
            canal_limpo = parametro.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip("/ ")
            if canal_limpo in config["canais_ativos"]:
                config["canais_ativos"].remove(canal_limpo)
                cupons.salvar_config(config)
                cupons.enviar_telegram(
                    chat_id,
                    f"🗑️ Canal <b>@{canal_limpo}</b> foi removido do monitoramento.",
                )
            else:
                cupons.enviar_telegram(
                    chat_id,
                    f"⚠️ Canal <b>@{canal_limpo}</b> não foi encontrado na lista de canais ativos.",
                )

    elif cmd_puro in ["limpar", "reset", "clear"]:
        cupons.salvar_memoria({})
        cupons.enviar_telegram(
            chat_id,
            "🧹 <b>Histórico de cupons limpo!</b>\nTodos os cupons válidos disponíveis serão reenviados no canal.",
        )

    elif cmd_puro in ["buscar", "varrer"]:
        cupons.enviar_telegram(chat_id, "🔍 <b>Iniciando varredura imediata de cupons...</b>")
        threading.Thread(target=cupons.executar_varredura, daemon=True).start()

    else:
        # Se não for comando com barra, o Gemini responde como assistente pessoal com IA!
        enviar_digitando(chat_id)
        resposta_ia = consultar_gemini(texto, config)
        cupons.enviar_telegram(chat_id, resposta_ia)


def loop_escuta_telegram():
    """Escuta mensagens do Telegram continuamente com Long Polling (tempo real)."""
    chat_id = cupons.obter_chat_id()
    config = cupons.carregar_config()
    print(f"👂 Escutando Telegram em tempo real para chat_id {chat_id}...")

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
            # Em caso de instabilidade de rede temporária, espera 3s e continua
            time.sleep(3)


def loop_varredura_periodica():
    """Executa a busca de cupons a cada 15 minutos (900 segundos)."""
    # Aguarda 15 segundos na inicialização para estabilizar
    time.sleep(15)
    while True:
        try:
            print(f"⏰ [{datetime.now().strftime('%H:%M:%S')}] Iniciando ciclo automático de varredura...")
            cupons.executar_varredura()
        except Exception as e:
            print(f"Erro no ciclo de varredura: {e}")
        # 15 minutos = 900 segundos
        time.sleep(900)


def main():
    print("🚀 Iniciando Bot Caçador de Cupons (Modo 24h Tempo Real)...")
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

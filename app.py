import json
import os
import unicodedata
import smtplib
from email.mime.text import MIMEText
import re

from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

# 🔥 NORMALIZAÇÃO (remove acento + padroniza)
def normalize(text):
    return unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("ASCII").lower()

# 🔑 KEYWORDS
_raw_keywords = os.environ.get("SLACK_ALERT_KEYWORDS", "urgente,erro").strip()
KEYWORDS = [normalize(k.strip()) for k in _raw_keywords.split(",") if k.strip()]

# SLACK
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "").strip()
USER_ID = os.environ.get("SLACK_USER_ID", "").strip()
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "").strip()

# EMAIL
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

_signature_verifier = SignatureVerifier(SLACK_SIGNING_SECRET) if SLACK_SIGNING_SECRET else None
client = WebClient(token=SLACK_TOKEN)

def get_user_real_name(user_id):
    """Pega o nome real do usuário pelo ID"""
    try:
        response = client.users_info(user=user_id)
        if response.get('ok'):
            real_name = response['user'].get('real_name')
            if real_name:
                return real_name
            return response['user'].get('name')
    except Exception as e:
        print(f"Erro ao pegar nome do usuário: {e}")
    return user_id

# 📧 ENVIO DE EMAIL
def send_email_alert(message: str):
    print(f"🔍 DEBUG - EMAIL_ENABLED: {EMAIL_ENABLED}")
    print(f"🔍 DEBUG - EMAIL_FROM: {EMAIL_FROM}")
    print(f"🔍 DEBUG - EMAIL_TO: {EMAIL_TO}")
    print(f"🔍 DEBUG - EMAIL_APP_PASSWORD: {'OK' if EMAIL_APP_PASSWORD else 'MISSING'}")
    
    if not EMAIL_ENABLED:
        print("⚠️ Email desativado")
        return

    if not EMAIL_FROM or not EMAIL_TO or not EMAIL_APP_PASSWORD:
        print("❌ Configurações de email incompletas")
        return

    try:
        msg = MIMEText(f"🚨 ALERTA:\n\n{message}")
        msg["Subject"] = "🚨 Alerta Slack"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            server.send_message(msg)

        print("✅ Email enviado com sucesso!")

    except Exception as e:
        print(f"❌ Erro ao enviar email: {e}")

# 🚨 ENVIO DE ALERTA COM QUOTE E LINK
def send_slack_alerts(original_message: str, channel_id: str = None, ts: str = None, user_id: str = None) -> None:
    print("🚀 TENTANDO ENVIAR ALERTA COM QUOTE...")
    
    # Pega o nome do usuário que enviou a mensagem original
    user_name = get_user_real_name(user_id) if user_id else "Alguém"
    
    # Constrói o link para a mensagem original (se tiver channel_id e ts)
    message_link = ""
    if channel_id and ts:
        # Remove o ponto do timestamp se existir
        ts_clean = ts.replace('.', '') if '.' in ts else ts
        message_link = f"\n\n🔗 <https://slack.com/archives/{channel_id}/p{ts_clean}|Clique aqui para ver a mensagem original>"
    
    # Formata a mensagem com quote e informações
    formatted_alert = f"""🚨 *ALERTA DETECTADO!*

*👤 Quem:* {user_name}
*📝 Mensagem original:* 
> {original_message}
*🔑 Palavra-chave detectada:* {', '.join(KEYWORDS)}{message_link}

💡 *Dica:* Clique no link acima para ir direto ao local da mensagem!"""
    
    print(f"📝 Alerta formatado: {formatted_alert}")
    
    # ✅ ENVIA APENAS PARA SEU DM
    if USER_ID:
        try:
            # Envia como uma mensagem normal (não como reply)
            response = client.chat_postMessage(
                channel=USER_ID,
                text=formatted_alert,
                mrkdwn=True  # Permite formatação markdown
            )
            print(f"✅ Alerta com quote enviado para seu DM!")
            
            # Se tiver o timestamp da mensagem original, adiciona uma reação de alerta lá (opcional)
            if channel_id and ts:
                try:
                    client.reactions_add(
                        channel=channel_id,
                        name="warning",
                        timestamp=ts
                    )
                    print(f"✅ Reação de alerta adicionada à mensagem original!")
                except Exception as e:
                    print(f"⚠️ Não foi possível adicionar reação: {e}")
                    
        except SlackApiError as e:
            print(f"❌ ERRO DM: {e.response.get('error')}")
    else:
        print("⚠️ USER_ID não configurado")
    
    send_email_alert(original_message)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    raw_body = request.get_data()

    if _signature_verifier:
        if not _signature_verifier.is_valid_request(raw_body, request.headers):
            return "", 403

    data = json.loads(raw_body.decode("utf-8"))

    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})

    # Ignora mensagens de bots
    if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed"):
        return "", 200

    text_original = event.get("text", "")
    text = normalize(text_original)
    
    # Pega informações da mensagem original
    channel_id = event.get("channel")  # Canal onde a mensagem foi enviada
    ts = event.get("ts")  # Timestamp da mensagem
    user_id = event.get("user")  # ID do usuário que enviou
    
    print(f"📝 Mensagem: '{text_original}'")
    print(f"📍 Canal: {channel_id}")
    print(f"🕒 Timestamp: {ts}")
    print(f"👤 Usuário: {user_id}")
    print(f"🔑 Keywords: {KEYWORDS}")

    # Verifica se tem keyword
    keyword_detected = False
    detected_words = []
    for word in KEYWORDS:
        if word in text:
            print(f"✅ KEYWORD: '{word}'")
            keyword_detected = True
            detected_words.append(word)
            break
    
    if keyword_detected:
        print("🔥 Enviando alerta com quote...")
        send_slack_alerts(text_original, channel_id, ts, user_id)
    else:
        print("⚠️ Nenhuma keyword")

    return "", 200

# 🏠 ROTA RAIZ
@app.route("/", methods=["GET"])
def home():
    return "Bot Slack está rodando! 🚀", 200

# 🏥 HEALTH CHECK
@app.route("/healthz", methods=["GET"])
def health_check():
    return "OK", 200

# 🧪 ROTA DE TESTE DE EMAIL
@app.route("/test-email", methods=["GET"])
def test_email():
    try:
        EMAIL_FROM = os.getenv("EMAIL_FROM")
        EMAIL_TO = os.getenv("EMAIL_TO")
        EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
        
        if not EMAIL_FROM or not EMAIL_TO or not EMAIL_APP_PASSWORD:
            return f"❌ Configurações faltando: FROM={bool(EMAIL_FROM)}, TO={bool(EMAIL_TO)}, PASSWORD={bool(EMAIL_APP_PASSWORD)}", 500
        
        msg = MIMEText("🧪 Teste do bot Slack - email funcionando!")
        msg["Subject"] = "🧪 Teste Bot Slack"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            server.send_message(msg)
        
        return "✅ Email enviado com sucesso!", 200
    except Exception as e:
        return f"❌ Erro: {str(e)}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    app.run(port=port)
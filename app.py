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
ALERT_CHANNEL = os.environ.get("SLACK_ALERT_CHANNEL", "").strip()
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "").strip()

# EMAIL
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

_signature_verifier = SignatureVerifier(SLACK_SIGNING_SECRET) if SLACK_SIGNING_SECRET else None
client = WebClient(token=SLACK_TOKEN)

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

# 🚨 ENVIO DE ALERTA (APENAS DENTRO DO BOT)
def send_slack_alerts(message: str) -> None:
    text = f"🚨 ALERTA:\n{message}"
    print("🚀 TENTANDO ENVIAR ALERTA:", text)

    # ✅ APENAS ENVIA PARA O PRÓPRIO BOT (DM)
    if USER_ID:
        try:
            response = client.chat_postMessage(channel=USER_ID, text=text)
            print(f"✅ Alerta enviado para o bot!")
        except SlackApiError as e:
            print(f"❌ ERRO: {e.response.get('error')}")
    else:
        print("⚠️ USER_ID não configurado")

    # ❌ NÃO ENVIA PARA NENHUM CANAL
    # O ALERT_CHANNEL É IGNORADO COMPLETAMENTE

    send_email_alert(message)

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

    if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed"):
        return "", 200

    text_original = event.get("text", "")
    text = normalize(text_original)
    
    print(f"📝 Mensagem: '{text_original}'")
    print(f"🔑 Keywords: {KEYWORDS}")

    keyword_detected = False
    for word in KEYWORDS:
        if word in text:
            print(f"✅ KEYWORD: '{word}'")
            keyword_detected = True
            break
    
    if keyword_detected:
        print("🔥 Enviando alerta...")
        send_slack_alerts(text_original)
    else:
        print("⚠️ Nenhuma keyword")

    return "", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    app.run(port=port)
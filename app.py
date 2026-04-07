import json
import os
import unicodedata
import smtplib
from email.mime.text import MIMEText

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

# 🔥 NORMALIZAÇÃO (remove acento)
def normalize(text):
    return unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("ASCII")

_raw_keywords = os.environ.get("SLACK_ALERT_KEYWORDS", "urgente,erro").strip()
KEYWORDS = [normalize(k.strip().lower()) for k in _raw_keywords.split(",") if k.strip()]

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
    if not EMAIL_ENABLED:
        print("⚠️ Email desativado")
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

        print("📧 Email enviado com sucesso")

    except Exception as e:
        print("❌ Erro ao enviar email:", e)

# 🚨 ENVIO DE ALERTA (Slack + Email)
def send_slack_alerts(message: str) -> None:
    text = f"🚨 ALERTA:\n{message}"
    print("🚀 TENTANDO ENVIAR ALERTA:", text)

    if USER_ID:
        try:
            client.chat_postMessage(channel=USER_ID, text=text)
            print("✅ ALERTA ENVIADO VIA DM")
        except SlackApiError as e:
            print("❌ ERRO DM:", e.response)

    if ALERT_CHANNEL:
        try:
            client.chat_postMessage(channel=ALERT_CHANNEL, text=text)
            print("✅ ALERTA ENVIADO NO CANAL")
        except SlackApiError as e:
            print("❌ ERRO CANAL:", e.response)

    # 👉 ENVIA EMAIL TAMBÉM
    send_email_alert(message)


# 🏠 ROTA RAIZ
@app.route("/", methods=["GET"])
def home():
    return "Bot Slack está rodando! 🚀", 200

# 🏥 HEALTH CHECK para o Render
@app.route("/healthz", methods=["GET"])
def health_check():
    return "OK", 200


@app.route("/slack/events", methods=["POST"])
def slack_events():
    raw_body = request.get_data()

    # 🔐 Verificação de assinatura
    if _signature_verifier:
        if not _signature_verifier.is_valid_request(raw_body, dict(request.headers)):
            print("❌ Assinatura inválida")
            return "", 403

    data = json.loads(raw_body.decode("utf-8"))

    # 🔥 CHALLENGE (Slack setup)
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})

    # ❌ ignora bots
    if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed"):
        return "", 200

    channel_type = event.get("channel_type")
    channel = event.get("channel")
    text_original = event.get("text", "")
    text = normalize(text_original.lower())

    # 🔍 DEBUG
    print("\n======================")
    print("📩 EVENTO:", event)
    print("📝 TEXTO:", text_original)
    print("🧠 NORMALIZADO:", text)
    print("🎯 KEYWORDS:", KEYWORDS)
    print("======================\n")

    # 🟢 RESPOSTA EM DM
    if channel_type == "im":
        try:
            client.chat_postMessage(
                channel=channel,
                text=f"🤖 Recebi sua mensagem: {text_original}"
            )
            print("✅ Respondeu DM")
        except SlackApiError as e:
            print("❌ ERRO DM:", e.response)

    # 🔵 RESPOSTA EM CANAL
    if channel_type == "channel":
        try:
            client.chat_postMessage(
                channel=channel,
                text=f"👀 Vi sua mensagem: {text_original}"
            )
            print("✅ Respondeu canal")
        except SlackApiError as e:
            print("❌ ERRO canal:", e.response)

    # 🚨 DETECÇÃO DE KEYWORDS
    if any(word in text for word in KEYWORDS):
        print("🔥 KEYWORD DETECTADA!")
        send_slack_alerts(text_original)
    else:
        print("⚠️ Nenhuma keyword detectada")

    return "", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    app.run(port=port)
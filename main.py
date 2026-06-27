import os
import threading
import asyncio
import logging
from flask import Flask, request
from clawops.agent import ClawOpsAgent, OpenAIRealtime
from clawops import ClawOps

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

CLAWOPS_FROM = "07052753884"
CLAWOPS_API_KEY = os.environ.get("CLAWOPS_API_KEY", "")
CLAWOPS_ACCOUNT_ID = os.environ.get("CLAWOPS_ACCOUNT_ID", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("RAILWAY_URL", "https://api.wondanmarket.com")

clawops_client = ClawOps(
    api_key=CLAWOPS_API_KEY,
    account_id=CLAWOPS_ACCOUNT_ID,
)

agent = ClawOpsAgent(
    api_key=CLAWOPS_API_KEY,
    account_id=CLAWOPS_ACCOUNT_ID,
    from_=CLAWOPS_FROM,
    session=OpenAIRealtime(
        system_prompt="당신은 NANA, 친절한 AI 전화 대리 서비스입니다. 짧고 자연스럽게 대화하세요.",
        voice="marin",
        language="ko",
        api_key=OPENAI_API_KEY,
    ),
)

def run_agent():
    asyncio.run(agent.serve())

thread = threading.Thread(target=run_agent, daemon=True)
thread.start()

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "NANA AI"}

@app.route("/call", methods=["POST"])
def make_call():
    data = request.json
    to = data.get("to", "").replace("-", "").replace("+82", "0")
    user_request = data.get("request", "")
    print(f"📞 발신 요청: {to} / {user_request}")
    call = clawops_client.calls.create(
        to=to,
        from_=CLAWOPS_FROM,
    )
    return {"call_id": call.call_id, "status": "initiated"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
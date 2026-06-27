import os
import asyncio
from flask import Flask, request, jsonify
from clawops.agent import ClawOpsAgent, OpenAIRealtime
from clawops import ClawOps

app = Flask(__name__)

CLAWOPS_FROM = "07052753884"
CLAWOPS_API_KEY = os.environ.get("CLAWOPS_API_KEY", "")
CLAWOPS_ACCOUNT_ID = os.environ.get("CLAWOPS_ACCOUNT_ID", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

def create_agent(system_prompt):
    return ClawOpsAgent(
        api_key=CLAWOPS_API_KEY,
        account_id=CLAWOPS_ACCOUNT_ID,
        from_=CLAWOPS_FROM,
        session=OpenAIRealtime(
            system_prompt=system_prompt,
            voice="marin",
            language="ko",
            api_key=OPENAI_API_KEY,
        ),
    )

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "NANA AI"}

@app.route("/call", methods=["POST"])
def make_call():
    data = request.json
    to = data.get("to", "").replace("-", "").replace("+82", "0")
    user_request = data.get("request", "")

    system_prompt = f"""당신은 NANA, 친절한 AI 전화 대리 서비스입니다.
사용자가 요청한 용건: {user_request}
짧고 자연스럽게 대화하세요. 용건을 처리하면 통화를 종료하세요."""

    async def run_call():
        agent = create_agent(system_prompt)
        await agent.call(to)

    asyncio.run(run_call())
    return {"status": "initiated"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
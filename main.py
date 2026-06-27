import os
import re
import json
import base64
import time
import requests
import anthropic
from openai import OpenAI
from flask import Flask, request, Response
from flask_sock import Sock
from clawops import ClawOps

app = Flask(__name__)
sock = Sock(app)

clawops_client = ClawOps(
    api_key=os.environ.get("CLAWOPS_API_KEY", ""),
    account_id=os.environ.get("CLAWOPS_ACCOUNT_ID", ""),
)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

CLAWOPS_FROM = "07052753884"
BASE_URL = os.environ.get("RAILWAY_URL", "https://api.wondanmarket.com")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
VOICE_ID = "onwK4e9ZLuTAKqWW03F9"

call_scripts = {}
audio_cache = {}

def split_sentences(text):
    sentences = re.split(r'(?<=[.!?。]) +', text.strip())
    return [s for s in sentences if s]

def generate_tts(text, audio_id):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    body = {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        audio_cache[audio_id] = response.content
        print(f"✅ TTS 생성: {audio_id}")
        return True
    print(f"❌ ElevenLabs 실패: {response.status_code} {response.text}")
    return False

def generate_tts_bytes(text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    body = {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}, "output_format": "ulaw_8000"}
    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        return response.content
    print(f"❌ ElevenLabs 실패: {response.status_code} {response.text}")
    return None

def stt(audio_bytes):
    import tempfile, audioop, wave
    pcm_bytes = audioop.ulaw2lin(audio_bytes, 2)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        with wave.open(f.name, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(pcm_bytes)
        with open(f.name, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=audio_file, language="ko")
    return transcript.text

def ask_claude(user_text, system_prompt):
    message = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=200, system=system_prompt,
        messages=[{"role": "user", "content": user_text}]
    )
    return message.content[0].text

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "NANA AI"}

@app.route("/call", methods=["POST"])
def make_call():
    import uuid
    data = request.json
    to = data.get("to", "").replace("-", "").replace("+82", "0")
    script = data.get("script") or data.get("request", "안녕하세요. 나나입니다.")
    system_prompt = data.get("system_prompt", "당신은 친절한 AI 전화 대리 서비스입니다. 짧고 자연스럽게 대화하세요.")

    call_id = str(uuid.uuid4())[:8]
    sentences = split_sentences(script)
    audio_ids = []
    for i, sentence in enumerate(sentences):
        audio_id = f"{call_id}_{i}"
        if generate_tts(sentence, audio_id):
            audio_ids.append(audio_id)

    call_scripts[call_id] = {"audio_ids": audio_ids, "system_prompt": system_prompt}

    call = clawops_client.calls.create(
        to=to, from_=CLAWOPS_FROM,
        url=f"{BASE_URL}/twiml?id={call_id}",
        timeout=120,
    )
    return {"call_id": call.call_id, "status": "initiated"}

@app.route("/audio", methods=["GET"])
def audio():
    audio_id = request.args.get("id", "")
    if audio_id in audio_cache:
        data = audio_cache[audio_id]
        return Response(data, mimetype="audio/mpeg", headers={"Content-Length": len(data)})
    return "Not found", 404

@app.route("/twiml", methods=["GET", "POST"])
def twiml():
    call_id = request.args.get("id", "")
    data = call_scripts.get(call_id, {})
    audio_ids = data.get("audio_ids", [])
    ws_url = BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://')

    play_tags = ""
    for audio_id in audio_ids:
        if audio_id in audio_cache:
            play_tags += f'  <Play>{BASE_URL}/audio?id={audio_id}</Play>\n'

    if not play_tags:
        play_tags = '  <Say language="ko-KR">안녕하세요. 나나입니다.</Say>\n'

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
{play_tags}  <Connect>
    <Stream url="{ws_url}/stream?id={call_id}"/>
  </Connect>
</Response>"""
    return Response(xml, mimetype="text/xml")

@sock.route("/stream")
def stream(ws):
    call_id = request.args.get("id", "")
    data = call_scripts.get(call_id, {})
    system_prompt = data.get("system_prompt", "당신은 친절한 AI 전화 대리 서비스입니다. 짧고 자연스럽게 대화하세요.")

    audio_buffer = bytearray()
    stream_sid = None
    last_audio_time = None
    SILENCE_THRESHOLD = 1.5

    def process_and_respond():
        nonlocal audio_buffer
        if len(audio_buffer) < 3200:
            audio_buffer = bytearray()
            return
        buf = bytes(audio_buffer)
        audio_buffer = bytearray()
        try:
            text = stt(buf)
            print(f"📝 STT: {text}")
            if text.strip():
                response_text = ask_claude(text, system_prompt)
                print(f"🤖 Claude: {response_text}")
                tts_audio = generate_tts_bytes(response_text)
                if tts_audio and stream_sid:
                    payload = base64.b64encode(tts_audio).decode("utf-8")
                    try:
                        ws.send(json.dumps({
                            "event": "media",
                            "media": {"payload": payload}
                        }))
                        print("🔊 TTS 전송 완료")
                    except Exception as e:
                        print(f"❌ TTS 전송 실패: {e}")
        except Exception as e:
            print(f"❌ 오류: {e}")

    while True:
        try:
            msg = ws.receive()
            if msg is None:
                break
        except Exception:
            break

        try:
            event = json.loads(msg)
        except Exception:
            continue

        if event.get("event") == "start":
            stream_sid = event.get("start", {}).get("streamId")
            print(f"✅ Stream 시작: {stream_sid}")

        elif event.get("event") == "media":
            payload = event.get("media", {}).get("payload", "")
            audio_buffer.extend(base64.b64decode(payload))
            last_audio_time = time.time()

        elif event.get("event") == "stop":
            print(f"🛑 Stop.")
            process_and_respond()
            break

        if last_audio_time and time.time() - last_audio_time > SILENCE_THRESHOLD:
            if len(audio_buffer) > 3200:
                last_audio_time = None
                process_and_respond()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
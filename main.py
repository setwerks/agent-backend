from fastapi import FastAPI, Request
import openai
import os

app = FastAPI()
openai.api_key = os.getenv("OPENAI_API_KEY")

# in-memory thread cache
thread_cache = {}

@app.post("/onboarding-chat-assistant")
async def assistant_chat(request: Request):
    body = await request.json()
    message = body.get("message")
    session_id = body.get("sessionId")

    if not message:
        return { "error": "Message required" }

    # Thread management
    thread_id = thread_cache.get(session_id)
    if not thread_id:
        thread = openai.beta.threads.create()
        thread_id = thread.id
        thread_cache[session_id or thread_id] = thread_id

    openai.beta.threads.messages.create(thread_id, {
        "role": "user",
        "content": message
    })

    run = openai.beta.threads.runs.create(thread_id, {
        "assistant_id": os.getenv("ONBOARD_ASSISTANT_ID")
    })

    while True:
        run_status = openai.beta.threads.runs.retrieve(thread_id, run.id)
        if run_status.status == "completed":
            break
        await asyncio.sleep(1)

    messages = openai.beta.threads.messages.list(thread_id)
    assistant_message = next(
        (m for m in messages.data if m.role == "assistant"), None
    )

    text = ""
    if assistant_message and isinstance(assistant_message.content, list):
        for block in assistant_message.content:
            if block.get("type") == "text":
                text = block["text"]["value"]
                break

    return {
        "threadId": thread_id,
        "sessionId": session_id or thread_id,
        "message": text
    }


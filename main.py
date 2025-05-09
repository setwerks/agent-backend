from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.post("/onboard-agent-chat")
async def onboard_agent_chat(request: Request):
    data = await request.json()
    message = data.get("message", "No message provided.")
    return JSONResponse({"reply": f"You said: {message}"})

@app.get("/health")
async def health():
    return {"status": "ok"}

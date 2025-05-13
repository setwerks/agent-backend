import os
from dotenv import load_dotenv

# Load environment vars first
load_dotenv(override=True)  # override=True ensures .env values take precedence

# Debug logging for environment variables
print("Environment variables:")
print(f"GOOGLE_APPLICATION_CREDENTIALS: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
print(f"GOOGLE_CLOUD_PROJECT: {os.getenv('GOOGLE_CLOUD_PROJECT')}")
print(f"GOOGLE_CLOUD_REGION: {os.getenv('GOOGLE_CLOUD_REGION')}")
print(f"VERTEX_CHAT_MODEL_ID: {os.getenv('VERTEX_CHAT_MODEL_ID')}")

import json
import logging
import uvicorn
from uuid import uuid4
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from quest_tools import (
    load_session,
    save_session,
    update_quest_state,
    process_quest
)

# === FASTAPI SETUP ===
app = FastAPI()
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

class QuestRequest(BaseModel):
    session_id: Optional[str] = None
    message: str

class QuestResponse(BaseModel):
    status: str
    session_id: str
    quest_state: Dict[str, Any]

@app.post("/start-quest", response_model=QuestResponse)
async def start_quest(request: QuestRequest):
    # Generate or use provided session ID
    session_id = request.session_id or str(uuid4())
    
    # Load previous session
    session = await load_session(session_id)
    chat_history = session.get("chat_history", [])
    quest_state = session.get("quest_state", {})
    
    # Append user message to history
    chat_history.append({"role": "user", "content": request.message})
    
    # Process quest
    result = await process_quest(
        quest_text=request.message,
        session_id=session_id,
        chat_history=chat_history
    )
    
    # Update chat history with assistant response
    chat_history.append({"role": "assistant", "content": json.dumps(result)})
    
    # Save session
    # Reload quest_state after process_quest (it updates quest_state)
    session = await load_session(session_id)
    quest_state = session.get("quest_state", {})
    await save_session(session_id, quest_state, chat_history)
    
    return QuestResponse(
        status="ok",
        session_id=session_id,
        quest_state=quest_state
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

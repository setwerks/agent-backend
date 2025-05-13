import os
import logging
from dotenv import load_dotenv
logging.basicConfig(level=logging.INFO)
# Load environment vars first
load_dotenv(override=True)  # override=True ensures .env values take precedence

if os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"):
    with open("service-account.json", "w") as f:
        f.write(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service-account.json"
else:
    # Reconstruct from individual GOOGLE_* env vars if present
    required_keys = [
        "TYPE", "PROJECT_ID", "PRIVATE_KEY_ID", "PRIVATE_KEY", "CLIENT_EMAIL", "CLIENT_ID",
        "AUTH_URI", "TOKEN_URI", "AUTH_PROVIDER_X509_CERT_URL", "CLIENT_X509_CERT_URL"
    ]
    service_account = {}
    found = False
    for key in required_keys:
        env_key = f"GOOGLE_{key}"
        value = os.getenv(env_key)
        if value:
            found = True
            if key == "PRIVATE_KEY":
                value = value.replace("\\n", "\n")
            service_account[key.lower()] = value
    # Optional universe_domain
    universe_domain = os.getenv("GOOGLE_UNIVERSE_DOMAIN")
    if universe_domain:
        service_account["universe_domain"] = universe_domain
    if found:
        with open("service-account.json", "w") as f:
            import json
            json.dump(service_account, f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service-account.json"
#logging.info(f"GOOGLE_APPLICATION_CREDENTIALS: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
#logging.info(f"service-account.json exists: {os.path.exists('service-account.json')}")
if os.path.exists("service-account.json"):
    with open("service-account.json") as f:
        #logging.info(f"service-account.json contents:", f.read())
        pass
import json
import uvicorn
from uuid import uuid4
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from routes.quests import router as quests_router

from quest_tools import (
    load_session,
    save_session,
    update_quest_state,
    process_quest
)

# === FASTAPI SETUP ===
app = FastAPI()
app.include_router(quests_router)
#app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

class QuestRequest(BaseModel):
    session_id: Optional[str] = None
    message: str

class QuestResponse(BaseModel):
    status: str
    session_id: str
    quest_state: Dict[str, Any]

@app.post("/start-quest", response_model=QuestResponse)
async def start_quest(request: QuestRequest):
    try:
        logging.info("/start-quest endpoint called with: %s", request)
        # Generate or use provided session ID
        session_id = request.session_id or str(uuid4())
        logging.info(f"Using session_id: {session_id}")
        
        # Load previous session
        session = await load_session(session_id)
        logging.info(f"Loaded session: {session}")
        chat_history = session.get("chat_history", [])
        quest_state = session.get("quest_state", {})
        logging.info(f"Initial chat_history: {chat_history}")
        logging.info(f"Initial quest_state: {quest_state}")
        
        # Append user message to history
        chat_history.append({"role": "user", "content": request.message})
        logging.info(f"Appended user message. chat_history now: {chat_history}")
        
        # Process quest
        logging.info("Calling process_quest...")
        result = await process_quest(
            quest_text=request.message,
            session_id=session_id,
            chat_history=chat_history
        )
        logging.info(f"process_quest result: {result}")
        
        # Update chat history with assistant response
        chat_history.append({"role": "assistant", "content": json.dumps(result)})
        logging.info(f"Appended assistant response. chat_history now: {chat_history}")
        
        # Remove 'ui' before saving to Supabase
        quest_state_to_save = {k: v for k, v in result.items() if k != "ui"}
        await save_session(session_id, quest_state_to_save, chat_history)
        logging.info(f"Session saved for session_id: {session_id}")
        
        # Return the full result (including 'ui') to the frontend
        return QuestResponse(
            status="ok",
            session_id=session_id,
            quest_state=result
        )
    except Exception as e:
        logging.exception("Error in /start-quest endpoint")
        raise

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

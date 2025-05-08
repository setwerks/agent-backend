from fastapi import FastAPI, Request
import openai
import os
import asyncio

app = FastAPI()

openai.api_key = os.getenv("OPENAI_API_KEY")

# Create the assistant agent with tools (optional)
onboarding_agent = openai.agent.Agent.create(
    name="onboarding-chat-assistant",
    instructions="You are a helpful assistant guiding new users through onboarding. Use tools or provide clear answers.",
    tools=[
        openai.agent.Tool.function({
            "name": "get_started_steps",
            "description": "Explains onboarding steps",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_type": {
                        "type": "string",
                        "description": "Type of user onboarding, e.g., creator, seeker, guest"
                    }
                },
                "required": ["user_type"]
            }
        })
    ]
)

# Tool definition
@onboarding_agent.function
def get_started_steps(user_type: str):
    steps = {
        "creator": "1. Set up your profile\n2. Create your first offer\n3. Share your profile",
        "seeker": "1. Set your interests\n2. Browse matches\n3. Connect with creators",
        "guest": "1. Explore the app\n2. Sign up to save favorites\n3. Create a quest"
    }
    return steps.get(user_type.lower(), "1. Explore the platform\n2. Create your account\n3. Follow onboarding tips")

# Endpoint for frontend/mobile use
@app.post("/agent-chat")
async def agent_chat(request: Request):
    body = await request.json()
    message = body.get("message")
    session_id = body.get("sessionId")  # Optional, for tracking/memory

    if not message:
        return {"error": "Missing message"}

    # Create or reuse thread (in-memory, simple demo)
    thread = onboarding_agent.new_thread(session_id=session_id or None)
    thread.send(message)

    response = thread.run()

    while response.status != "completed":
        await asyncio.sleep(1)
        response.refresh()

    reply = response.output.get("content", "No response generated.")
    return {
        "message": reply,
        "session_id": session_id,
        "thread_id": thread.id
    }


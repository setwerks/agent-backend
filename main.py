from fastapi import FastAPI, Request
from agents import Agent, Runner, function_tool, RunConfig
import os
import requests
import uvicorn
import json
from dotenv import load_dotenv


import logging
load_dotenv()
logging.basicConfig(
    level=logging.INFO,  # or DEBUG for even more detail
    format="%(levelname)s: %(message)s"
)

# ✅ Initialize FastAPI app
app = FastAPI()

# ✅ Set OpenAI API Key (optional if already in environment)
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")
# ✅ Define and register a tool using the decorator
@function_tool
def geocode_location(location: str) -> str:
    """Get coordinates and a map preview for a location."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": location,
        "format": "json",
        "limit": 1
    }
    headers = {
        "User-Agent": "Questor-Agent/1.0"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"Error fetching location data: {str(e)}"

    if not data:
        return f"Sorry, I couldn't find '{location}'."

    result = data[0]
    lat = result["lat"]
    lon = result["lon"]
    map_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"
    return f"{location} is at latitude {lat}, longitude {lon}. [View on Map]({map_url})"

# ✅ Create agent with the tool
onboarding_agent = Agent(
    name="onboarding-chat-assistant",
    instructions="You are a helpful assistant that guides users through onboarding. Use tools if needed.",
    tools=[geocode_location],
    model="gpt-4o"  # Optional: use a specific OpenAI model
)

@app.post("/onboard-agent-chat")
async def agent_chat(request: Request):
    try:
        body = await request.json()
        message = body.get("message")

        if not message:
            return {"error": "Missing 'message'"}

        result = await Runner.run(
            onboarding_agent,
            message,
            run_config=RunConfig(workflow_name="onboarding_flow")
        )

        # ✅ Dump all attributes manually
        logging.info("=== RunResult attributes ===")
        for attr in dir(result):
            if not attr.startswith("_") and not callable(getattr(result, attr)):
                try:
                    val = getattr(result, attr)
                    logging.info(f"{attr} = {val}")
                except Exception as e:
                    logging.warning(f"{attr} could not be read: {e}")

        return {
            "message": result.final_output
        }

    except Exception as e:
        logging.exception("Agent run failed")
        return {"error": str(e)}
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

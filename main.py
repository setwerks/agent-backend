from fastapi import FastAPI, Request
from agents import Agent, Runner, function_tool
import os
import requests
import uvicorn

# ✅ Define FastAPI app *before* launching Uvicorn
app = FastAPI()

# Set OpenAI API Key (optional if already set in the environment)
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")


# ✅ Define and register the tool using the decorator
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

# ✅ Create agent with tool
onboarding_agent = Agent(
    name="onboarding-chat-assistant",
    instructions="You are a helpful assistant that guides users through onboarding. Use tools if needed.",
    tools=[geocode_location],
    model="gpt-4o"  # Optional: specify model
)

# ✅ Define API endpoint
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
            run_config={"workflow_name": "onboarding_flow"}  # Optional tracing
        )

        return {
            "message": result.final_output,
            "trace_id": result.trace_id
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
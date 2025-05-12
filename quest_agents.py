from agents import Agent
from quest_tools import (
    load_session,
    save_session,
    update_quest_state,
    classify_quest,
    geocode_location,
    confirm_location,
)
from quest_prompts import (
    FOR_SALE_PROMPT,
    HOUSING_PROMPT,
    JOBS_PROMPT,
    SERVICES_PROMPT,
    COMMUNITY_PROMPT,
    GIGS_PROMPT,
)

category_agents = {
    "for_sale": Agent(
        name="quest_for_sale",
        instructions=FOR_SALE_PROMPT,
        tools=[
            load_session,
            classify_quest,
            update_quest_state,
            geocode_location,
            confirm_location,
            save_session,
        ],
        model="gpt-4o",
    ),
    "housing": Agent(
        name="quest_housing",
        instructions=HOUSING_PROMPT,
        tools=[
            load_session,
            classify_quest,
            update_quest_state,
            geocode_location,
            confirm_location,
            save_session,
        ],
        model="gpt-4o",
    ),
    "jobs": Agent(
        name="quest_jobs",
        instructions=JOBS_PROMPT,
        tools=[
            load_session,
            classify_quest,
            update_quest_state,
            confirm_location,
            save_session,
        ],
        model="gpt-4o",
    ),
    "services": Agent(
        name="quest_services",
        instructions=SERVICES_PROMPT,
        tools=[
            load_session,
            classify_quest,
            update_quest_state,
            save_session,
        ],
        model="gpt-4o",
    ),
    "community": Agent(
        name="quest_community",
        instructions=COMMUNITY_PROMPT,
        tools=[
            load_session,
            classify_quest,
            update_quest_state,
            geocode_location,
            confirm_location,
            save_session,
        ],
        model="gpt-4o",
    ),
    "gigs": Agent(
        name="quest_gigs",
        instructions=GIGS_PROMPT,
        tools=[
            load_session,
            classify_quest,
            update_quest_state,
            save_session,
        ],
        model="gpt-4o",
    ),
}

dynamic_agent = Agent(
    name="quest_generic",
    instructions="You are a generic quest agent. Ask clarifying questions.",
    tools=[load_session, classify_quest, update_quest_state, save_session],
    model="gpt-4o",
)

# TASK 6 EXTENSION (§C): seed the pgvector tool-router table.
"""
Embed each agent tool's description into tool_descriptions so the agent can pick
the right tool by semantic similarity when the LLM mis-routes.

Usage (after docker compose up -d, and the schema is loaded):
    python skeleton/seed_tool_router.py

Idempotent: store_tool_description upserts by tool name.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from skeleton.agent import TOOLS
from skeleton.llm_provider import llm
from databases.relational.queries import store_tool_description

# Curated trigger phrases per tool: appended to the embedded text to sharpen
# recall for the phrasings real users employ (kept small and human-readable).
TRIGGER_PHRASES = {
    "search_policy": "refund delay compensation luggage bicycle pets food conduct rules "
                     "fare evasion child fare entitled to compensation",
    "find_route": "how do I get from A to B, fastest route, quickest way, shortest path, "
                  "directions, journey, change between metro and rail, cross-network",
    "find_alternative_routes": "avoid a closed or delayed station, alternative route around",
    "get_delay_ripple": "which stations are affected by a disruption or delay, knock-on impact",
    "get_user_bookings": "my bookings, my tickets, my trips, my travel history, my reservations",
    "check_national_rail_availability": "what trains run, rail timetable, rail schedule, services between",
    "check_metro_availability": "metro services, metro timetable between two stations",
    "get_metro_fare": "metro fare, metro price, how much does the metro cost",
    "get_national_rail_fare": "rail fare, rail ticket price, how much is the train",
    "get_available_seats": "available seats, choose a seat, seat map",
    "make_booking": "book a ticket, make a reservation, reserve a seat",
    "cancel_booking": "cancel my booking, cancel reservation, refund a booking",
}


def seed():
    count = 0
    for tool in TOOLS:
        name = tool["name"]
        description = tool["description"]
        triggers = TRIGGER_PHRASES.get(name, "")
        text = f"{name}: {description} {triggers}".strip()
        embedding = llm.embed(text)
        store_tool_description(name, description, embedding, triggers)
        count += 1
        print(f"  embedded tool: {name}")
    print(f"\nDone: {count} tool descriptions embedded into tool_descriptions.")


if __name__ == "__main__":
    print("Seeding pgvector tool router...")
    seed()

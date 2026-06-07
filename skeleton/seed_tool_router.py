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
from databases.relational.queries import store_tool_description, clear_tool_descriptions

# Near-duplicate / internal tools excluded from the router so they don't steal
# candidates from the user-facing tool. calculate_metro_fare(schedule_id, stops)
# overlaps with the user-facing get_metro_fare(origin, destination).
SKIP_TOOLS = {"calculate_metro_fare"}

# Curated trigger phrases per tool: appended to the embedded text to sharpen
# recall for the phrasings real users employ. Phrasings are chosen to DISAMBIGUATE
# easily-confused tools (e.g. policy-vs-disruption when a query mentions "delay",
# or policy-vs-metro when a query mentions "metro").
TRIGGER_PHRASES = {
    "search_policy": "company policy question; am I entitled to a refund; delay compensation; "
                     "claim compensation for a delayed train; refund eligibility rules; "
                     "luggage allowance; bicycles and bikes; pets, dogs, cats, animals on board; "
                     "food and drink; code of conduct; booking rules; ticket types; fare evasion penalty; "
                     "child and concession fares; applies even when the question mentions metro, rail or a train",
    "find_route": "how do I get from one station to another; travel from X to Y; "
                  "fastest route; quickest way; shortest path; directions; journey planning; "
                  "cross-network trip using both metro and national rail; changing between networks",
    "find_alternative_routes": "a route that avoids one specific closed or blocked station; reroute around a station",
    "get_delay_ripple": "which stations and lines are affected if a station is disrupted or closed; "
                        "knock-on ripple impact within N hops; how far a closure propagates",
    "get_user_bookings": "my bookings; my tickets; my trips; my travel history; my reservations",
    "check_national_rail_availability": "what national rail trains run between two stations; rail timetable; rail schedule; rail services and departures",
    "check_metro_availability": "what metro services run between two metro stations; metro timetable and departures",
    "get_metro_fare": "how much does the metro cost; metro ticket price or fare between two stations",
    "get_national_rail_fare": "how much is the train; national rail ticket price or fare for a schedule",
    "get_available_seats": "which seats are available; choose or pick a seat; seat map for a service",
    "make_booking": "book a ticket; make a reservation; reserve a seat",
    "cancel_booking": "cancel my booking; cancel a reservation by its booking reference",
}


def seed():
    clear_tool_descriptions()  # rebuild from scratch so excluded tools don't linger
    count = 0
    for tool in TOOLS:
        name = tool["name"]
        if name in SKIP_TOOLS:
            print(f"  skipped (duplicate/internal): {name}")
            continue
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

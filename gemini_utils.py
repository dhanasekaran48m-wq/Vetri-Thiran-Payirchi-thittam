import os
from pathlib import Path

from dotenv import load_dotenv

try:
    from google import genai
except ImportError:
    genai = None

# Load .env from project folder
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("GOOGLE_API_KEY")

if genai is not None and API_KEY:
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception:
        client = None
else:
    client = None


def ask_gemini(prompt: str):
    if client is None:
        return "Gemini configuration error: GOOGLE_API_KEY is missing or the google-genai package is not installed."

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        return getattr(response, "text", str(response))
    except Exception as e:
        return f"Gemini Error: {str(e)}"


def get_home_recommendations(data):
    prompt = f"""
    Create a home budget plan.

    Budget: ₹{data.total_budget}
    Lights: {data.num_lights}
    Fans: {data.num_fans}
    Furniture: {data.num_furniture}
    Dining Tables: {data.num_dining_tables}
    Living Room: {data.has_living_room}
    Kitchen: {data.has_kitchen}
    Bedroom: {data.has_bedroom}
    Extra: {data.additional_requirements}

    Give item-wise budget and savings.
    """

    text = ask_gemini(prompt)

    return {
        "category": "Home",
        "total_budget": data.total_budget,
        "remaining_budget": 0,
        "recommendation": text,
    }


def get_party_recommendations(data):
    prompt = f"""
    Create a party budget.

    Budget: ₹{data.total_budget}
    Party Type: {data.party_type}
    Guests: {data.num_guests}
    Venue: {data.venue_type}
    Catering: {data.needs_catering}
    Decoration: {data.needs_decoration}
    Entertainment: {data.needs_entertainment}
    Extra: {data.additional_requirements}

    Give complete budget split.
    """

    text = ask_gemini(prompt)

    return {
        "category": "Party",
        "total_budget": data.total_budget,
        "remaining_budget": 0,
        "recommendation": text,
    }


def get_jewelry_recommendations(data, image_path=None):
    prompt = f"""
    Suggest jewelry.

    Budget: ₹{data.total_budget}
    Occasion: {data.occasion}
    Preference: {data.preferences}

    Recommend gold, silver or diamond options.
    """

    text = ask_gemini(prompt)

    return {
        "category": "Jewelry",
        "total_budget": data.total_budget,
        "remaining_budget": 0,
        "image": image_path,
        "recommendation": text,
    }

import re

TARGET_COUNTIES = ["Orange County", "Seminole County", "Volusia County", "Lake County", "Flagler County"]

HIGH_PRIORITY_CITIES = {
    "Apopka",
    "Clermont",
    "Daytona Beach",
    "DeLand",
    "Deltona",
    "Flagler Beach",
    "Lake Mary",
    "Leesburg",
    "Mount Dora",
    "Ormond Beach",
    "Palm Coast",
    "Port Orange",
    "Sanford",
    "Winter Garden",
    "Winter Park",
}

COUNTY_CITY_MAP = {
    "Orange County": [
        "Apopka",
        "Bay Lake",
        "Belle Isle",
        "Edgewood",
        "Eatonville",
        "Lake Buena Vista",
        "Maitland",
        "Oakland",
        "Ocoee",
        "Orlando",
        "Windermere",
        "Winter Garden",
        "Winter Park",
    ],
    "Seminole County": [
        "Altamonte Springs",
        "Casselberry",
        "Lake Mary",
        "Longwood",
        "Oviedo",
        "Sanford",
        "Winter Springs",
    ],
    "Volusia County": [
        "Daytona Beach",
        "Daytona Beach Shores",
        "DeBary",
        "DeLand",
        "Deltona",
        "Edgewater",
        "Holly Hill",
        "Lake Helen",
        "New Smyrna Beach",
        "Oak Hill",
        "Orange City",
        "Ormond Beach",
        "Pierson",
        "Ponce Inlet",
        "Port Orange",
        "South Daytona",
    ],
    "Lake County": [
        "Astatula",
        "Clermont",
        "Eustis",
        "Fruitland Park",
        "Groveland",
        "Howey-in-the-Hills",
        "Lady Lake",
        "Leesburg",
        "Mascotte",
        "Minneola",
        "Montverde",
        "Mount Dora",
        "Tavares",
        "Umatilla",
    ],
    "Flagler County": [
        "Beverly Beach",
        "Bunnell",
        "Flagler Beach",
        "Marineland",
        "Palm Coast",
    ],
}


def slugify_city_name(city_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", city_name.lower()).strip("-")
    return re.sub(r"-+", "-", slug)


def priority_for_city(city_name: str) -> str:
    if city_name == "Orlando":
        return "Primary"
    if city_name in HIGH_PRIORITY_CITIES:
        return "High"
    return "Medium"


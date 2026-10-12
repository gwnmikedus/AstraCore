"""Canonical destinations for the operation and its supporting pages."""

PRIMARY_NAV = [
    ("Home", "/", "house", "Your operation at a glance"),
    ("Plan", "/pi/plan", "layers", "Build a plan around your playtime"),
    ("Operate", "/pi/operate", "timer", "Run your current operation"),
    ("Characters", "/profile", "users", "Manage your connected alts"),
]

PLAN_NAV = [
    ("Plan", "/pi/plan", "layers"),
    ("Area", "/pi/area", "map"),
    ("Settings", "/pi/settings", "settings"),
]

COMMUNITY_PATHS = (
    "/about", "/project", "/credits", "/releases", "/roadmap", "/community",
    "/feedback", "/what-we-read", "/privacy",
)


def section_for(path: str) -> str:
    """Keep the parent destination selected on its supporting pages."""
    if path in ("/", "/welcome"):
        return "/"
    if path == "/profile" or path.startswith("/profile/"):
        return "/profile"
    if path == "/pi/operate" or path.startswith("/pi/operate/"):
        return "/pi/operate"
    if path == "/pi" or path.startswith("/pi/"):
        return "/pi/plan"
    if any(path == prefix or path.startswith(prefix + "/") for prefix in COMMUNITY_PATHS):
        return "/community"
    return ""

"""Canonical destinations for the operation and its supporting pages.

Module sub-navigation (PI: Plan · Area · Settings) comes from `Module.nav` in the module registry.
"""

PRIMARY_NAV = [
    ("Home", "/", "house", "Your operation at a glance"),
    ("Plan", "/pi/plan", "layers", "Build a plan around your playtime"),
    ("Operate", "/pi/operate", "timer", "Run your current operation"),
    ("Characters", "/profile", "users", "Manage your connected alts"),
]

COMMUNITY_PATHS = (
    "/about", "/project", "/credits", "/releases", "/roadmap", "/community",
    "/feedback", "/what-we-read", "/privacy",
)


def section_for(path: str) -> str:
    """Keep the parent destination selected on its supporting pages."""
    if path in ("/", "/welcome"):
        return "/"
    if path == "/profile" or path.startswith("/profile/") or path == "/pi/reset":
        return "/profile"
    if path == "/pi/glossary":
        return ""   # a help page linked from the "?" answers, not a plan setup step
    if path == "/pi/operate" or path.startswith("/pi/operate/"):
        return "/pi/operate"
    if path == "/pi" or path.startswith("/pi/"):
        return "/pi/plan"
    if any(path == prefix or path.startswith(prefix + "/") for prefix in COMMUNITY_PATHS):
        return "/community"
    return ""

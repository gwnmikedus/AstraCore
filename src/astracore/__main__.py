"""Run with: python -m astracore   (mode from ASTRACORE_MODE, default local)."""
import sys

import uvicorn

from . import config


def main() -> None:
    if config.PRODUCTION:
        missing = config.missing_production_secrets()
        if missing:
            sys.exit("Refusing to start in production mode; missing in .env.production: " + ", ".join(missing))
    print(f"Astracore ({config.MODE}) on {config.PUBLIC_URL} (listening on {config.HOST}:{config.PORT})")
    reload = not config.PRODUCTION and config.env("ASTRACORE_RELOAD") == "1"   # local development only
    uvicorn.run("astracore.app:app", host=config.HOST, port=config.PORT, log_level="info",
                proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                reload=reload, reload_dirs=[str(config.ROOT / "src" / "astracore")] if reload else None)


if __name__ == "__main__":
    main()

"""Run with: python -m pi_planner"""
import uvicorn

from .config import HOST, PORT


def main() -> None:
    print(f"PI Planner running on http://localhost:{PORT}")
    uvicorn.run("pi_planner.app:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()

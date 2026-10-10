#!/usr/bin/env python3
"""Validate release metadata without starting the app; optionally print GitHub release notes."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from astracore.core.releases import RELEASE_DATA, validate  # noqa: E402


def package_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", text)
    version = re.search(r'^version\s*=\s*"([^"]+)"\s*$', project.group(1), re.M) if project else None
    if not version:
        raise ValueError("pyproject.toml must declare a project version")
    return version.group(1)


def release_notes(entry: dict) -> str:
    lines = [f"# AstraCore {entry['version']} — {entry['title']}", ""]
    if entry["date"]:
        lines.extend([entry["date"], ""])
    else:
        lines.extend(["Historical baseline; original release date not recorded.", ""])
    for heading, field in (("Changes", "changes"), ("Good to know", "limitations"), ("Technical details", "technical")):
        if entry[field]:
            lines.extend([f"## {heading}", ""])
            lines.extend(f"- {item}" for item in entry[field])
            lines.append("")
    if entry.get("references"):
        lines.extend(["## Development links", ""])
        lines.extend(f"- [{item['label']}]({item['url']})" for item in entry["references"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Require an exact version tag, such as v1.1.0")
    parser.add_argument("--notes", metavar="VERSION", help="Print the release notes for a version")
    args = parser.parse_args()
    try:
        data = json.loads(RELEASE_DATA.read_text(encoding="utf-8"))
        version = package_version()
        validate(data, version)
        if args.tag and args.tag != f"v{version}":
            raise ValueError(f"release tag must be v{version}")
        if args.notes:
            entry = next((item for item in data["releases"] if item["version"] == args.notes), None)
            if entry is None:
                raise ValueError("requested release notes do not exist")
            print(release_notes(entry))
        else:
            print(f"Release metadata valid: {version}")
    except (OSError, ValueError) as exc:
        print(f"Release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

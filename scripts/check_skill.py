"""Validate the repository's distributable clitg skill."""

from pathlib import Path

import yaml

SKILL = Path("skills/clitg/SKILL.md")
OPENAI = Path("skills/clitg/agents/openai.yaml")


def main() -> None:
    """Validate required frontmatter and UI metadata."""
    content = SKILL.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise SystemExit("SKILL.md frontmatter is missing")
    _, raw_frontmatter, body = content.split("---", maxsplit=2)
    frontmatter = yaml.safe_load(raw_frontmatter)
    if set(frontmatter) != {"name", "description"}:
        raise SystemExit("SKILL.md must contain only name and description frontmatter")
    if frontmatter["name"] != "clitg" or not frontmatter["description"] or not body.strip():
        raise SystemExit("SKILL.md content is incomplete")
    metadata = yaml.safe_load(OPENAI.read_text(encoding="utf-8"))
    interface = metadata.get("interface", {})
    if not {"display_name", "short_description", "default_prompt"} <= set(interface):
        raise SystemExit("agents/openai.yaml interface is incomplete")
    if "$clitg" not in interface["default_prompt"]:
        raise SystemExit("default_prompt must mention $clitg")


if __name__ == "__main__":
    main()

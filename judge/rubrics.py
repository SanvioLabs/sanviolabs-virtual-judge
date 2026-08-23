"""Load rubrics from YAML files."""

from pathlib import Path

import yaml

from . import db

RUBRICS_DIR = Path(__file__).parent.parent / "rubrics"


def load_rubric_from_yaml(path: Path) -> dict:
    """Parse a rubric YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data


def sync_rubrics_to_db():
    """Load all YAML rubrics into the database (idempotent by name)."""
    existing = {r["name"]: r for r in db.list_rubrics()}

    for yaml_file in RUBRICS_DIR.glob("*.yaml"):
        data = load_rubric_from_yaml(yaml_file)
        name = data["name"]

        if name not in existing:
            db.create_rubric(
                name=name,
                categories=data["categories"],
                scale_min=data.get("scale_min", 1),
                scale_max=data.get("scale_max", 5),
                description=data.get("description", ""),
                calibration=data.get("calibration", ""),
                judge_persona=data.get("judge_persona", ""),
            )


def get_default_rubric_id() -> str:
    """Get the first rubric ID (or create from YAML if none exist)."""
    rubrics = db.list_rubrics()
    if not rubrics:
        sync_rubrics_to_db()
        rubrics = db.list_rubrics()
    return rubrics[0]["id"]

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
    """The rubric an event gets when it names none.

    A rubric file may claim it with `default: true`. Without that the most
    recently created wins, which is invisible on a one-rubric install and
    surprising on the day somebody adds a second: an event is then judged
    against whichever was loaded last rather than whichever was meant.

    The flag is opt-in, so nothing changes for anyone who does not use it, and
    a flag naming a rubric that never loaded falls back rather than failing.
    """
    loaded = db.list_rubrics()
    if not loaded:
        sync_rubrics_to_db()
        loaded = db.list_rubrics()

    by_name = {r["name"]: r["id"] for r in loaded}
    for yaml_file in sorted(RUBRICS_DIR.glob("*.yaml")):
        data = load_rubric_from_yaml(yaml_file)
        if data.get("default") and data.get("name") in by_name:
            return by_name[data["name"]]

    return loaded[0]["id"]

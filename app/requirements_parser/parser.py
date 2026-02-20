import json
from pathlib import Path
from .models import RequirementsFile, Requirement


def parse_json(filepath: str | Path) -> RequirementsFile:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RequirementsFile(**data)


def parse_json_string(content: str) -> RequirementsFile:
    data = json.loads(content)
    return RequirementsFile(**data)

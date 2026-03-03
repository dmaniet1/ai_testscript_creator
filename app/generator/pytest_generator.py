from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from ..requirements_parser.models import Requirement, RequirementsFile

TEMPLATE_DIR = Path(__file__).parent.parent / "pytest_templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_pytest_testcase(req: Requirement) -> str:
    env = _get_env()
    template = env.get_template(f"{req.type.value}.py.j2")
    return template.render(req=req, timestamp=datetime.now().isoformat())


def generate_pytest_modules(req_file: RequirementsFile) -> dict[str, str]:
    """
    Returns a dict of { filename: pytest_content }
    e.g. { "test_timing.py": "import pytest\n\nclass Test_REQ001..." }
    """
    groups = defaultdict(list)
    for req in req_file.requirements:
        groups[req.type.value].append(req)

    type_to_filename = {
        "timing":   f"test_{req_file.project}_timing.py",
        "signal":   f"test_{req_file.project}_signal.py",
        "response": f"test_{req_file.project}_response.py",
        "presence": f"test_{req_file.project}_presence.py",
    }

    modules = {}
    for req_type, reqs in groups.items():
        filename = type_to_filename.get(req_type, f"test_{req_file.project}_{req_type}.py")
        header = (
            f'"""\n'
            f"pytest Test Module : {filename}\n"
            f"Project            : {req_file.project}\n"
            f"Generated          : {datetime.now().isoformat()}\n"
            f"Requirements       : {', '.join(r.id for r in reqs)}\n"
            f'"""\n\n'
        )
        body = "\n\n".join(render_pytest_testcase(req) for req in reqs)
        modules[filename] = header + body

    return modules


def generate_conftest(req_file: RequirementsFile) -> str:
    env = _get_env()
    template = env.get_template("conftest.py.j2")
    return template.render(
        project=req_file.project,
        timestamp=datetime.now().isoformat()
    )

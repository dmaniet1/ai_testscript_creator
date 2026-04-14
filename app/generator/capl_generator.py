from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from ..requirements_parser.models import Requirement, RequirementsFile

TEMPLATE_DIR = Path(__file__).parent.parent / "capl_templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_testcase(req: Requirement) -> str:
    env = _get_env()
    template = env.get_template(f"{req.type.value}.can.j2")
    return template.render(req=req, timestamp=datetime.now().isoformat())


def group_by_type(requirements: list[Requirement]) -> dict[str, list[Requirement]]:
    """Group requirements by type — each group becomes one .can module."""
    groups = defaultdict(list)
    for req in requirements:
        groups[req.type.value].append(req)
    return dict(groups)


def generate_capl_modules(req_file: RequirementsFile) -> dict[str, str]:
    """
    Returns a dict of { filename: capl_content }
    e.g. { "CAN_Timing_Tests.can": "/* ... */\n\ntestcase TC_REQ001 ..." }
    """
    groups = group_by_type(req_file.requirements)
    modules = {}

    type_to_filename = {
        "timing":   f"{req_file.project}_Timing_Tests.can",
        "signal":   f"{req_file.project}_Signal_Tests.can",
        "response": f"{req_file.project}_Response_Tests.can",
        "presence": f"{req_file.project}_Presence_Tests.can",
    }

    for req_type, reqs in groups.items():
        filename = type_to_filename.get(req_type, f"{req_file.project}_{req_type}_Tests.can")
        header = (
            f"/*\n"
            f" * CAPL Test Module : {filename}\n"
            f" * Project          : {req_file.project}\n"
            f" * Generated        : {datetime.now().isoformat()}\n"
            f" * Requirements     : {', '.join(r.id for r in reqs)}\n"
            f" */\n\n"
        )
        body = "\n\n".join(render_testcase(req) for req in reqs)
        modules[filename] = header + body

    return modules

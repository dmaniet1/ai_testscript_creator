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


def _proto_key(req: Requirement) -> str:
    """Return 'ETH' for Ethernet requirements, 'CAN' for everything else."""
    return "ETH" if req.protocol.upper() == "ETHERNET" else "CAN"


def render_testcase(req: Requirement) -> str:
    env = _get_env()
    prefix = "eth_" if _proto_key(req) == "ETH" else ""
    template = env.get_template(f"{prefix}{req.type.value}.can.j2")
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
    Groups by (protocol_key, type) so CAN and Ethernet produce separate .can modules.
    e.g. { "Project_CAN_Timing_Tests.can": ..., "Project_ETH_Signal_Tests.can": ... }
    """
    groups: dict[tuple[str, str], list[Requirement]] = defaultdict(list)
    for req in req_file.requirements:
        groups[(_proto_key(req), req.type.value)].append(req)

    modules = {}
    for (proto, req_type), reqs in groups.items():
        filename = f"{req_file.project}_{proto}_{req_type.capitalize()}_Tests.can"
        header = (
            f"/*\n"
            f" * CAPL Test Module : {filename}\n"
            f" * Project          : {req_file.project}\n"
            f" * Protocol         : {proto}\n"
            f" * Generated        : {datetime.now().isoformat()}\n"
            f" * Requirements     : {', '.join(r.id for r in reqs)}\n"
            f" */\n\n"
        )
        body = "\n\n".join(render_testcase(req) for req in reqs)
        modules[filename] = header + body

    return modules

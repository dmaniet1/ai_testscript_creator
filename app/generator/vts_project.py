from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString
from datetime import datetime
from ..requirements_parser.models import RequirementsFile


def _pretty_xml(root: Element) -> str:
    raw = tostring(root, encoding="unicode")
    return parseString(raw).toprettyxml(indent="  ")


def generate_vts_project(req_file: RequirementsFile, capl_modules: dict[str, str]) -> str:
    """Generate a vTestStudio .vtp project XML file."""

    root = Element("TestConfiguration")
    root.set("version", "2.0")
    root.set("xmlns", "http://www.vector.com/vTestStudio")

    # Project info
    info = SubElement(root, "ProjectInfo")
    SubElement(info, "Name").text = req_file.project
    SubElement(info, "Version").text = req_file.version
    SubElement(info, "Author").text = req_file.author
    SubElement(info, "CreatedAt").text = datetime.now().isoformat()
    SubElement(info, "GeneratedBy").text = "CAPL-GEN v1.0"

    # Test modules — one per .can file
    modules_el = SubElement(root, "TestModules")

    for filename in capl_modules:
        module = SubElement(modules_el, "TestModule")
        module.set("name", filename.replace(".can", ""))
        module.set("file", filename)
        module.set("active", "true")

        # Add test cases within this module
        tc_list = SubElement(module, "TestCases")
        # Find requirements that belong to this module's type
        module_type = _filename_to_type(filename)
        for req in req_file.requirements:
            if req.type.value == module_type:
                tc = SubElement(tc_list, "TestCase")
                tc.set("id", req.id)
                tc.set("function", f"TC_{req.id.replace('-', '_')}_{_type_suffix(req.type.value)}")
                tc.set("title", req.title)
                tc.set("priority", req.priority.value)
                tc.set("status", req.status.value)
                SubElement(tc, "Description").text = req.description
                SubElement(tc, "AcceptanceCriteria").text = req.acceptance_criteria

    # Test execution order
    exec_el = SubElement(root, "ExecutionOrder")
    for filename in capl_modules:
        ref = SubElement(exec_el, "ModuleRef")
        ref.set("name", filename.replace(".can", ""))

    return _pretty_xml(root)


def generate_vtestunit(req_file: RequirementsFile, module_name: str, reqs: list) -> str:
    """Generate a .vtestunit file for a single test module."""

    root = Element("TestUnit")
    root.set("version", "1.0")
    root.set("name", module_name)

    for req in reqs:
        tc = SubElement(root, "TestCase")
        tc.set("id", req.id)
        tc.set("title", req.title)
        tc.set("verdict", "none")
        SubElement(tc, "RequirementRef").text = req.id

    return _pretty_xml(root)


def _filename_to_type(filename: str) -> str:
    mapping = {
        "Timing":   "timing",
        "Signal":   "signal",
        "Response": "response",
        "Presence": "presence",
    }
    for key, val in mapping.items():
        if key in filename:
            return val
    return "unknown"


def _type_suffix(req_type: str) -> str:
    suffixes = {
        "timing":   "TimingCheck",
        "signal":   "SignalRange",
        "response": "ResponseTime",
        "presence": "Presence",
    }
    return suffixes.get(req_type, "Test")

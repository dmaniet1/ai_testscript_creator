import os
import io
import json
import zipfile
from pathlib import Path
from datetime import datetime
import requests

from flask import Flask, render_template, request, jsonify, send_file

from app.requirements_parser.parser import parse_json_string
from app.requirements_parser.models import RequirementsFile
from app.generator.capl_generator import generate_capl_modules
from app.generator.vts_project import generate_vts_project, generate_vtestunit, _filename_to_type

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["APPLICATION_ROOT"] = "/ai_test_gen"
BASE_URL = "/ai_test_gen"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_URL = "https://models.github.ai/inference/chat/completions"
MODEL = os.environ.get("GITHUB_MODEL", "openai/gpt-4.1")

# Keep request payload safely below model request-size limits.
MAX_RAG_CHARS = int(os.environ.get("MAX_RAG_CHARS", "14000"))
MAX_USER_PROMPT_CHARS = int(os.environ.get("MAX_USER_PROMPT_CHARS", "2000"))
MAX_REQUIREMENTS_CHARS = int(os.environ.get("MAX_REQUIREMENTS_CHARS", "3000"))
MAX_TEMPLATE_CHARS = int(os.environ.get("MAX_TEMPLATE_CHARS", "1200"))
MAX_PROJECT_FILE_CHARS = int(os.environ.get("MAX_PROJECT_FILE_CHARS", "1000"))
MAX_TEMPLATES = int(os.environ.get("MAX_TEMPLATES", "8"))
MAX_PROJECT_FILES = int(os.environ.get("MAX_PROJECT_FILES", "6"))


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _clip_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    omitted = len(text) - max_chars
    return f"{clipped}\n\n... [truncated {omitted} chars]"


def _fit_json_payload(payload: dict, max_chars: int) -> str:
    """Serialize and trim large sections until payload fits the max char budget."""
    serialized = json.dumps(payload, ensure_ascii=True)
    if len(serialized) <= max_chars:
        return serialized

    # Priority order for trimming if still too large.
    trim_order = [
        ("project_files", int(MAX_PROJECT_FILE_CHARS * 0.7)),
        ("capl_jinja_templates", int(MAX_TEMPLATE_CHARS * 0.7)),
        ("requirements_json", int(MAX_REQUIREMENTS_CHARS * 0.7)),
        ("user_prompt", int(MAX_USER_PROMPT_CHARS * 0.7)),
    ]

    for key, reduced_limit in trim_order:
        if key == "project_files":
            for f in list(payload.get("project_files", {}).keys()):
                payload["project_files"][f] = _clip_text(payload["project_files"][f], reduced_limit)
        elif key == "capl_jinja_templates":
            for t in list(payload.get("capl_jinja_templates", {}).keys()):
                payload["capl_jinja_templates"][t] = _clip_text(payload["capl_jinja_templates"][t], reduced_limit)
        else:
            payload[key] = _clip_text(str(payload.get(key, "")), reduced_limit)

        serialized = json.dumps(payload, ensure_ascii=True)
        if len(serialized) <= max_chars:
            return serialized

    # Last resort: remove project file bodies entirely.
    payload["project_files"] = {"note": "omitted to respect payload limit"}
    serialized = json.dumps(payload, ensure_ascii=True)
    if len(serialized) <= max_chars:
        return serialized

    # Absolute fallback: hard clip final JSON string.
    return _clip_text(serialized, max_chars)


def build_rag_context(user_prompt: str, raw_requirements: str = "") -> str:
    """Build JSON RAG context from templates and core project files."""
    root = Path(__file__).parent

    template_dir = root / "app" / "capl_templates"
    templates = {}
    if template_dir.exists():
        for tpl in sorted(template_dir.glob("*.j2"))[:MAX_TEMPLATES]:
            templates[tpl.name] = _clip_text(_safe_read(tpl), MAX_TEMPLATE_CHARS)

    important_files = [
        root / "app.py",
        root / "README.md",
        root / "requirements.txt",
        root / "app" / "generator" / "capl_generator.py",
        root / "app" / "generator" / "vts_project.py",
        root / "app" / "requirements_parser" / "models.py",
        root / "app" / "requirements_parser" / "parser.py",
    ]

    project_files = {}
    for f in important_files[:MAX_PROJECT_FILES]:
        if f.exists():
            project_files[str(f.relative_to(root))] = _clip_text(_safe_read(f), MAX_PROJECT_FILE_CHARS)

    libs = []
    reqs_txt = _safe_read(root / "requirements.txt")
    for line in reqs_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        libs.append(line)

    rag_payload = {
        "task": "Automotive requirement assistant for CAPL/vTestStudio generation",
        "user_prompt": _clip_text(user_prompt, MAX_USER_PROMPT_CHARS),
        "libraries": libs,
        "capl_jinja_templates": templates,
        "project_files": project_files,
        "requirements_json": _clip_text(raw_requirements, MAX_REQUIREMENTS_CHARS),
    }

    return _fit_json_payload(rag_payload, MAX_RAG_CHARS)


def ask_model(prompt: str, raw_requirements: str = "") -> str:
    if not GITHUB_TOKEN:
        return "Error: missing GITHUB_TOKEN environment variable."

    rag_context = build_rag_context(prompt, raw_requirements)
    try:
        response = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an assistant for automotive CAPL test generation. "
                            "Use the provided RAG JSON context (templates, libraries, and files) "
                            "to answer concretely and produce requirement JSON snippets when needed."
                        ),
                    },
                    {"role": "system", "content": rag_context},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 800,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        return f"Error: request failed: {exc}"

    if response.status_code != 200:
        return f"Error {response.status_code}: {response.text}"

    data = response.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/ai_test_gen/")
def index():
    return render_template("index.html", base_url=BASE_URL)

@app.route("/api/parse", methods=["POST"])
@app.route("/ai_test_gen/api/parse", methods=["POST"])
def parse_requirements():
    """Accept uploaded JSON, parse it, return structured preview data."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename.endswith(".json"):
        return jsonify({"error": "Only .json files supported in v1"}), 400

    try:
        content = f.read().decode("utf-8")
        req_file = parse_json_string(content)
    except Exception as e:
        return jsonify({"error": f"Parse error: {str(e)}"}), 422

    return jsonify({
        "project":      req_file.project,
        "version":      req_file.version,
        "author":       req_file.author,
        "count":        len(req_file.requirements),
        "requirements": [
            {
                "id":          r.id,
                "title":       r.title,
                "description": r.description,
                "type":        r.type.value,
                "protocol":    r.protocol,
                "priority":    r.priority.value,
                "status":      r.status.value,
                "parameters":  r.parameters,
            }
            for r in req_file.requirements
        ],
        "raw": content,
    })

@app.route("/api/generate", methods=["POST"])
@app.route("/ai_test_gen/api/generate", methods=["POST"])
def generate():
    """Generate CAPL scripts + vTestStudio project, return as zip."""
    data = request.get_json()
    if not data or "raw" not in data:
        return jsonify({"error": "Missing requirements data"}), 400

    try:
        req_file = parse_json_string(data["raw"])
    except Exception as e:
        return jsonify({"error": f"Parse error: {str(e)}"}), 422

    options = data.get("options", {})
    include_capl      = options.get("capl", True)
    include_vtp       = options.get("vtp", True)
    include_vtestunit = options.get("vtestunit", True)

    log = []

    # 1. Generate CAPL modules
    capl_modules = {}
    if include_capl:
        capl_modules = generate_capl_modules(req_file)
        for fname in capl_modules:
            log.append(f"✓ Generated {fname}")

    # 2. Generate vTestStudio project
    vtp_content = ""
    if include_vtp:
        vtp_content = generate_vts_project(req_file, capl_modules)
        log.append(f"✓ Generated {req_file.project}.vtp")

    # 3. Generate .vtestunit files
    vtestunit_files = {}
    if include_vtestunit:
        from collections import defaultdict
        groups = defaultdict(list)
        for r in req_file.requirements:
            groups[r.type.value].append(r)
        for rtype, reqs in groups.items():
            fname = f"{req_file.project}_{rtype.capitalize()}.vtestunit"
            vtestunit_files[fname] = generate_vtestunit(req_file, fname, reqs)
            log.append(f"✓ Generated {fname}")

    # 4. Pack into zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in capl_modules.items():
            zf.writestr(fname, content)
        if vtp_content:
            zf.writestr(f"{req_file.project}.vtp", vtp_content)
        for fname, content in vtestunit_files.items():
            zf.writestr(fname, content)
        zf.writestr("requirements.json", data["raw"])

    zip_buffer.seek(0)
    log.append("→ Zip ready for download")

    files = (
        list(capl_modules.keys())
        + ([f"{req_file.project}.vtp"] if vtp_content else [])
        + list(vtestunit_files.keys())
    )

    zip_path = OUTPUT_DIR / f"{req_file.project}_output.zip"
    with open(zip_path, "wb") as out:
        out.write(zip_buffer.getvalue())

    return jsonify({
        "success": True,
        "files":   files,
        "log":     log,
        "zip":     str(zip_path),
    })

@app.route("/api/download/<path:filename>")
@app.route("/ai_test_gen/api/download/<path:filename>")
def download(filename):
    zip_path = OUTPUT_DIR / filename
    if not zip_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(
        zip_path,
        as_attachment=True,
        download_name=zip_path.name,
        mimetype="application/zip",
    )

@app.route("/api/sample")
@app.route("/ai_test_gen/api/sample")
def sample():
    sample_path = Path("sample/requirements.json")
    if sample_path.exists():
        return send_file(sample_path, mimetype="application/json")
    return jsonify({"error": "Sample not found"}), 404


@app.route("/api/ask", methods=["POST"])
@app.route("/ai_test_gen/api/ask", methods=["POST"])
def ask():
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip()
    raw_requirements = data.get("raw", "")

    if not prompt:
        return jsonify({"error": "Missing prompt"}), 400

    answer = ask_model(prompt, raw_requirements)
    if answer.startswith("Error"):
        return jsonify({"error": answer}), 500

    return jsonify({"answer": answer, "model": MODEL})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8181)
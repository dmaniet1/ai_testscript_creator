import os
import io
import json
import zipfile
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file

from app.requirements_parser.parser import parse_json_string
from app.requirements_parser.models import RequirementsFile
from app.generator.capl_generator import generate_capl_modules
from app.generator.vts_project import generate_vts_project, generate_vtestunit, _filename_to_type

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB max upload
app.config["APPLICATION_ROOT"] = "/ai_test_gen"
BASE_URL = "/ai_test_gen"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/ai_test_gen/")
def index():
    ...

@app.route("/ai_test_gen/api/parse", methods=["POST"])
def parse_requirements():
    ...

@app.route("/ai_test_gen/api/download/<path:filename>")
def download(filename):
    ...

@app.route("/ai_test_gen/api/sample")
def sample():
    ...


@app.route("/api/parse", methods=["POST"])
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

    # Return summary for preview table
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
        "raw": content,  # passed back so /api/generate doesn't need re-upload
    })


@app.route("/api/generate", methods=["POST"])
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
    include_capl     = options.get("capl", True)
    include_vtp      = options.get("vtp", True)
    include_vtestunit = options.get("vtestunit", True)

    log = []

    # 1. Generate CAPL modules
    capl_modules = {}
    if include_capl:
        capl_modules = generate_capl_modules(req_file)
        for fname in capl_modules:
            log.append(f"Generated {fname}")

    # 2. Generate vTestStudio project
    vtp_content = ""
    if include_vtp:
        vtp_content = generate_vts_project(req_file, capl_modules)
        log.append(f"Generated {req_file.project}.vtp")

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
            log.append(f"Generated {fname}")

    # 4. Pack into zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in capl_modules.items():
            zf.writestr(fname, content)
        if vtp_content:
            zf.writestr(f"{req_file.project}.vtp", vtp_content)
        for fname, content in vtestunit_files.items():
            zf.writestr(fname, content)
        # Include original requirements
        zf.writestr("requirements.json", data["raw"])

    zip_buffer.seek(0)
    log.append("Zip ready for download")

    # Also return file listing for the UI
    files = (
        list(capl_modules.keys())
        + ([f"{req_file.project}.vtp"] if vtp_content else [])
        + list(vtestunit_files.keys())
    )

    # Store zip temporarily for download
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
def sample():
    """Return the sample requirements JSON so users can see the expected format."""
    sample_path = Path("sample/requirements.json")
    if sample_path.exists():
        return send_file(sample_path, mimetype="application/json")
    return jsonify({"error": "Sample not found"}), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8181)

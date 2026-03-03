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
from app.generator.pytest_generator import generate_pytest_modules, generate_conftest

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["APPLICATION_ROOT"] = "/ai_test_gen"
BASE_URL = "/ai_test_gen"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/ai_test_gen/")
def index():
    return render_template("index.html", base_url=BASE_URL)


@app.route("/api/parse", methods=["POST"])
@app.route("/ai_test_gen/api/parse", methods=["POST"])
def parse_requirements():
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
    data = request.get_json()
    if not data or "raw" not in data:
        return jsonify({"error": "Missing requirements data"}), 400

    try:
        req_file = parse_json_string(data["raw"])
    except Exception as e:
        return jsonify({"error": f"Parse error: {str(e)}"}), 422

    options        = data.get("options", {})
    include_capl      = options.get("capl", True)
    include_vtp       = options.get("vtp", True)
    include_vtestunit = options.get("vtestunit", True)
    include_pytest    = options.get("pytest", False)

    log       = []
    all_files = {}

    # 1. CAPL modules
    capl_modules = {}
    if include_capl:
        capl_modules = generate_capl_modules(req_file)
        for fname in capl_modules:
            log.append(f"✓ Generated {fname}")
        all_files.update(capl_modules)

    # 2. vTestStudio project
    if include_vtp:
        vtp_content = generate_vts_project(req_file, capl_modules)
        vtp_name    = f"{req_file.project}.vtp"
        all_files[vtp_name] = vtp_content
        log.append(f"✓ Generated {vtp_name}")

    # 3. vtestunit files
    if include_vtestunit:
        from collections import defaultdict
        groups = defaultdict(list)
        for r in req_file.requirements:
            groups[r.type.value].append(r)
        for rtype, reqs in groups.items():
            fname = f"{req_file.project}_{rtype.capitalize()}.vtestunit"
            all_files[fname] = generate_vtestunit(req_file, fname, reqs)
            log.append(f"✓ Generated {fname}")

    # 4. pytest modules
    if include_pytest:
        pytest_modules = generate_pytest_modules(req_file)
        for fname in pytest_modules:
            log.append(f"✓ Generated {fname}")
        all_files.update(pytest_modules)
        all_files["conftest.py"] = generate_conftest(req_file)
        log.append("✓ Generated conftest.py")

    # 5. Pack zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in all_files.items():
            zf.writestr(fname, content)
        zf.writestr("requirements.json", data["raw"])

    zip_buffer.seek(0)
    log.append("→ Zip ready for download")

    zip_path = OUTPUT_DIR / f"{req_file.project}_output.zip"
    with open(zip_path, "wb") as out:
        out.write(zip_buffer.getvalue())

    return jsonify({
        "success": True,
        "files":   list(all_files.keys()),
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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8181)

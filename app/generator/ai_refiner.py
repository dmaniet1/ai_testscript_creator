import json
import os
import re
import shutil
import subprocess
from typing import Tuple
from urllib import request
from urllib.error import HTTPError, URLError

from ..requirements_parser.models import RequirementsFile


DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_\-]*\n", "", cleaned)
    cleaned = re.sub(r"\n```$", "", cleaned)
    return cleaned.strip()


def _to_requirement_context(req_file: RequirementsFile, req_type: str) -> str:
    reqs = [r for r in req_file.requirements if r.type.value == req_type]
    context = [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "acceptance_criteria": r.acceptance_criteria,
            "parameters": r.parameters,
        }
        for r in reqs
    ]
    return json.dumps(context, indent=2, ensure_ascii=False)


def _infer_req_type(filename: str) -> str:
    lowered = filename.lower()
    if "timing" in lowered:
        return "timing"
    if "signal" in lowered:
        return "signal"
    if "response" in lowered:
        return "response"
    if "presence" in lowered:
        return "presence"
    return ""


def _build_user_prompt(req_file: RequirementsFile, filename: str, content: str) -> str:
    req_type = _infer_req_type(filename)
    req_context = _to_requirement_context(req_file, req_type) if req_type else "[]"
    return (
        f"Project: {req_file.project}\n"
        f"Module file: {filename}\n\n"
        "Requirements context (JSON):\n"
        f"{req_context}\n\n"
        "Current CAPL module:\n"
        f"{content}\n\n"
        "Tasks:\n"
        "1) Improve naming clarity and step reporting.\n"
        "2) Add robust pass/fail branches and boundary checks where applicable.\n"
        "3) Keep syntax valid for CAPL test modules.\n"
        "4) Do not invent new requirement IDs.\n"
        "Return only the improved CAPL module text."
    )


def _refine_with_openai_compatible(req_file: RequirementsFile, modules: dict[str, str]) -> Tuple[dict[str, str], list[str]]:
    api_key = os.getenv("CAPL_AI_API_KEY", "")
    model = os.getenv("CAPL_AI_MODEL", "")
    api_url = os.getenv("CAPL_AI_API_URL", DEFAULT_API_URL)

    if not api_key or not model:
        return modules, ["⚠ AI refinement requested, but CAPL_AI_API_KEY/CAPL_AI_MODEL not set"]

    refined: dict[str, str] = {}
    log: list[str] = []

    system_prompt = (
        "You are an automotive CAPL expert for Vector CANoe/vTestStudio. "
        "Improve CAPL test module quality while preserving requirement intent. "
        "Return only CAPL code, no markdown fences or explanations."
    )

    for filename, content in modules.items():
        user_prompt = _build_user_prompt(req_file, filename, content)

        payload = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        req = request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            ai_text = body["choices"][0]["message"]["content"]
            ai_text = _strip_code_fences(ai_text)
            if ai_text:
                refined[filename] = ai_text
                log.append(f"✓ AI refined {filename}")
            else:
                refined[filename] = content
                log.append(f"⚠ AI returned empty output for {filename}; kept template output")
        except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            refined[filename] = content
            log.append(f"⚠ AI refine failed for {filename}: {str(exc)}")

    return refined, log


def _refine_with_copilot_cli(req_file: RequirementsFile, modules: dict[str, str]) -> Tuple[dict[str, str], list[str]]:
    copilot_cmd = os.getenv("CAPL_COPILOT_COMMAND", "").strip()
    if not copilot_cmd:
        if shutil.which("copilot") is not None:
            copilot_cmd = "copilot"
        elif shutil.which("gh") is not None:
            copilot_cmd = "gh"
        else:
            return modules, ["⚠ Copilot CLI provider selected, but neither `copilot` nor `gh` is installed"]

    refined: dict[str, str] = {}
    log: list[str] = []
    timeout_seconds = int(os.getenv("CAPL_COPILOT_TIMEOUT_SEC", "60"))

    if copilot_cmd == "gh":
        probe = subprocess.run(
            ["gh", "copilot", "suggest", "echo hello"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        probe_text = ((probe.stdout or "") + "\n" + (probe.stderr or "")).lower()
        if "deprecated" in probe_text or "no commands will be executed" in probe_text:
            return modules, [
                "⚠ `gh copilot suggest` is deprecated in this environment and returns no AI output.",
                "⚠ Install standalone Copilot CLI and set CAPL_COPILOT_COMMAND=copilot",
            ]

    if copilot_cmd == "copilot":
        probe = subprocess.run(
            ["copilot", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        probe_text = ((probe.stdout or "") + "\n" + (probe.stderr or "")).lower()
        if "cannot find github copilot cli" in probe_text or "installing failed" in probe_text:
            return modules, [
                "⚠ Standalone `copilot` is not initialized on this machine.",
                "⚠ Install Node.js/npm and initialize Copilot CLI, then retry",
            ]

    for filename, content in modules.items():
        prompt = (
            "You are improving a CAPL test module. Return only CAPL code, no markdown.\n\n"
            + _build_user_prompt(req_file, filename, content)
        )

        try:
            command = ["gh", "copilot", "suggest", prompt] if copilot_cmd == "gh" else ["copilot", "suggest", prompt]
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
            ai_text = _strip_code_fences((result.stdout or "").strip())
            full_text = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
            if "deprecated" in full_text or "no commands will be executed" in full_text:
                refined[filename] = content
                log.append(f"⚠ Copilot CLI deprecated path for {filename}; kept template output")
            elif result.returncode == 0 and ai_text:
                refined[filename] = ai_text
                log.append(f"✓ Copilot CLI refined {filename}")
            else:
                refined[filename] = content
                stderr = (result.stderr or "").strip()
                if stderr:
                    log.append(f"⚠ Copilot CLI failed for {filename}: {stderr}")
                else:
                    log.append(f"⚠ Copilot CLI returned empty output for {filename}; kept template output")
        except (subprocess.SubprocessError, TimeoutError) as exc:
            refined[filename] = content
            log.append(f"⚠ Copilot CLI error for {filename}: {str(exc)}")

    return refined, log


def _refine_with_simulated_ai(req_file: RequirementsFile, modules: dict[str, str]) -> Tuple[dict[str, str], list[str]]:
    """
    Deterministic local simulation mode for demos/POC.
    No external AI call is made.
    """
    refined: dict[str, str] = {}
    log: list[str] = []

    for filename, content in modules.items():
        module_text = content
        if "/*" in module_text:
            module_text = module_text.replace(
                " */\n\n",
                " * AI Simulation    : ON\n"
                " * AI Provider      : VE Botfather\n"
                " */\n\n",
                1,
            )

        if "TestStepPass(" in module_text and "TestStep(" not in module_text:
            module_text = module_text.replace(
                "TestStepPass(",
                "TestStep(\"VE_BOTFATHER_SIM\", \"VE Botfather refinement path executed\");\n  TestStepPass(",
                1,
            )

        module_text = module_text.replace("_TimingCheck", "_TimingCheck_Optimized")
        module_text = module_text.replace("_SignalRange", "_SignalRange_Optimized")
        module_text = module_text.replace("_ResponseTime", "_ResponseTime_Optimized")
        module_text = module_text.replace("_Presence", "_Presence_Optimized")

        refined[filename] = module_text
        log.append(f"✓ VE Botfather refined {filename}")

    return refined, log


def refine_capl_modules_with_ai(
    req_file: RequirementsFile,
    modules: dict[str, str],
) -> Tuple[dict[str, str], list[str]]:
    """
    Optional AI pass that refines generated CAPL modules.
        Provider options:
            - openai_api (default): OpenAI-compatible Chat Completions endpoint
            - copilot_cli (POC): gh/copilot CLI via subprocess
            - ve_botfather (POC): deterministic local refinement without external AI
    """
    enabled = os.getenv("CAPL_AI_ENABLED", "false").lower() == "true"
    provider = os.getenv("CAPL_AI_PROVIDER", "openai_api").strip().lower()

    if not enabled:
        refined, sim_log = _refine_with_simulated_ai(req_file, modules)
        return refined, ["ℹ AI provider disabled; using VE Botfather fallback"] + sim_log

    if provider == "copilot_cli":
        refined, log = _refine_with_copilot_cli(req_file, modules)
        if any("⚠" in line for line in log):
            sim_refined, sim_log = _refine_with_simulated_ai(req_file, modules)
            return sim_refined, log + ["ℹ Copilot CLI unavailable; using VE Botfather fallback"] + sim_log
        return refined, log
    if provider == "openai_api":
        refined, log = _refine_with_openai_compatible(req_file, modules)
        if any("⚠" in line for line in log):
            sim_refined, sim_log = _refine_with_simulated_ai(req_file, modules)
            return sim_refined, log + ["ℹ OpenAI API unavailable; using VE Botfather fallback"] + sim_log
        return refined, log
    if provider in {"simulated", "mock"}:
        return _refine_with_simulated_ai(req_file, modules)

    sim_refined, sim_log = _refine_with_simulated_ai(req_file, modules)
    return sim_refined, [f"⚠ Unknown CAPL_AI_PROVIDER='{provider}'; using VE Botfather fallback"] + sim_log

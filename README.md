# CAPL-GEN · Test Case Generator

Flask web app that reads requirements from JSON and generates CAPL test scripts + vTestStudio project files.

## Quick start

```bash
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

## Docker

```bash
docker build -t capl-gen .
docker run -p 5000:5000 capl-gen
```

## Project structure

```
capl-gen/
  app.py                          # Flask app + routes
  app/
    requirements_parser/
      models.py                   # Pydantic data models
      parser.py                   # JSON parser
    generator/
      capl_generator.py           # CAPL script generator (Jinja2)
      vts_project.py              # vTestStudio XML generator
    capl_templates/
      timing.can.j2               # Cycle time test template
      signal.can.j2               # Signal range test template
      response.can.j2             # Request/response test template
      presence.can.j2             # Message presence test template
  templates/
    index.html                    # Flask HTML template (full UI)
  sample/
    requirements.json             # Example requirements file
  output/                         # Generated zips land here
```

## Requirement types

| type | What it tests | Key parameters |
|------|--------------|----------------|
| `timing` | CAN message cycle time | `message_id`, `cycle_time_ms`, `tolerance_ms` |
| `signal` | Signal min/max range | `signal_name`, `min_value`, `max_value`, `unit` |
| `response` | Request/response latency | `request_id`, `response_id`, `max_response_ms` |
| `presence` | Message exists on bus | `message_id`, `timeout_ms` |

## Adding SystemWeaver (v2)

Replace the file upload with a `sw_client.py` that fetches items via REST
and returns the same `RequirementsFile` Pydantic model — nothing else changes.

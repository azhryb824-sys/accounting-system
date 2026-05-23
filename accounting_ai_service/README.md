# Accounting AI Service

This folder contains the source code for the private accounting AI service used by the Django system.

Run locally:

```powershell
cd D:\accounting-ai
.\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8010
```

The Django app connects to:

```text
http://127.0.0.1:8010/ask
```

or to the URL configured in `PRIVATE_ACCOUNTING_AI_URL`.

Model weights and virtual environments are not committed here. Keep trained model files under the local service directory, for example:

```text
D:\accounting-ai\models\my_model
```

## Photographed invoice OCR

The invoice image reader uses only free open-source components that can be used commercially:

- Tesseract OCR, Apache 2.0
- pytesseract 0.3.1+, Apache 2.0
- Pillow, HPND-style open-source license

For real photographed invoice reading on Render, run this service as Docker because Tesseract is a system binary, not just a Python package.

Recommended Render settings for the AI service:

- Root directory: `accounting_ai_service`
- Runtime: Docker
- Dockerfile path: `Dockerfile`
- Start command: leave empty

The Dockerfile installs Tesseract with Arabic and English language packs, then starts:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

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

## Strong recommended setup

For a noticeably stronger assistant, run this service with Ollama and a modern open instruction model. This keeps the system free of paid API keys and allows commercial use when you choose a permissive model license.

Recommended models:

- Best balance: `qwen2.5:7b-instruct`
- Stronger when hardware allows: `qwen2.5:14b-instruct`
- Lighter/faster: `qwen2.5:3b-instruct`

PowerShell example:

```powershell
ollama pull qwen2.5:7b-instruct
$env:ACCOUNTING_AI_BACKEND="ollama"
$env:OLLAMA_MODEL="qwen2.5:7b-instruct"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
.\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8010
```

Then check:

```text
http://127.0.0.1:8010/health
```

The Django app will still use its own accounting-data layer for exact invoices, inventory, reports, permissions, and approval flows. The open model improves conversation depth, Arabic wording, reasoning, and general knowledge; the Django layer protects financial accuracy.

Model weights and virtual environments are not committed here. Keep trained model files under the local service directory, for example:

```text
D:\accounting-ai\models\my_model
```

You can also point the service to a stronger local instruction model with:

```powershell
$env:ACCOUNTING_AI_MODEL_PATH="D:\accounting-ai\models\qwen2.5-7b-instruct"
```

For a ChatGPT-like local experience without paid APIs, use a commercially usable open model that your server can run. Good practical choices are Qwen2.5 Instruct or Mistral Instruct families. The stronger the model and hardware, the better the conversation quality; the Django app still protects weak answers with accounting-data fallbacks.

## Arabic voice quality

Browser voices depend on the user's device and operating system. For the best Arabic male voice without paid services:

- Install high-quality Arabic voices on Windows or the browser device when available.
- Use a modern browser with Arabic `speechSynthesis` support.
- Keep responses short and sentence-based for clearer pronunciation.
- For future server-side TTS, prefer commercially usable open TTS models such as Apache/MIT licensed Arabic TTS projects, but verify each voice/model license before deployment.

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
- Start command: leave empty when Runtime is Docker

If you deploy it as a native Python web service instead of Docker, use this Start Command:

```bash
sh render-start.sh
```

or:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Do not run `python manage.py ...` inside this AI service. It is FastAPI, not Django.

The Dockerfile installs Tesseract with Arabic and English language packs, then starts:

```bash
uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}
```

## Strict private local model mode

If you do not want to depend on any external hosted model, use only your own trained/exported model files:

```text
ACCOUNTING_AI_BACKEND=local_model
REQUIRE_LOCAL_MODEL=true
ACCOUNTING_AI_MODEL_PATH=/app/models/my_model
```

The directory must contain a Hugging Face compatible model and tokenizer, for example:

```text
accounting_ai_service/models/my_model/config.json
accounting_ai_service/models/my_model/tokenizer.json
accounting_ai_service/models/my_model/model.safetensors
```

With `REQUIRE_LOCAL_MODEL=true`, the service fails loudly if the model is missing. It will not silently use OpenRouter, OpenAI, Ollama, or the built-in local fallback as the main AI.

Render free/small instances may not have enough RAM for a large model. In that case use a smaller exported model, a paid Render instance with enough RAM, or deploy the AI service on a server with CPU/RAM/GPU suitable for the model.

## Optional hosted model mode

If you later decide to use a hosted OpenAI-compatible provider, configure:

```text
ACCOUNTING_AI_BACKEND=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=https://openrouter.ai/api/v1
OPENAI_COMPATIBLE_MODEL=<provider/model-name>
OPENAI_COMPATIBLE_API_KEY=<your-api-key>
REQUIRE_HOSTED_AI=true
```

Any provider that supports `POST /chat/completions` can be used, such as OpenRouter, Groq, Together, or OpenAI. Keep the API key in Render environment variables only; do not commit it.

With `REQUIRE_HOSTED_AI=true`, the service will fail loudly if the hosted provider is not configured or does not answer. This prevents accidental silent fallback to the local knowledge layer.

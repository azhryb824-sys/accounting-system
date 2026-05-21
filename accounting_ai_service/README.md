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

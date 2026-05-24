# AI platform upgrade guide

This system should use a layered AI design:

1. Exact accounting layer in Django
   - Reads invoices, products, customers, suppliers, inventory, payroll, branches, permissions, and approvals.
   - Must remain the final authority for company numbers.

2. Modern open model layer
   - Recommended free/commercial-friendly runtime: Ollama.
   - Recommended models:
     - Fast: `qwen2.5:3b-instruct`
     - Balanced: `qwen2.5:7b-instruct`
     - Stronger: `qwen2.5:14b-instruct`
   - Run:
     ```powershell
     ollama pull qwen2.5:7b-instruct
     $env:ACCOUNTING_AI_BACKEND="ollama"
     $env:OLLAMA_MODEL="qwen2.5:7b-instruct"
     cd accounting_ai_service
     ..\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8010
     ```

3. Massive knowledge layer
   - Update local knowledge with:
     ```powershell
     python manage.py update_ai_knowledge --limit 2
     ```
   - Add extra topics:
     ```powershell
     python manage.py update_ai_knowledge --topic "Saudi retail market" --topic "restaurant accounting" --limit 2
     ```
   - Current free/public sources:
     - ZATCA official regulation links
     - Wikipedia summaries
     - Wikidata public facts
     - OpenAlex open research metadata

4. Arabic voice layer
   - Browser voices depend on the device. Use HTTPS or localhost for microphone/camera/screen sharing.
   - For best Arabic speech, install high-quality Arabic voices on Windows/Android/iOS.
   - Keep AI answers short and sentence-based for voice mode.
   - Server-side TTS can be added later with a verified commercial-use Arabic TTS model.

5. Product quality rules
   - Never invent company numbers.
   - Ask for approval before creating or changing accounting data.
   - Use official sources for Saudi tax and e-invoicing questions.
   - Do not give religious rulings; refer the user to qualified scholars.
   - Use web/knowledge sources for general questions when local data is insufficient.


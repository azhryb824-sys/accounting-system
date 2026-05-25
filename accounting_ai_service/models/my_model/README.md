# Private model placeholder

Place a Hugging Face compatible causal language model here.

Expected examples:

```text
config.json
generation_config.json
tokenizer.json
tokenizer_config.json
special_tokens_map.json
model.safetensors
```

or sharded weights:

```text
model-00001-of-00002.safetensors
model-00002-of-00002.safetensors
model.safetensors.index.json
```

This directory is the default value used by the AI service:

```text
ACCOUNTING_AI_MODEL_PATH=/app/models/my_model
```

Do not commit real model weights to the public repository.


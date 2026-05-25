from pathlib import Path

from inference import MODEL_PATH, get_model


def main():
    path = Path(MODEL_PATH)
    print(f"Model path: {path}")
    print(f"Path exists: {path.exists()}")
    required_any = [
        "model.safetensors",
        "pytorch_model.bin",
        "model.safetensors.index.json",
        "pytorch_model.bin.index.json",
    ]
    required_config = ["config.json"]
    missing_config = [name for name in required_config if not (path / name).exists()]
    has_weights = any((path / name).exists() for name in required_any) or bool(list(path.glob("*.safetensors")))
    print(f"Has config: {not missing_config}")
    print(f"Has weights: {has_weights}")
    model = get_model()
    loaded = bool(model.model is not None and model.tokenizer is not None)
    print(f"Transformers loaded: {loaded}")
    if not loaded:
        raise SystemExit("Model is not ready. Add real Hugging Face model files to models/my_model.")


if __name__ == "__main__":
    main()

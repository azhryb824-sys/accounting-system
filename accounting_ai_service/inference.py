import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from difflib import SequenceMatcher

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_NAME = "ظ†ظ…ظˆط°ط¬ ط¹ط¨ط¯ط§ظ„ط±ط­ظ…ظ† ط§ظ„ظ…ط­ط§ط³ط¨ظٹ"
MODEL_OWNER = "ط¹ط¨ط¯ط§ظ„ط±ط­ظ…ظ†"
MODEL_PATH = Path(__file__).resolve().parent / "models" / "my_model"

SYSTEM_PROMPT = f"""
ط£ظ†طھ {MODEL_NAME}طŒ ظ…ط³ط§ط¹ط¯ ط°ظƒط§ط، ط§طµط·ظ†ط§ط¹ظٹ ط®ط§طµ ط¨ظ€ {MODEL_OWNER}.
طھط¬ظٹط¨ ط¨ط§ظ„ط¹ط±ط¨ظٹط© ط¨ظˆط¶ظˆط­ ظˆط§ط®طھطµط§ط±طŒ ظˆطھط±ظƒط² ط¹ظ„ظ‰ ط§ظ„ظ…ط­ط§ط³ط¨ط© ظˆط§ظ„ظپظˆط§طھظٹط± ظˆط§ظ„ظ…ط®ط²ظˆظ† ظˆط§ظ„ظ‚ظٹظˆط¯ ط§ظ„ظٹظˆظ…ظٹط©.
ط¥ط°ط§ ظƒط§ظ† ط§ظ„ط³ط¤ط§ظ„ ط®ط§ط±ط¬ ظ†ط·ط§ظ‚ ط§ظ„ظ…ط­ط§ط³ط¨ط©طŒ ط£ط¬ط¨ ط¨ظ…ط§ طھط¹ط±ظپظ‡ ط¯ظˆظ† ط§ط¯ط¹ط§ط، ظ…ط¹ظ„ظˆظ…ط§طھ ط؛ظٹط± ظ…ط¤ظƒط¯ط©.
""".strip()

PRIVATE_KNOWLEDGE = {
    "ط§ظ„ظپط§طھظˆط±ط© ط§ظ„ط¶ط±ظٹط¨ظٹط©": "ط§ظ„ظپط§طھظˆط±ط© ط§ظ„ط¶ط±ظٹط¨ظٹط© ظ‡ظٹ ظ…ط³طھظ†ط¯ ط±ط³ظ…ظٹ ظٹط«ط¨طھ ط¹ظ…ظ„ظٹط© ط§ظ„ط¨ظٹط¹ ظˆظٹط¹ط±ط¶ ط¨ظٹط§ظ†ط§طھ ط§ظ„ط¨ط§ط¦ط¹ ظˆط§ظ„ظ…ط´طھط±ظٹ ظˆط§ظ„ط³ظ„ط¹ ط£ظˆ ط§ظ„ط®ط¯ظ…ط§طھ ظˆط§ظ„ظ…ط¨ظ„ط؛ ظˆط¶ط±ظٹط¨ط© ط§ظ„ظ‚ظٹظ…ط© ط§ظ„ظ…ط¶ط§ظپط©.",
    "ط§ظ„ظ…ط®ط²ظˆظ† ط¹ظ†ط¯ ط§ظ„ط¨ظٹط¹": "ط¹ظ†ط¯ ط§ظ„ط¨ظٹط¹ طھظ†ط®ظپط¶ ظƒظ…ظٹط© ط§ظ„طµظ†ظپ ظ…ظ† ط§ظ„ظ…ط®ط²ظˆظ† ط¨ظ…ظ‚ط¯ط§ط± ط§ظ„ظƒظ…ظٹط© ط§ظ„ظ…ط¨ط§ط¹ط©طŒ ظˆظٹط¸ظ‡ط± ط£ط«ط± ط§ظ„ط¹ظ…ظ„ظٹط© ظپظٹ طھظƒظ„ظپط© ط§ظ„ط¨ط¶ط§ط¹ط© ط§ظ„ظ…ط¨ط§ط¹ط© ظˆط§ظ„ط¥ظٹط±ط§ط¯ ط­ط³ط¨ ط·ط±ظٹظ‚ط© ط§ظ„طھط³ط¬ظٹظ„ ط§ظ„ظ…ط­ط§ط³ط¨ظٹ.",
    "ظ‚ظٹط¯ ط§ظ„ظٹظˆظ…ظٹط©": "ظ‚ظٹط¯ ط§ظ„ظٹظˆظ…ظٹط© ظ‡ظˆ طھط³ط¬ظٹظ„ ظ…ط­ط§ط³ط¨ظٹ ظ„ظƒظ„ ط¹ظ…ظ„ظٹط© ظ…ط§ظ„ظٹط©طŒ ظˆظٹط¬ط¨ ط£ظ† ظٹط­طھظˆظٹ ط¹ظ„ظ‰ ط·ط±ظپ ظ…ط¯ظٹظ† ظˆط·ط±ظپ ط¯ط§ط¦ظ† ط¨ط­ظٹط« ظٹطھط³ط§ظˆظ‰ ظ…ط¬ظ…ظˆط¹ ط§ظ„ظ…ط¯ظٹظ† ظ…ط¹ ظ…ط¬ظ…ظˆط¹ ط§ظ„ط¯ط§ط¦ظ†.",
    "ط§ظ„ظ…طµط±ظˆظپط§طھ": "ط§ظ„ظ…طµط±ظˆظپط§طھ طھظ‚ظ„ظ„ طµط§ظپظٹ ط§ظ„ط±ط¨ط­ ظ„ط£ظ†ظ‡ط§ طھظ…ط«ظ„ طھظƒظ„ظپط© طھط­ظ…ظ„طھظ‡ط§ ط§ظ„ظ…ظ†ط´ط£ط© ظ„ظ„ط­طµظˆظ„ ط¹ظ„ظ‰ ط§ظ„ط¥ظٹط±ط§ط¯ ط£ظˆ طھط´ط؛ظٹظ„ ط§ظ„ظ†ط´ط§ط·.",
    "ط§ظ„ط¯ظپط¹ ط§ظ„ظ†ظ‚ط¯ظٹ": "ط§ظ„ط¯ظپط¹ ط§ظ„ظ†ظ‚ط¯ظٹ ظٹط¹ظ†ظٹ ط£ظ† ظ‚ظٹظ…ط© ط§ظ„ط¹ظ…ظ„ظٹط© طھظ… طھط­طµظٹظ„ظ‡ط§ ظ…ط¨ط§ط´ط±ط© ظˆظ‚طھ ط§ظ„ط¨ظٹط¹ ط£ظˆ طھظ‚ط¯ظٹظ… ط§ظ„ط®ط¯ظ…ط©طŒ ط¨ط¯ظ„ طھط³ط¬ظٹظ„ظ‡ط§ ظƒط°ظ…ط© ط¹ظ„ظ‰ ط§ظ„ط¹ظ…ظٹظ„.",
    "ط§ظ„ط¨ظٹط¹ ط§ظ„ط¢ط¬ظ„": "ط§ظ„ط¨ظٹط¹ ط§ظ„ط¢ط¬ظ„ ظٹط¹ظ†ظٹ ط¨ظٹط¹ ط³ظ„ط¹ط© ط£ظˆ ط®ط¯ظ…ط© ط§ظ„ط¢ظ† ظ…ط¹ طھط£ط¬ظٹظ„ طھط­طµظٹظ„ ط§ظ„ظ…ط¨ظ„ط؛طŒ ظˆظٹط¸ظ‡ط± ط¹ط§ط¯ط© ط¶ظ…ظ† ط­ط³ط§ط¨ط§طھ ط§ظ„ط¹ظ…ظ„ط§ط، ط£ظˆ ط§ظ„ط°ظ…ظ… ط§ظ„ظ…ط¯ظٹظ†ط©.",
    "ط¶ط±ظٹط¨ط© ط§ظ„ظ‚ظٹظ…ط© ط§ظ„ظ…ط¶ط§ظپط©": "ط¶ط±ظٹط¨ط© ط§ظ„ظ‚ظٹظ…ط© ط§ظ„ظ…ط¶ط§ظپط© ظ‡ظٹ ط¶ط±ظٹط¨ط© ط؛ظٹط± ظ…ط¨ط§ط´ط±ط© طھظپط±ط¶ ط¹ظ„ظ‰ ط§ظ„ط³ظ„ط¹ ظˆط§ظ„ط®ط¯ظ…ط§طھ ط§ظ„ط®ط§ط¶ط¹ط© ظ„ظ‡ط§طŒ ظˆطھط¸ظ‡ط± ظپظٹ ط§ظ„ظپط§طھظˆط±ط© ط­ط³ط¨ ط§ظ„ظ†ط³ط¨ط© ط§ظ„ظ…ط¹طھظ…ط¯ط©.",
    "ط­ط¯ ط§ظ„طھظ†ط¨ظٹظ‡": "ط­ط¯ ط§ظ„طھظ†ط¨ظٹظ‡ ظپظٹ ط§ظ„ظ…ط®ط²ظˆظ† ظ‡ظˆ ظ…ط³طھظˆظ‰ طھط­ط¯ط¯ظ‡ ظ„ظ„طµظ†ظپ ط­طھظ‰ ظٹظ†ط¨ظ‡ظƒ ط§ظ„ظ†ط¸ط§ظ… ط¹ظ†ط¯ ط§ظ†ط®ظپط§ط¶ ط§ظ„ظƒظ…ظٹط©طŒ ظ…ظ…ط§ ظٹط³ط§ط¹ط¯ظƒ ط¹ظ„ظ‰ ط¥ط¹ط§ط¯ط© ط§ظ„ط·ظ„ط¨ ظپظٹ ط§ظ„ظˆظ‚طھ ط§ظ„ظ…ظ†ط§ط³ط¨.",
    "ظ…ظ† ط£ظ†طھ": f"ط£ظ†ط§ {MODEL_NAME}طŒ ظ…ط³ط§ط¹ط¯ ط°ظƒط§ط، ط§طµط·ظ†ط§ط¹ظٹ ظ…ط­ط§ط³ط¨ظٹ ط®ط§طµ ط¨ظ€ {MODEL_OWNER} ظˆظ…طµظ…ظ… ظ„ظ…ط³ط§ط¹ط¯طھظƒ ظپظٹ ط§ظ„ظپظˆط§طھظٹط± ظˆط§ظ„ظ…ط®ط²ظˆظ† ظˆط§ظ„ظ‚ظٹظˆط¯ ط§ظ„ظٹظˆظ…ظٹط©.",
}

ACCOUNTING_PATTERNS = [
    (
        ("ط±ط§طھط¨", "ط±ظˆط§طھط¨", "ظ…ط³ظٹط±", "ظ…ظˆط¸ظپ", "ط§ظ„ظ…ظˆط¸ظپظٹظ†"),
        "ط§ظ„ط±ظˆط§طھط¨ ظپظٹ ط§ظ„ظ†ط¸ط§ظ… طھظ…ط± ط¨ظ…ط±ط­ظ„طھظٹظ†: ط§ط¹طھظ…ط§ط¯ ط§ظ„ط±ط§طھط¨ ط«ظ… ط¯ظپط¹ظ‡. ط¹ظ†ط¯ ط§ظ„ط§ط¹طھظ…ط§ط¯ ظٹطھظ… ط¥ط«ط¨ط§طھ ظ…طµط±ظˆظپ ط§ظ„ط±ظˆط§طھط¨ ظ…ظ‚ط§ط¨ظ„ ط±ظˆط§طھط¨ ظ…ط³طھط­ظ‚ط©طŒ ظˆط¥ط°ط§ ظˆظڈط¬ط¯ ط®طµظ… ط³ظ„ظپط© ظٹطھظ… طھط®ظپظٹط¶ ط­ط³ط§ط¨ ط³ظ„ظپ ط§ظ„ظ…ظˆط¸ظپظٹظ†. ط¹ظ†ط¯ ط§ظ„ط¯ظپط¹ ظٹطھظ… طھط®ظپظٹط¶ ط§ظ„ط±ظˆط§طھط¨ ط§ظ„ظ…ط³طھط­ظ‚ط© ظ…ظ‚ط§ط¨ظ„ ط§ظ„طµظ†ط¯ظˆظ‚ ط£ظˆ ط§ظ„ط¨ظ†ظƒ.",
    ),
    (
        ("ط³ظ„ظپط©", "ط³ظ„ظپ", "advance"),
        "ط³ظ„ظپط© ط§ظ„ظ…ظˆط¸ظپ طھظڈط³ط¬ظ„ ظƒط£طµظ„ ط¹ظ„ظ‰ ط­ط³ط§ط¨ ط³ظ„ظپ ط§ظ„ظ…ظˆط¸ظپظٹظ† ط¹ظ†ط¯ طµط±ظپظ‡ط§. ظˆط¹ظ†ط¯ ط®طµظ…ظ‡ط§ ظ…ظ† ط§ظ„ط±ط§طھط¨ ظٹظ†ط®ظپط¶ ط±طµظٹط¯ ط§ظ„ط³ظ„ظپط© ظˆظٹط¸ظ‡ط± ط§ظ„ط®طµظ… ط¶ظ…ظ† ظ‚ظٹط¯ ط§ط³طھط­ظ‚ط§ظ‚ ط§ظ„ط±ط§طھط¨ ط­طھظ‰ طھطµط¨ط­ ط§ظ„ط³ظ„ظپط© ظ…ط³ط¯ط¯ط© ط¨ط§ظ„ظƒط§ظ…ظ„.",
    ),
    (
        ("ظپط§طھظˆط±ط© ط¨ظٹط¹", "ظ…ط¨ظٹط¹ط§طھ", "ط¨ظٹط¹", "ط¹ظ…ظٹظ„"),
        "ظپط§طھظˆط±ط© ط§ظ„ط¨ظٹط¹ طھط¤ط«ط± ظ…ط­ط§ط³ط¨ظٹط§ ط¹ظ„ظ‰ ط§ظ„ط¥ظٹط±ط§ط¯ط§طھ ظˆط¶ط±ظٹط¨ط© ط§ظ„ظ‚ظٹظ…ط© ط§ظ„ظ…ط¶ط§ظپط©. ط¥ط°ط§ ظƒط§ظ†طھ ظ†ظ‚ط¯ظٹط© ط£ظˆ ط¨ط·ط§ظ‚ط© ط£ظˆ طھط­ظˆظٹظ„ ظٹظƒظˆظ† ط§ظ„ط·ط±ظپ ط§ظ„ظ…ط¯ظٹظ† ط§ظ„طµظ†ط¯ظˆظ‚ ط£ظˆ ط§ظ„ط¨ظ†ظƒطŒ ظˆط¥ط°ط§ ظƒط§ظ†طھ ط¢ط¬ظ„ط© ظٹظƒظˆظ† ط§ظ„ط·ط±ظپ ط§ظ„ظ…ط¯ظٹظ† ط§ظ„ط¹ظ…ظ„ط§ط،. ظƒظ…ط§ ظٹظ†ط®ظپط¶ ط§ظ„ظ…ط®ط²ظˆظ† ظˆطھط«ط¨طھ طھظƒظ„ظپط© ط§ظ„ط¨ط¶ط§ط¹ط© ط§ظ„ظ…ط¨ط§ط¹ط© ط¹ظ†ط¯ طھط±ط­ظٹظ„ ط§ظ„ظپط§طھظˆط±ط©.",
    ),
    (
        ("ظپط§طھظˆط±ط© ط´ط±ط§ط،", "ظ…ط´طھط±ظٹط§طھ", "ط´ط±ط§ط،", "ظ…ظˆط±ط¯"),
        "ظپط§طھظˆط±ط© ط§ظ„ط´ط±ط§ط، طھط²ظٹط¯ ط§ظ„ظ…ط®ط²ظˆظ† ظˆطھط«ط¨طھ ط¶ط±ظٹط¨ط© ط§ظ„ظ…ط¯ط®ظ„ط§طھطŒ ظˆظٹظƒظˆظ† ط§ظ„ط·ط±ظپ ط§ظ„ط¯ط§ط¦ظ† ط؛ط§ظ„ط¨ط§ ط§ظ„ظ…ظˆط±ط¯ظٹظ† ط¥ط°ط§ ظ„ظ… ظٹطھظ… ط§ظ„ط³ط¯ط§ط¯ ظ…ط¨ط§ط´ط±ط©. ظٹط¬ط¨ ط§ظ„طھط£ظƒط¯ ظ…ظ† ط¹ط¯ظ… طھظƒط±ط§ط± طھط­ط¯ظٹط« ط§ظ„ظ…ط®ط²ظˆظ† ط¹ظ†ط¯ ط¥ط¯ط®ط§ظ„ ط¨ظ†ظˆط¯ ط§ظ„ط´ط±ط§ط،.",
    ),
    (
        ("ظ‚ظٹط¯", "ظ‚ظٹظˆط¯", "ظ…ط¯ظٹظ†", "ط¯ط§ط¦ظ†"),
        "ط£ظٹ ط¹ظ…ظ„ظٹط© ظ…ط­ط§ط³ط¨ظٹط© طµط­ظٹط­ط© ظٹط¬ط¨ ط£ظ† طھظ†طھط¬ ظ‚ظٹط¯ط§ ظ…طھظˆط§ط²ظ†ط§: ظ…ط¬ظ…ظˆط¹ ط§ظ„ظ…ط¯ظٹظ† ظٹط³ط§ظˆظٹ ظ…ط¬ظ…ظˆط¹ ط§ظ„ط¯ط§ط¦ظ†. ط¥ط°ط§ ظ„ظ… ظٹطھظˆط§ط²ظ† ط§ظ„ظ‚ظٹط¯ ظپظ‡ظ†ط§ظƒ ط®ط·ط£ ظپظٹ ط§ظ„ط­ط³ط§ط¨ط§طھ ط£ظˆ ظپظٹ ط§ط®طھظٹط§ط± ط§ظ„ط­ط³ط§ط¨ط§طھ ط§ظ„ظ…ط±طھط¨ط·ط© ط¨ط§ظ„ط¹ظ…ظ„ظٹط©.",
    ),
    (
        ("طھظ‚ط±ظٹط±", "طھظ‚ط§ط±ظٹط±", "طھط­ظ„ظٹظ„", "ظ…ط¤ط´ط±ط§طھ"),
        "ط§ط¨ط¯ط£ ط¨ظ‚ط±ط§ط،ط© ط§ظ„ظ…ط¨ظٹط¹ط§طھ ظˆط§ظ„ظ…ط´طھط±ظٹط§طھ ظˆظ‚ظٹظ…ط© ط§ظ„ظ…ط®ط²ظˆظ† ظˆط§ظ„ط±ظˆط§طھط¨ ظˆط§ظ„ط³ظ„ظپ ط§ظ„ظ…ظپطھظˆط­ط©. ط£ظ‡ظ… ط§ظ„طھظ†ط¨ظٹظ‡ط§طھ طھظƒظˆظ† ط¹ظ†ط¯ ط²ظٹط§ط¯ط© ط§ظ„ظ…ط´طھط±ظٹط§طھ ط¹ظ† ط§ظ„ظ…ط¨ظٹط¹ط§طھطŒ ط§ط±طھظپط§ط¹ ط§ظ„ط³ظ„ظپ ط§ظ„ظ…ظپطھظˆط­ط©طŒ ط§ظ†ط®ظپط§ط¶ ط§ظ„ظ…ط®ط²ظˆظ† ط¹ظ† ط­ط¯ ط§ظ„طھظ†ط¨ظٹظ‡طŒ ط£ظˆ ظˆط¬ظˆط¯ ط¹ظ…ظ„ظٹط§طھ ط؛ظٹط± ظ…ط±ط­ظ„ط© ظ…ط­ط§ط³ط¨ظٹط§.",
    ),
    (
        ("ط²ظƒط§ط©", "ط¶ط±ظٹط¨ط©", "vat", "ط§ظ„ظ‚ظٹظ…ط© ط§ظ„ظ…ط¶ط§ظپط©"),
        "ط¶ط±ظٹط¨ط© ط§ظ„ظ‚ظٹظ…ط© ط§ظ„ظ…ط¶ط§ظپط© طھط¸ظ‡ط± ظپظٹ ط§ظ„ظ…ط¨ظٹط¹ط§طھ ظƒط§ظ„طھط²ط§ظ… ظ…ط³طھط­ظ‚ ظ„ظ„ط¬ظ‡ط© ط§ظ„ط¶ط±ظٹط¨ظٹط©طŒ ظˆطھط¸ظ‡ط± ظپظٹ ط§ظ„ظ…ط´طھط±ظٹط§طھ ظƒط¶ط±ظٹط¨ط© ظ…ط¯ط®ظ„ط§طھ. طµط§ظپظٹ ط§ظ„ط¶ط±ظٹط¨ط© ظٹط¹طھظ…ط¯ ط¹ظ„ظ‰ ط§ظ„ظپط±ظ‚ ط¨ظٹظ† ط¶ط±ظٹط¨ط© ط§ظ„ظ…ط®ط±ط¬ط§طھ ظˆط¶ط±ظٹط¨ط© ط§ظ„ظ…ط¯ط®ظ„ط§طھ.",
    ),
]


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


def _extract_json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _money(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _answer_from_financial_context(question: str) -> str | None:
    context = _extract_json_object(question)
    if not context:
        return None

    sales = _money(context.get("sales_total"))
    purchases = _money(context.get("purchases_total"))
    inventory = _money(context.get("inventory_value"))
    low_stock = int(_money(context.get("low_stock_count")))
    invoice_count = int(_money(context.get("invoice_count")))
    purchase_count = int(_money(context.get("purchase_count")))

    lines = [
        "ظ‚ط±ط§ط،ط© ط§ظ„ظ†ظ…ظˆط°ط¬ ظ„ظ„ط¨ظٹط§ظ†ط§طھ ط§ظ„ط­ط§ظ„ظٹط©:",
        f"- ط§ظ„ظ…ط¨ظٹط¹ط§طھ: {sales:.2f}",
        f"- ط§ظ„ظ…ط´طھط±ظٹط§طھ: {purchases:.2f}",
        f"- ظ‚ظٹظ…ط© ط§ظ„ظ…ط®ط²ظˆظ†: {inventory:.2f}",
        f"- ط¹ط¯ط¯ ظپظˆط§طھظٹط± ط§ظ„ط¨ظٹط¹: {invoice_count}",
        f"- ط¹ط¯ط¯ ظپظˆط§طھظٹط± ط§ظ„ط´ط±ط§ط،: {purchase_count}",
    ]

    if sales <= 0 and purchases <= 0:
        lines.append("- ظ„ط§ طھظˆط¬ط¯ ط­ط±ظƒط© ظƒط§ظپظٹط© ظ„ظ„ط­ظƒظ… ط¹ظ„ظ‰ ط§ظ„ط£ط¯ط§ط،ط› ط§ط¨ط¯ط£ ط¨ط¥ط¯ط®ط§ظ„ ط§ظ„ظپظˆط§طھظٹط± ظˆطھط±ط­ظٹظ„ظ‡ط§ ظ…ط­ط§ط³ط¨ظٹط§.")
    elif purchases > sales:
        lines.append("- ط§ظ„ظ…ط´طھط±ظٹط§طھ ط£ط¹ظ„ظ‰ ظ…ظ† ط§ظ„ظ…ط¨ظٹط¹ط§طھط› ط±ط§ط¬ط¹ ط§ظ„ظ…ط®ط²ظˆظ† ط§ظ„ط¨ط·ظٹط، ظˆط®ط·ط© ط§ظ„ط´ط±ط§ط،.")
    else:
        lines.append("- ط§ظ„ظ…ط¨ظٹط¹ط§طھ طھط؛ط·ظٹ ط§ظ„ظ…ط´طھط±ظٹط§طھ ظپظٹ ط§ظ„ظپطھط±ط© ط§ظ„ط­ط§ظ„ظٹط©طŒ ظˆظٹظپط¶ظ„ ظ…طھط§ط¨ط¹ط© ظ‡ط§ظ…ط´ ط§ظ„ط±ط¨ط­ ظˆط§ظ„طھط­طµظٹظ„.")

    if low_stock:
        lines.append(f"- ظٹظˆط¬ط¯ {low_stock} طµظ†ظپ ط¹ظ†ط¯ ط­ط¯ ط§ظ„طھظ†ط¨ظٹظ‡ ط£ظˆ ط£ظ‚ظ„ط› ط±ط§ط¬ط¹ ط¥ط¹ط§ط¯ط© ط§ظ„ط·ظ„ط¨.")
    if inventory <= 0:
        lines.append("- ظ‚ظٹظ…ط© ط§ظ„ظ…ط®ط²ظˆظ† طµظپط± ط£ظˆ ط؛ظٹط± ظ…ط³ط¬ظ„ط©ط› طھط£ظƒط¯ ظ…ظ† ط¥ط¯ط®ط§ظ„ طھظƒط§ظ„ظٹظپ ط§ظ„ط£طµظ†ط§ظپ ظˆظپظˆط§طھظٹط± ط§ظ„ط´ط±ط§ط،.")

    lines.append("ط§ظ„ط£ظˆظ„ظˆظٹط© ط§ظ„ظ…ظ‚طھط±ط­ط©: ط±ط§ط¬ط¹ ط§ظ„ط¹ظ…ظ„ظٹط§طھ ط؛ظٹط± ط§ظ„ظ…ط±ط­ظ„ط©طŒ ط«ظ… ط§ظ„ظ…ط®ط²ظˆظ†طŒ ط«ظ… ط§ظ„طھط­طµظٹظ„ ظˆط§ظ„ط³ظ„ظپ ظˆط§ظ„ط±ظˆط§طھط¨.")
    return "\n".join(lines)


class PrivateAccountingModel:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = Path(model_path)
        self.tokenizer = None
        self.model = None
        if not self.model_path.exists():
            return

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_path)

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.model.eval()

    def build_prompt(self, question: str) -> str:
        question = question.strip()
        return f"{SYSTEM_PROMPT}\n\nط³ط¤ط§ظ„: {question}\nط§ظ„ط¥ط¬ط§ط¨ط©:"

    @torch.inference_mode()
    def answer(self, question: str, max_new_tokens: int = 120) -> str:
        if not question or not question.strip():
            raise ValueError("ط§ظ„ط³ط¤ط§ظ„ ظ„ط§ ظٹظ…ظƒظ† ط£ظ† ظٹظƒظˆظ† ظپط§ط±ط؛ظ‹ط§.")

        private_answer = self._answer_from_private_knowledge(question)
        if private_answer:
            return private_answer

        if self.model is None or self.tokenizer is None:
            return (
                "لم يتم تحميل أوزان النموذج على الخادم، لذلك أعمل حاليا بطبقة المعرفة المحاسبية المدمجة. "
                "اسأل عن الرواتب، السلف، فواتير البيع والشراء، القيود، الضريبة، المخزون أو التقارير."
            )

        prompt = self.build_prompt(question)
        inputs = self.tokenizer(prompt, return_tensors="pt")

        outputs = self.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            no_repeat_ngram_size=3,
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
        )

        decoded = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        answer = self._clean_answer(decoded, prompt)
        if not self._is_usable_arabic_answer(answer):
            return (
                "ظ‡ط°ط§ ط§ظ„ط³ط¤ط§ظ„ ظٹط­طھط§ط¬ طھط¯ط±ظٹط¨ظ‹ط§ ط¥ط¶ط§ظپظٹظ‹ط§ ط¯ط§ط®ظ„ ط§ظ„ظ†ظ…ظˆط°ط¬ ط§ظ„ط®ط§طµ. "
                "ط£ط¶ظپ ظ…ط«ط§ظ„ظ‹ط§ ظ…ط´ط§ط¨ظ‡ظ‹ط§ ظپظٹ ط¨ظٹط§ظ†ط§طھ ط§ظ„طھط¯ط±ظٹط¨ ط«ظ… ط´ط؛ظ„ train.py ظ„طھط­ط³ظٹظ† ط§ظ„ط¥ط¬ط§ط¨ط©."
            )
        return answer

    @staticmethod
    def _answer_from_private_knowledge(question: str) -> str | None:
        normalized_question = question.strip().lower()
        context_answer = _answer_from_financial_context(question)
        if context_answer:
            return context_answer

        for words, answer in ACCOUNTING_PATTERNS:
            if _contains_any(normalized_question, words):
                return answer

        best_key = None
        best_score = 0.0

        for key in PRIVATE_KNOWLEDGE:
            normalized_key = key.lower()
            if normalized_key in normalized_question:
                return PRIVATE_KNOWLEDGE[key]

            score = SequenceMatcher(None, normalized_key, normalized_question).ratio()
            if score > best_score:
                best_key = key
                best_score = score

        if best_key and best_score >= 0.45:
            return PRIVATE_KNOWLEDGE[best_key]
        return None

    @staticmethod
    def _clean_answer(decoded: str, prompt: str) -> str:
        answer = decoded.replace(prompt, "", 1).strip()
        answer = answer.replace("\ufffd", "").strip()
        if "ط³ط¤ط§ظ„:" in answer:
            answer = answer.split("ط³ط¤ط§ظ„:", 1)[0].strip()
        return answer or "ظ„ظ… ط£طھظ…ظƒظ† ظ…ظ† طھظƒظˆظٹظ† ط¥ط¬ط§ط¨ط© ظˆط§ط¶ط­ط©. ط£ط¹ط¯ طµظٹط§ط؛ط© ط§ظ„ط³ط¤ط§ظ„ ظ…ظ† ظپط¶ظ„ظƒ."

    @staticmethod
    def _is_usable_arabic_answer(answer: str) -> bool:
        arabic_chars = sum(1 for char in answer if "\u0600" <= char <= "\u06ff")
        latin_chars = sum(1 for char in answer if "a" <= char.lower() <= "z")
        return arabic_chars >= 10 and arabic_chars >= latin_chars


@lru_cache(maxsize=1)
def get_model() -> PrivateAccountingModel:
    return PrivateAccountingModel()


def ask(question: str, max_new_tokens: int = 120) -> str:
    return get_model().answer(question, max_new_tokens=max_new_tokens)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"{MODEL_NAME} ط¬ط§ظ‡ط².")
    print(ask("ظ…ط§ ظ‡ظٹ ط§ظ„ظپط§طھظˆط±ط© ط§ظ„ط¶ط±ظٹط¨ظٹط©طں"))

"""Verify analysis assets are provisioned (dictionary + ONNX model).

Usage: python scripts/check_assets.py
Exit 0 when both assets exist, 1 otherwise with explicit guidance.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402


def main() -> int:
    ok = True
    if os.path.isfile(config.LM_DICTIONARY_PATH):
        print(f"OK dictionary: {config.LM_DICTIONARY_PATH}")
    else:
        ok = False
        print(f"MISSING dictionary: {config.LM_DICTIONARY_PATH}")
        print("  Place the Loughran-McDonald CSV there or set LM_DICTIONARY_PATH.")

    model_file = os.path.join(config.MODEL_PATH, "model_quantized.onnx")
    if os.path.isdir(config.MODEL_PATH) and os.path.isfile(model_file):
        print(f"OK model: {model_file}")
    else:
        ok = False
        print(f"MISSING model: {model_file}")
        print("  Provision the quantized ONNX directory there or set MODEL_PATH.")
        print("  See README.md 'ML models' for the reproducible setup.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

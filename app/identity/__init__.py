"""Master reference set, LoRA training, and face embeddings.

A threshold is calibrated against one embedding model at one version, and
changing either silently invalidates every stored vector — the numbers still
compare, they just stop meaning anything. Re-calibration is therefore forced by
the schema (amendment A3), not remembered.

LoRA base model weights must permit commercial use, and the licence is recorded
in `lora_version.base_model_licence` (task 1.4).
"""

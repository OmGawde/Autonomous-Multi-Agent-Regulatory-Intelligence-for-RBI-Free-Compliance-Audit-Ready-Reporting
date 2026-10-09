"""Phase 1 — Bank Statement Decision / Rule Engine."""

import os

# Keep transformers on the PyTorch backend only, set before anything imports it.
#
# transformers 4.x probes for TensorFlow at import time and pulls it in if the
# environment has it installed. This project never uses TF -- both models run on
# torch -- but a broken TF/protobuf pairing on the host then raises
# "TypeError: Descriptors cannot be created directly" from deep inside an import
# chain, taking down the classifier and the Param adapter with an error that
# names neither. Declaring the backend up front avoids the probe entirely.
#
# (transformers 5.x dropped the TF backend, so this only bites on the 4.55 pin
# that BharatGen FinanceParam requires -- see model/param_adapter.py.)
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

# Per-version independent control-flow engine (rewritten from scratch)
# Each version (py39-py315) has its own reconstruction logic here.
# No shared base decompiler dependency for exception/raise/finally flow.

VERSION_FLOW = {
    "3.9":  "SETUP_FINALLY_POP_BLOCK_RERAISE",
    "3.10": "SETUP_FINALLY_POP_BLOCK_RERAISE",
    "3.11": "SETUP_FINALLY_RERAISE_WITH_EXCEPT",
    "3.12": "SETUP_FINALLY_RERAISE_WITH_EXCEPT",
    "3.13": "SETUP_FINALLY_RERAISE_WITH_EXCEPT",
    "3.14": "SETUP_FINALLY_RERAISE_WITH_EXCEPT",
    "3.15": "SETUP_FINALLY_RERAISE_WITH_EXCEPT",
}

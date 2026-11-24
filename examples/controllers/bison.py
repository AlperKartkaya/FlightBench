"""Bison weights served locally through the publisher-derived decision runtime."""

from examples.controllers.glide import GlideController


class BisonController(GlideController):
    model = "bison-1"
    deployment = model

    def __init__(self):
        super().__init__()
        self.metadata.update(
            name="Bison 1 (31B)",
            provider="Baseten weights, self-hosted on Colab",
            source_url="https://huggingface.co/baselabs/bison-1",
            model_revision="bf8350b2c59eb6c36e95d02a2af870aec18724a7",
            precision="bf16; float32 LM head",
            runtime="Publisher Mammoth runtime with Gemma4 compatibility adaptation",
            provenance_limit="Bison prompt/calibration parity with hosted API is unverified",
        )

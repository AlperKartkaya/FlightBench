"""Minimal external AI controller using FlightBench's frozen action IDs."""

from typing import ClassVar


class ExampleController:
    metadata: ClassVar = {
        "name": "Example categorical controller",
        "controller_type": "ai",
        "provider": "Example Org",
        "model": "example-v1",
        "source_url": "https://example.com/example-v1",
        "license": "Apache-2.0",
        "local": True,
    }

    def decide(self, observation):
        # Replace this fixed choice with model inference. IDs are validated and
        # mapped to canonical absolute controls by FlightBench.
        return {"aileron": "3", "elevator": "7", "rudder": "3", "throttle": "3"}

"""Campaign entry point that records safe provider error categories."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def error_category(error):
    result = {"exception_type": type(error).__name__}
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        result["http_status"] = status
    message = str(error).lower()
    if any(
        marker in message
        for marker in ("usage_limit", "usage limit", "quota", "rate_limit", "rate limit")
    ):
        result["limit_indicated"] = True
    code = getattr(error, "code", None)
    if code in {
        "usage_limit_reached",
        "rate_limit_exceeded",
        "insufficient_quota",
        "server_error",
        "invalid_api_key",
        "account_deactivated",
    }:
        result["provider_code"] = code
    return result


if __name__ == "__main__":
    from flightbench.benchmark import main
    from flightbench.controllers import CodexController, JevController

    for controller_class in (CodexController, JevController):
        original = controller_class.decide

        def observed_decide(self, observation, _original=original):
            try:
                return _original(self, observation)
            except Exception as error:
                print("CONTROLLER_DIAGNOSTIC " + json.dumps(error_category(error)), flush=True)
                raise

        controller_class.decide = observed_decide
    main()

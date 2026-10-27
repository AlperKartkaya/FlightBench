"""Campaign entry point: report safe error categories without changing decisions."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def error_category(error):
    result = {"exception_type": type(error).__name__}
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        result["http_status"] = status
    from pydantic import ValidationError

    if isinstance(error, ValidationError):
        result["validation_types"] = [item["type"] for item in error.errors()]
    message = str(error).lower()
    if any(marker in message for marker in ("usage_limit", "usage limit", "quota", "rate_limit", "rate limit")):
        result["limit_indicated"] = True
    code = getattr(error, "code", None)
    if code in {"usage_limit_reached", "rate_limit_exceeded", "insufficient_quota", "server_error", "invalid_api_key", "account_deactivated"}:
        result["provider_code"] = code
    return result


if __name__ == "__main__":
    from flightbench.controllers import CodexController
    from flightbench.benchmark import main

    original = CodexController.decide

    def observed_decide(self, observation):
        try:
            return original(self, observation)
        except Exception as error:
            print("CONTROLLER_DIAGNOSTIC " + json.dumps(error_category(error)), flush=True)
            raise

    CodexController.decide = observed_decide
    main()

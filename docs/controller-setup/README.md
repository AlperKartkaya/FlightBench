# Jev and Codex setup

Human-pilot mode needs neither an API key nor a Codex account. The development
launcher installs the Jev and Codex integrations automatically.

Run the commands below from the repository root, in the same terminal you use to
start FlightBench.

## Jev

Set your real TypeSafe API key **before starting the launcher**.

macOS / Linux:

```sh
export TYPESAFE_API_KEY="your-real-key"
./scripts/dev.sh
```

Windows (PowerShell):

```powershell
$env:TYPESAFE_API_KEY="your-real-key"
python scripts/dev.py
```

Replace `your-real-key` with your actual key; an empty value (`""`) does not
authenticate. Restart the launcher after changing the key. Never put the key in
frontend code, screenshots or committed files.

## Codex

Install the Codex CLI, then sign in with your ChatGPT account:

```sh
codex login
codex login status
```

Confirm that the status reports a ChatGPT login. This integration uses your Codex
account session, not an OpenAI API key. Then start FlightBench using
`./scripts/dev.sh` on macOS/Linux, or
`python scripts/dev.py` in PowerShell.

In the UI, choose the Jev or Codex controller, select a model and click
**Start flight**. If the server was already running before setup, stop it with
**Ctrl+C** and restart it.

The Codex integration uses
[llm-openai-via-codex](https://github.com/simonw/llm-openai-via-codex).

[Back to Quick take-off](../../README.md#quick-take-off)

"""One high-effort trial using the standard evaluator and unchanged action protocol."""
import hashlib
import json
import sys
import tarfile
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from flightbench import benchmark, controllers
from flightbench.runs import SOURCE_FILES, source_identity, now

out = Path(__file__).resolve().parent
submission = ROOT / 'leaderboard/submissions/gpt-6-1-sol-high-20261021'
assert not submission.exists(), 'Do not overwrite a previous trial'
metadata = {
    'name': 'GPT 6.1 Sol high', 'slug': submission.name,
    'model': 'openai-codex/gpt-6.1-sol', 'provider': 'OpenAI',
    'source_url': 'https://openai.com/', 'license': 'proprietary hosted API',
    'local': False, 'controller_type': 'ai',
    'cost_methodology': 'Subscription marginal cost unknown; recorded usage only.',
    'reasoning_effort': 'high',
    'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'campaign': {'decision_hz': 2, 'scenario': 'easy', 'seed': 42,
                 'mode': 'lockstep', 'jobs': 1, 'warmup': 'none',
                 'request_timeout_s': 120, 'provider_hardware': 'undisclosed'},
}
(out / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
archive = out / 'benchmark-source.tar.gz'
with tarfile.open(archive, 'x:gz') as tar:
    for p in SOURCE_FILES:
        if p.is_file(): tar.add(p, arcname=p.relative_to(ROOT))
    tar.add(__file__, arcname='run-high.py')
(out / 'source.json').write_text(json.dumps({'identity': source_identity(), 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2) + '\n')
# Only select effort; the production adapter handles prompts, IDs, usage and commands.
controllers.CodexController = partial(controllers.CodexController, reasoning_effort='high')
args = ['--controller', 'codex', '--model', metadata['model'], '--metadata', str(out / 'metadata.json'), '--modes', 'lockstep', '--seeds', '42', '--jobs', '1', '--decision-hz', '2', '--time-scale', '1.0', '--realtime-response-policy', 'apply-on-arrival', '--timeout', '120', '--output-dir', str(submission)]
status = {'started_at': now(), 'arguments': args, 'reasoning_effort': 'high', 'status': 'running'}
(out / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
benchmark.evaluate(args)
status.update(finished_at=now(), status='exported')
(out / 'status.json').write_text(json.dumps(status, indent=2) + '\n')

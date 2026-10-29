"""Append third trial per group; preserve the original two-trial submissions."""
import gzip
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from flightbench.leaderboard import build_submission, validate_submission
from flightbench.runs import SOURCE_FILES, now, source_identity

OUT = Path(__file__).resolve().parent
DATA = ROOT / 'leaderboard/campaigns/2026-10-22-scoring-v2/submissions'
identity = source_identity()
archive = OUT / 'benchmark-source.tar.gz'
if archive.exists():
    frozen = json.loads((OUT / 'source.json').read_text())
    assert identity['source_hash'] == frozen['identity']['source_hash'], 'Benchmark source changed'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == frozen['archive_sha256']
else:
    with tarfile.open(archive, 'x:gz') as tar:
        for p in SOURCE_FILES:
            if p.is_file(): tar.add(p, arcname=p.relative_to(ROOT))
        tar.add(__file__, arcname='campaign-runner.py')
    (OUT / 'source.json').write_text(json.dumps({'identity': identity, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2)+'\n')
cases = [('jev', model, None) for model in ('jev-1.13.0', 'jev-1.14.0')]
cases += [('codex', model, effort) for model in ('openai-codex/gpt-6.1-sol', 'openai-codex/gpt-6-astra', 'openai-codex/gpt-6-luna', 'openai-codex/gpt-6-sol') for effort in ('low','medium','high','xhigh','max')]
cases.sort(key=lambda case: (case[2] == 'max', case[1] == 'openai-codex/gpt-6-astra' and case[2] == 'max'))
status=json.loads((OUT/'status.json').read_text()) if (OUT/'status.json').exists() else []
for controller, model, effort in cases:
    slug=model.split('/')[-1].replace('.','-')+('-'+effort if effort else '')
    folder=DATA/slug; folder.mkdir(parents=True, exist_ok=True)
    if (folder/'submission.json').exists():
        prior=validate_submission(json.loads((folder/'submission.json').read_text()),folder)
        if len(prior.runs)==3: continue
        assert len(prior.runs)==2
        for name in ('submission','metadata'):
            backup=folder/f'{name}-best-of-two.json'
            if not backup.exists(): shutil.copy2(folder/f'{name}.json',backup)
    metadata={'name':model.split('/')[-1]+(' '+effort if effort else ''), 'slug':slug,
      'model':model,'controller_type':'ai','provider':'OpenAI' if controller=='codex' else 'TypeSafe',
      'source_url':'https://developers.openai.com/api/docs/models/'+model.split('/')[-1] if controller=='codex' else 'https://docs.typesafe.ai/models',
      'license':'proprietary hosted API','local':False,'pricing_date':'2026-10-22',
      'cost_methodology':'Selected-flight actual token usage at dated Standard short-context API-equivalent rates; not subscription billing. Missing usage or cache-write TTL means unknown. Jev $0.042/M input, output free.',
      'campaign':{'id':'2026-10-22-scoring-v2','scoring_version':'v2','seeds':[42,101,202], 'model_parallelism':1,'per_model_episode_jobs':1,'decision_hz':2,'time_scale':1.0,'request_timeout_s':300,'scenario':'easy: repeated physical initialization','selection':'highest score of three completed campaign trials; lower seed breaks ties; excluded controller/infrastructure attempts disclosed separately','provider_hardware':'undisclosed remote','warmup':'none'},
    }
    if effort:metadata['reasoning_effort']=effort
    meta=folder/'metadata.json';meta.write_text(json.dumps(metadata,indent=2)+'\n')
    records=[];artifacts=[]
    for seed in (42,101,202):
        assert source_identity()['source_hash']==identity['source_hash'], 'Benchmark source changed during campaign'
        trial=folder/'trials'/str(seed)
        if (trial/'submission.json').exists():
            sub=validate_submission(json.loads((trial/'submission.json').read_text()),trial)
            assert len(sub.artifacts)==1
            artifact=trial/sub.artifacts[0].path
            record=json.loads(gzip.decompress(artifact.read_bytes()) if artifact.suffix=='.gz' else artifact.read_bytes())
            assert record['outcome']['status'] not in {'controller_timeout','controller_error','interrupted','error'}, 'Archive incomplete attempt explicitly before retry'
            records.append(record);artifacts.append(artifact)
            continue
        assert not trial.exists(), 'Archive unfinished evidence explicitly before retry' 
        cmd=[str(ROOT/'.venv/bin/python'),'-u',str(OUT/'diagnostic_entry.py'),'eval','--controller',controller,'--model',model,'--metadata',str(meta),'--modes','lockstep','--seeds',str(seed),'--jobs','1','--decision-hz','2','--time-scale','1.0','--realtime-response-policy','apply-on-arrival','--timeout','300','--output-dir',str(trial)]
        if effort:cmd+=['--reasoning-effort',effort]
        entry={'model':model,'effort':effort,'seed':seed,'started_at':now(),'command':cmd,'status':'running'}
        status.append(entry);(OUT/'status.json').write_text(json.dumps(status,indent=2)+'\n')
        with (OUT/f'{slug}-{seed}.log').open('x') as log:
            process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
            exported_at=None
            while process.poll() is None:
                if (trial/'submission.json').exists():
                    exported_at=exported_at or time.monotonic()
                    if time.monotonic()-exported_at>15:
                        process.terminate()
                        try: process.wait(timeout=10)
                        except subprocess.TimeoutExpired: process.kill();process.wait()
                        entry['cleanup']='terminated already-exported process with residual provider work'
                        break
                time.sleep(2)
        entry.update(exit_code=process.returncode,finished_at=now())
        subpath=trial/'submission.json'
        if not subpath.exists():
            entry['status']='export_failed';(OUT/'status.json').write_text(json.dumps(status,indent=2)+'\n')
            raise RuntimeError(f'Trial export failed: {slug} seed {seed}; inspect sanitized log')
        sub=validate_submission(json.loads(subpath.read_text()),trial)
        assert len(sub.artifacts)==1
        artifact=trial/sub.artifacts[0].path
        record=json.loads(gzip.decompress(artifact.read_bytes()) if artifact.suffix=='.gz' else artifact.read_bytes())
        assert record['config']['scoring_version']=='v2'
        if effort:assert all(d['decision_info']['reasoning_effort']==effort for d in record['decisions'] if d.get('decision_info'))
        records.append(record);artifacts.append(artifact)
        entry.update(status='recorded',outcome=record['outcome'],applied=record['diagnostics']['interventions']['applied'])
        (OUT/'status.json').write_text(json.dumps(status,indent=2)+'\n')
        print(slug,seed,record['outcome'],flush=True)
        assert record['outcome']['status'] not in {'controller_timeout','controller_error','interrupted','error'}, 'Infrastructure failure: stop campaign for diagnosis'
    payload=build_submission(records,metadata,artifacts,folder/'submission.json')
    validate_submission(payload,folder)
print('CAMPAIGN COMPLETE',flush=True)

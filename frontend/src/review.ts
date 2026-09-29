import { comparisonDifferences, measurement, outcomeLabel, policyLabel, touchdownValues } from './results.ts';
import type { RunRecord } from './results.ts';

// Local files are the archive; this view never deletes or rewrites experiments.
export function setupReview(container: HTMLElement) {
  container.innerHTML = `
    <div class="section-heading"><div><span class="eyebrow">03 / REVIEW</span><h2>Saved experiments</h2></div>
      <div class="review-actions"><button id="refreshRuns" class="btn-secondary">Refresh</button>
      <button id="compareRuns" class="btn-primary" disabled>Compare two runs</button></div></div>
    <p id="historyStatus" role="status">Loading saved runs…</p>
    <div class="table-scroll"><table class="runs-table"><thead><tr><th scope="col">Compare</th><th scope="col">Started</th><th scope="col">Controller / policy</th><th scope="col">Conditions</th><th scope="col">Outcome</th><th scope="col">Score</th><th scope="col">Details</th></tr></thead><tbody id="savedRuns"></tbody></table></div>
    <dialog id="runReview" class="fb-modal" aria-labelledby="runReviewTitle"><div class="modal-card wide">
      <div class="modal-header"><h2 id="runReviewTitle">Experiment review</h2><button id="closeReview" class="btn-secondary">Close</button></div>
      <div class="modal-body"><p id="comparisonNote"></p><div class="table-scroll"><table class="runs-table" id="comparisonTable"></table></div>
      <details><summary>Full saved record</summary><pre id="savedRecordJson" class="modal-code-block"></pre></details></div>
      <div class="modal-footer"><button id="downloadRun" class="btn-secondary">Download JSON</button></div>
    </div></dialog>`;
  const get = <T extends HTMLElement>(id: string) => container.querySelector<T>(`#${id}`)!;
  const selected = new Set<string>();
  let displayed: RunRecord[] = [];
  let refreshVersion = 0;
  const modal = get<HTMLDialogElement>('runReview');
  get('closeReview').onclick = () => modal.close();
  get('downloadRun').onclick = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(displayed.length === 1 ? displayed[0] : displayed, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = displayed.length === 1 ? `${displayed[0].run_id}.json` : 'flightbench-comparison.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  async function inspect(ids: string[]) {
    get('historyStatus').textContent = 'Loading experiment details…';
    try {
      displayed = await Promise.all(ids.map(async (id) => {
        const response = await fetch(`/api/runs/${encodeURIComponent(id)}`);
        if (!response.ok) throw new Error('Saved record could not be read.');
        return await response.json() as RunRecord;
      }));
      const differences = displayed.length === 2 ? comparisonDifferences(displayed[0].config, displayed[1].config) : [];
      if (displayed.length === 2 && displayed[0].source_identity?.source_hash !== displayed[1].source_identity?.source_hash) differences.push('source_hash');
      get('comparisonNote').textContent = displayed.length === 1
        ? 'Touchdown values are frozen at first main-gear contact, not at the end of rollout. N/A means no contact was recorded.'
        : differences.length ? `Different conditions: ${differences.join(', ')}. This is a diagnostic comparison, not a controlled ranking.`
          : 'Same recorded configuration and source. Compare outcomes; one run is not a success-rate estimate.';
      const table = get<HTMLTableElement>('comparisonTable');
      table.replaceChildren();
      const row = (label: string, values: string[]) => {
        const tr = document.createElement('tr');
        const th = document.createElement('th');
        th.scope = 'row'; th.textContent = label; tr.append(th);
        for (const value of values) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
        table.append(tr);
      };
      row('Run', displayed.map((r) => r.run_id));
      row('Policy', displayed.map((r) => policyLabel(r.config)));
      row('Outcome', displayed.map((r) => outcomeLabel(r.outcome.status, r.outcome.success)));
      row('Score', displayed.map((r) => measurement(r.outcome.quality, 2, ' / 100')));
      for (const [i, label] of ['Touchdown airspeed', 'Touchdown sink', 'Touchdown centerline offset', 'Touchdown pitch', 'Touchdown bank'].entries()) {
        row(label, displayed.map((r) => touchdownValues(r.outcome)[i]));
      }
      for (const field of new Set(displayed.flatMap((r) => Object.keys(r.config)))) {
        row(field.replaceAll('_', ' '), displayed.map((r) => typeof r.config[field] === 'object' ? JSON.stringify(r.config[field]) : String(r.config[field] ?? 'N/A')));
      }
      for (const field of new Set(displayed.flatMap((r) => Object.keys(r.diagnostics)))) {
        row(field.replaceAll('_', ' '), displayed.map((r) => typeof r.diagnostics[field] === 'object' && r.diagnostics[field] !== null ? Object.entries(r.diagnostics[field]).map(([key, value]) => `${key}: ${value}`).join(' · ') : String(r.diagnostics[field] ?? 'N/A')));
      }
      row('Source hash', displayed.map((r) => r.source_identity?.source_hash ?? 'Not recorded'));
      get('savedRecordJson').textContent = JSON.stringify(displayed.length === 1 ? displayed[0] : displayed, null, 2);
      if (!modal.open) modal.showModal();
      get('historyStatus').textContent = 'Saved records loaded.';
    } catch {
      get('historyStatus').textContent = 'Unable to load saved records. Check the local server and try Refresh.';
    }
  }

  async function refresh() {
    const version = ++refreshVersion;
    get('historyStatus').textContent = 'Loading saved runs…';
    try {
      const response = await fetch('/api/runs');
      if (!response.ok) throw new Error('History unavailable');
      const { runs } = await response.json() as { runs: RunRecord[] };
      if (version !== refreshVersion) return;
      selected.clear();
      get<HTMLButtonElement>('compareRuns').disabled = true;
      const body = get<HTMLTableSectionElement>('savedRuns'); body.replaceChildren();
      get('historyStatus').textContent = runs.length ? `${runs.length} saved runs shown. Interrupted flights are retained separately from landing failures.` : 'No saved runs yet. Start a local baseline flight; completed or interrupted runs will appear here.';
      for (const run of runs) {
        const tr = document.createElement('tr');
        const chooseCell = document.createElement('td');
        const choose = document.createElement('input'); choose.type = 'checkbox';
        choose.setAttribute('aria-label', `Compare run ${run.run_id}`);
        choose.onchange = () => {
          if (choose.checked && selected.size >= 2) { choose.checked = false; return; }
          if (choose.checked) selected.add(run.run_id); else selected.delete(run.run_id);
          get<HTMLButtonElement>('compareRuns').disabled = selected.size !== 2;
        };
        chooseCell.append(choose); tr.append(chooseCell);
        const values = [new Date(run.started_at).toLocaleString(), policyLabel(run.config),
          `seed ${run.config.seed} · ${run.config.decision_hz} Hz`,
          outcomeLabel(run.outcome.status, run.outcome.success), measurement(run.outcome.quality, 1, '')];
        for (const value of values) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
        const actionCell = document.createElement('td');
        const inspectButton = document.createElement('button'); inspectButton.className = 'btn-secondary'; inspectButton.textContent = 'Inspect';
        inspectButton.setAttribute('aria-label', `Inspect run ${run.run_id}`);
        inspectButton.onclick = () => void inspect([run.run_id]);
        actionCell.append(inspectButton); tr.append(actionCell); body.append(tr);
      }
    } catch {
      if (version === refreshVersion) get('historyStatus').textContent = 'History unavailable. Start the local server, then Refresh. Existing files have not been changed.';
    }
  }
  get('refreshRuns').onclick = () => void refresh();
  get('compareRuns').onclick = () => void inspect([...selected]);
  return { refresh };
}

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { touchdownValues, outcomeLabel, comparisonDifferences, nextRunState } from './results.ts';

test('touchdown uses frozen contact values and never final telemetry', () => {
  const result = { touchdown: { airspeed_mps: 28, sink_rate_mps: -1.2, cross_track_m: -4, pitch_deg: 3, roll_deg: 2 } };
  assert.deepEqual(touchdownValues(result), ['28.0 m/s', '-1.20 m/s', '-4.0 m', '3.0°', '2.0°']);
  assert.deepEqual(touchdownValues({}), Array(5).fill('N/A'));
});

test('failure, interruption and success remain distinct', () => {
  assert.equal(outcomeLabel('landed', true), 'Safe landing');
  assert.equal(outcomeLabel('time_limit', false), 'Time limit');
  assert.equal(outcomeLabel('interrupted', false), 'Interrupted');
  assert.equal(outcomeLabel('controller_error', false), 'Controller error');
});

test('only server acknowledgement starts a flight; disconnect cannot leave it running', () => {
  assert.equal(nextRunState('offline', 'start'), 'offline');
  assert.equal(nextRunState('ready', 'start'), 'starting');
  assert.equal(nextRunState('starting', 'error'), 'ready');
  assert.equal(nextRunState('starting', 'accepted'), 'running');
  assert.equal(nextRunState('running', 'error'), 'running');
  assert.equal(nextRunState('running', 'disconnect'), 'offline');
  assert.equal(nextRunState('running', 'finished'), 'complete');
});

test('comparison exposes assistance and timing differences, not just controller name', () => {
  assert.deepEqual(comparisonDifferences({ controller: 'human', wing_leveler: false, decision_hz: 2 }, { controller: 'human', wing_leveler: true, decision_hz: 10 }), ['decision_hz', 'wing_leveler']);
  assert.deepEqual(comparisonDifferences({ seed: 42 }, { seed: 43 }), ['seed']);
});

// Local Vite UI; capability/model discovery mocked, no model is started.
async page => {
  const assert = (value, message) => {if (!value) throw Error(message);};
  await page.route('**/api/capabilities', route => route.fulfill({json: {live_jev: true}}));
  await page.route('**/api/models', route => route.fulfill({json: {models: ['test-codex']}}));
  await page.reload();
  await page.locator('#configureToggle').click();
  await page.locator('input[name="controller-choice"][value="codex"]').check();
  await page.locator('#timingMode').selectOption('lockstep');
  await page.locator('#reasoningEffort').selectOption('high');
  assert(await page.locator('#reasoningEffort').inputValue() === 'high', 'Lockstep cannot use high effort');
  await page.locator('#timingMode').selectOption('realtime');
  assert(await page.locator('#reasoningEffort').inputValue() === 'low', 'Realtime did not select low effort');
  assert(await page.locator('#reasoningEffort option:disabled').count() === 4, 'Realtime permits non-low effort');
  assert(await page.locator('#ghostChoices input[value="live:baseline"]').isVisible(), 'Codex cannot race baseline');
  assert(await page.locator('#ghostChoices input[value^="live:jev"]').count() === 2, 'Codex cannot race both Jev versions');
  assert(await page.locator('#decisionRate').count() === 0, 'Nominal rate selector remains');
  await page.keyboard.press('Escape');
  await page.locator('#scenarioToggle').click();
  await page.locator('#scenario').selectOption('medium');
  assert(!await page.locator('#configPanel').isVisible(), 'Scenario opens controller settings');
  await page.keyboard.press('Escape');
  return 'Codex timing/effort restrictions and all-controller multiselect passed; no inference';
}

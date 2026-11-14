// Pages-mode Vite dev server; all Jev responses are mocked, no paid requests.
async page => {
  const assert = (value, message) => {if (!value) throw Error(message);};
  const base = page.url(), errors = [], calls = {};
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/src/main.ts', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + `
      window.flightSample = () => ({rotation: aircraft.userData.propeller?.rotation.z,
        state: runState, live: [...liveOpponents.keys()],
        decisions: [...liveOpponents.values()].map(e => e.state?.decision_count ?? 0)});
    `});
  });
  const proxy = 'https://flightbench-jev.alperkartkaya.workers.dev/decide';
  await page.context().route(proxy, async route => {
    const {model} = route.request().postDataJSON(); calls[model] = (calls[model] ?? 0) + 1;
    await new Promise(r => setTimeout(r, 120));
    try {await route.fulfill({json: {model,
      action_ids: {aileron: '3', elevator: '7', rudder: '3', throttle: '3'},
      command: {aileron: -.15, elevator: .15, rudder: .09, throttle: .5}}});} catch (error) {if (!/already handled|closed/.test(String(error))) throw error;}
  });
  try {
    await page.setViewportSize({width: 1440, height: 1000}); await page.goto(base);
    await page.waitForFunction(() => !document.querySelector('#start').disabled && window.flightSample().rotation != null);
    const idle = await page.evaluate(() => window.flightSample().rotation);
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => window.flightSample().rotation) === idle, 'Idle propeller spins');
    await page.locator('#scenarioToggle').click();
    assert(!await page.locator('#configPanel').isVisible(), 'Scenario shares controller popover');
    await page.locator('#scenario').selectOption('hard'); await page.keyboard.press('Escape');
    assert(await page.locator('#windInstrument').isVisible(), 'Hard wind compass missing');
    await page.locator('#configureToggle').click();
    await page.locator('input[name="controller-choice"][value="baseline"]').check();
    assert(!await page.locator('#timingMode').isVisible(), 'Baseline has model timing setting');
    assert(await page.locator('#ghostSettings').isVisible(), 'Nonhuman cannot select opponents');
    await page.locator('input[name="controller-choice"][value="jev"]').check();
    await page.locator('#jevModel').selectOption('jev-1.13.0');
    await page.locator('#timingMode').selectOption('realtime');
    await page.locator('#ghostChoices input[value="live:baseline"]').check();
    await page.locator('#ghostChoices input[value="live:jev-1.14.0"]').check();
    await page.keyboard.press('Escape'); await page.locator('#start').click();
    await page.waitForFunction(() => window.flightSample().live.length === 2);
    await page.waitForFunction(() => /\d\.\d Hz/.test(document.querySelector('#effectiveRate').textContent), null, {timeout: 15000});
    assert(await page.evaluate(() => window.flightSample().rotation) !== idle, 'Running propeller stopped');
    assert(calls['jev-1.13.0'] > 5 && calls['jev-1.14.0'] > 5, 'Jev versions did not race');
    const speed = await page.locator('#windSpeed').innerText(), bearing = await page.locator('#windBearing').innerText();
    assert(!speed.includes('—') && !bearing.includes('—'), 'No live wind values');
    const rate = await page.locator('#effectiveRate').innerText();
    assert(await page.evaluate(() => document.querySelector('#configureToggle').textContent.includes(document.querySelector('#effectiveRate').textContent)), 'Toolbar effective rate differs');
    const meanLatency = await page.locator('#cadenceValue').innerText();
    assert(!meanLatency.includes('—'), 'Mean latency missing');
    await page.locator('#decisionDiagnostics summary').click();
    assert(await page.locator('.diagnostic-choice').count() === 4, 'Four actuator diagnostics missing');
    assert(await page.locator('.diagnostic-choice').first().isVisible(), 'Diagnostics hidden');
    await page.locator('#topProbBars').scrollIntoViewIfNeeded();
    await page.screenshot({path: '/tmp/flightbench-diagnostics.png', fullPage: true});
    await page.waitForTimeout(1200);
    assert(await page.locator('#windSpeed').innerText() !== speed || await page.locator('#windBearing').innerText() !== bearing,
      'Hard wind indicator did not change');
    await page.locator('#reset').click();
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    const stopped = await page.evaluate(() => window.flightSample().rotation);
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => window.flightSample().rotation) === stopped, 'Reset propeller spins');
    const after = JSON.stringify(calls); await page.waitForTimeout(400);
    assert(JSON.stringify(calls) === after, 'Reset left a paid request loop');
    for (const [width, height] of [[390, 844], [844, 390]]) {
      await page.setViewportSize({width, height}); await page.goto(base);
      await page.waitForFunction(() => !document.querySelector('#start').disabled);
      await page.locator('#scenarioToggle').click(); await page.locator('#scenario').selectOption('hard');
      await page.keyboard.press('Escape'); await page.locator('#configureToggle').click();
      await page.locator('input[name="controller-choice"][value="jev"]').check();
      await page.keyboard.press('Escape'); await page.locator('#start').click();
      await page.waitForFunction(() => !document.querySelector('#windSpeed').textContent.includes('—'));
      const [wind, readout] = await Promise.all([page.locator('#windInstrument').boundingBox(), page.locator('.flight-readout').boundingBox()]);
      assert(!readout || wind.x >= readout.x + readout.width || wind.y + wind.height <= readout.y || wind.y >= readout.y + readout.height,
        `Wind compass overlaps controls at ${width}x${height}`);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile overflow');
      await page.locator('#decisionDiagnostics summary').click();
      await page.locator('.diagnostic-choice').first().waitFor();
      await page.locator('#topProbBars').scrollIntoViewIfNeeded();
      await page.screenshot({path: `/tmp/flightbench-mobile-${width}.png`, fullPage: true});
      await page.locator('#reset').click();
      await page.waitForFunction(() => !document.querySelector('#start').disabled);
    }
    assert(errors.length === 0, errors.join('\n'));
    return {rate, meanLatency, mockedCalls: calls};
  } finally {await page.goto(base); await page.context().unroute(proxy); await page.unroute('**/src/main.ts');}
}

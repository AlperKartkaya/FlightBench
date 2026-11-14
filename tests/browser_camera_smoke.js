// Run with playwright-cli run-code --filename tests/browser_camera_smoke.js on a Pages-mode Vite dev server.
async page => {
  const assert = (value, message) => { if (!value) throw Error(message); };
  const base = page.url();
  const errors = [];
  const results = [];
  page.on('pageerror', error => errors.push(String(error)));
  // Test-only access to camera geometry; no debug API in the application.
  await page.route('**/src/main.ts', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + `
      window.cameraSample = () => ({distance: camera.position.distanceTo(cameraSubject().position),
        aspect: camera.aspect, zoom: camera.zoom});
    `});
  });
  let requests = 0;
  await page.context().route('https://flightbench-jev.alperkartkaya.workers.dev/decide', async route => {
    requests++;
    const {model} = route.request().postDataJSON();
    // Deliberately pause lockstep physics at every decision. No provider requests.
    await new Promise(resolve => setTimeout(resolve, 500));
    try {
      await route.fulfill({json: {model,
        action_ids: {aileron: '3', elevator: '7', rudder: '3', throttle: '3'},
        command: {aileron: -.15, elevator: .15, rudder: .09, throttle: .5},
      }});
    } catch (error) {
      // Stop/navigation can cancel an in-flight mock reply.
      if (!String(error).includes('already handled')) throw error;
    }
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', {enabled: true, maxTouchPoints: 5});
  try {
    for (const [width, height] of [[390, 844], [844, 390]]) {
      await page.setViewportSize({width, height});
      await page.goto(base);
      await page.waitForFunction(() => !document.querySelector('#start').disabled);
      await page.locator('#configureToggle').click();
      await page.locator('input[name="controller-choice"][value="jev"]').check();
      await page.locator('#timingMode').selectOption('lockstep');
      await page.keyboard.press('Escape');
      const before = requests;
      await page.locator('#start').click();
      const samples = await page.evaluate(async () => {
        const samples = [];
        const start = performance.now();
        await new Promise(resolve => {
          function sample() {
            samples.push(window.cameraSample());
            if (performance.now() - start > 4500) resolve();
            else requestAnimationFrame(sample);
          }
          requestAnimationFrame(sample);
        });
        return samples;
      });
      assert(requests - before >= 3, 'Did not exercise repeated Jev decisions');
      const distances = samples.map(s => s.distance);
      const variation = Math.max(...distances) - Math.min(...distances);
      assert(variation < 0.15, `Camera distance pumps by ${variation.toFixed(3)} m`);
      assert(samples.every(s => s.zoom === 1 && Math.abs(s.aspect - samples[0].aspect) < 1e-9),
        'Camera projection changed during decisions');
      results.push({width, height, mockedDecisions: requests - before, distanceVariationM: variation});
      await page.locator('#stop').click();
    }
    assert(errors.length === 0, errors.join('\n'));
    return results;
  } finally {
    await page.goto(base);
    await page.context().unroute('https://flightbench-jev.alperkartkaya.workers.dev/decide');
    await page.unroute('**/src/main.ts');
  }
}

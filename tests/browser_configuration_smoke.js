// Pages-mode Vite dev server. No model requests; the close-up uses a visual-only wind fixture.
async page => {
  const assert = (value, message) => {if (!value) throw Error(message);};
  const base = page.url(), errors = [], layouts = [];
  const disjoint = (a, b) => a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/src/main.ts', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + `
      window.windFlowProbe = () => ({bearing: windsock.sourceBearingDeg, flow: windsock.flowBearingDeg, speed: windsock.speedMps,
        rotation: document.querySelector('#windArrow').getAttribute('transform')});
      window.windReadingsPreview = () => {lastObservation = {environment: {headwind_mps: 12, crosswind_mps: 8, vertical_wind_mps: .5}};};
      window.windsockPreview = () => {
        lastObservation = {environment: {headwind_mps: 5, crosswind_mps: 4, vertical_wind_mps: 0}};
        aircraft.visible = false; desiredPosition.set(8, 5.5, -28); aircraft.position.copy(desiredPosition);
        cameraMode = 'orbit'; orbit.enabled = true; orbit.target.copy(desiredPosition);
        lastOrbitTarget.copy(desiredPosition); camera.position.set(-5, 9, -43);
      };
    `});
  });
  try {
    for (const [width, height] of [[1440, 1000], [390, 844], [320, 667], [844, 390]]) {
      await page.setViewportSize({width, height}); await page.goto(base);
      await page.waitForFunction(() => !document.querySelector('#start').disabled);
      for (const [selector, size] of [['.brand-title img', 22], ['.jev-brand-badge img', 18]]) {
        const icon = page.locator(selector);
        await icon.evaluate(img => img.decode());
        assert((await icon.getAttribute('src')).endsWith('/FlightBench/flightbench-icon.png'), 'Brand icon ignores Pages base path');
        const bounds = await icon.boundingBox();
        assert(bounds.width === size && bounds.height === size, 'Brand icon is oversized');
      }
      assert(!(await page.locator('.jev-brand-badge').innerText()).includes('⚡'), 'Brand still uses lightning emoji');
      const headingColor = await page.locator('.ctrl-card-title').filter({hasText: /^Actuator Output$/}).evaluate(el => getComputedStyle(el).color);
      assert(await page.locator('#ctrlBrandTitle').evaluate(el => getComputedStyle(el).color) === headingColor, 'Controller name color differs from panel headings');
      const header = await page.locator('.topbar').boundingBox();
      for (const item of await page.locator('.brand-title, .profile-link').all()) {
        const bounds = await item.boundingBox();
        assert(bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.y + bounds.height <= header.y + header.height, 'Header brand or profile link is clipped');
      }
      await page.locator('#configureToggle').click();
      assert(await page.locator('.opponent-model-group').count() === 1, 'Repeated Jev opponent cards');
      assert(await page.locator('.opponent-model-group input').count() === 2, 'Jev version badges missing');
      const font = await page.locator('.settings-heading').first().evaluate(el => getComputedStyle(el).fontFamily);
      assert(!font.includes('Mono') && !font.includes('monospace'), 'Heading still monospace');
      for (const tile of await page.locator('.controller-card:visible, .opponent-card:visible, .version-badge:visible').all()) {
        assert((await tile.boundingBox()).height >= 44, 'Small selection target');
      }
      await page.locator('input[name="controller-choice"][value="jev"]').check();
      await page.locator('input[name="jev-version"][value="jev-1.14.0"]').check();
      assert(await page.locator('#jevModel').inputValue() === 'jev-1.14.0', 'Version selection not propagated');
      assert(await page.locator('#ghostChoices input[value="live:jev-1.14.0"]').count() === 0, 'Self opponent offered');
      await page.locator('#ghostChoices input[value="live:jev-1.13.0"]').check();
      await page.locator('#ghostChoices input[value="live:baseline"]').check();
      assert(await page.locator('#ghostChoices input:checked').count() === 2, 'Multiselect lost');
      await page.screenshot({path: `output/playwright/configuration-${width}.png`});
      await page.keyboard.press('Escape');
      await page.locator('#scenarioToggle').click(); await page.locator('#scenario').selectOption('hard');
      assert(await page.locator('#scenarioSummary section').count() === 2, 'Scenario bounds are not grouped');
      assert(await page.locator('#scenarioSummary dt').count() === 7, 'Scenario bounds omitted');
      assert(!/XW|HW|VW|seed-deterministic/.test(await page.locator('#scenarioSummary').innerText()), 'Raw scenario dump remains');
      assert((await page.locator('#scenarioSummary').innerText()).includes('±60 m'), 'Initial offset bound omitted');
      await page.screenshot({path: `output/playwright/scenario-${width}.png`});
      await page.keyboard.press('Escape');
      if (width <= 850) await page.locator('#hudToggle').click();
      await page.waitForFunction(() => {const c = document.querySelector('#viewport'); return Math.abs(c.getBoundingClientRect().height - c.parentElement.clientHeight) < 1;});
      const wind = await page.locator('#windInstrument').boundingBox();
      const hud = await page.locator('#hudOverlay').boundingBox();
      const toolbar = await page.locator('#viewerToolbar').boundingBox();
      const viewport = await page.locator('#viewport').boundingBox();
      assert(hud.y - viewport.y >= 9 && hud.y - viewport.y <= 15, 'Instruments pushed down from top edge');
      assert(disjoint(wind, hud) && disjoint(wind, toolbar), 'Wind overlaps HUD or toolbar');
      if (width > 850) {
        assert(hud.width === 440, 'Original telemetry footprint was shrunk');
        assert(await page.locator('#hudIas').evaluate(el => getComputedStyle(el).fontSize) === '22px', 'Telemetry values were shrunk');
        assert(wind.x >= hud.x + hud.width && Math.abs(wind.y - hud.y) <= 1, 'Wind is not alongside top-left HUD');
        assert(Math.abs(wind.height - hud.height) <= 1, 'Adjacent instruments have unequal heights');
      }
      const speed = await page.locator('#windSpeed').boundingBox(), bearing = await page.locator('#windBearing').boundingBox();
      assert(bearing.x >= speed.x + speed.width && Math.abs(speed.y - bearing.y) < 10, 'Wind readings are not a row');
      if (width === 320) {
        await page.evaluate(() => window.windReadingsPreview());
        await page.waitForFunction(() => window.windFlowProbe().speed > 14);
        const reading = await page.locator('#windBearing').boundingBox();
        assert(reading.x + reading.width <= wind.x + wind.width - 4, 'From bearing overflows narrow wind card');
      }
      assert(wind.x + wind.width <= width, 'Wind overflows mobile');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow');
      if (width <= 850) {
        await page.locator('#hudToggle').click();
        await page.waitForFunction(() => {const c = document.querySelector('#viewport'); return Math.abs(c.getBoundingClientRect().height - c.parentElement.clientHeight) < 1;});
        assert(await page.locator('#windInstrument').isVisible(), 'Collapsed HUD hid wind');
        const collapsed = await page.locator('#windInstrument').boundingBox();
        const currentViewport = await page.locator('#viewport').boundingBox();
        assert(collapsed.y - currentViewport.y >= 9 && collapsed.y - currentViewport.y <= 15, 'Collapsed wind lost top anchor');
      }
      layouts.push(`${width}x${height}`);
      await page.screenshot({path: `output/playwright/instruments-${width}.png`});
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.evaluate(() => window.windsockPreview()); await page.waitForTimeout(1800);
    const flow = await page.evaluate(() => window.windFlowProbe());
    assert(Math.abs(Number(flow.rotation.match(/rotate\(([^ ]+)/)[1]) - flow.bearing) < .001, 'Wind graphic differs from source direction');
    assert(await page.locator('#windBearing').innerText() === `From ${Math.round(flow.bearing) % 360}°`, 'Numeric bearing differs from wind source');
    assert(Math.abs(((flow.bearing - flow.flow + 360) % 360) - 180) < .001, 'Source arrow must oppose downstream cloth');
    assert(await page.locator('#windSpeed').innerText() === `${flow.speed.toFixed(1)} m/s`, 'Panel speed differs from cloth');
    await page.screenshot({path: 'output/playwright/windsock-closeup.png'});
    assert(errors.length === 0, errors.join('\n'));
    return {layouts, errors};
  } finally {await page.unroute('**/src/main.ts'); await page.goto(base);}
}

// Pages-mode Vite dev server. No model requests; the close-up uses a visual-only wind fixture.
async page => {
  const assert = (value, message) => {if (!value) throw Error(message);};
  const base = page.url(), errors = [], layouts = [];
  const disjoint = (a, b) => a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/src/main.ts', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + `
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
      await page.keyboard.press('Escape');
      if (width <= 850) await page.locator('#hudToggle').click();
      const wind = await page.locator('#windInstrument').boundingBox();
      const hud = await page.locator('#hudOverlay').boundingBox();
      const toolbar = await page.locator('#configureToggle').boundingBox();
      assert(disjoint(wind, hud) && disjoint(wind, toolbar), 'Wind overlaps HUD or toolbar');
      assert(wind.x >= hud.x + hud.width && Math.abs(wind.y - hud.y) <= 1, 'Wind is not alongside top-left HUD');
      assert(wind.x + wind.width <= width, 'Wind overflows mobile');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow');
      if (width <= 850) {
        await page.locator('#hudToggle').click();
        assert(await page.locator('#windInstrument').isVisible(), 'Collapsed HUD hid wind');
      }
      layouts.push(`${width}x${height}`);
      await page.screenshot({path: `output/playwright/instruments-${width}.png`});
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.evaluate(() => window.windsockPreview()); await page.waitForTimeout(1800);
    await page.screenshot({path: 'output/playwright/windsock-closeup.png'});
    assert(errors.length === 0, errors.join('\n'));
    return {layouts, errors};
  } finally {await page.unroute('**/src/main.ts'); await page.goto(base);}
}

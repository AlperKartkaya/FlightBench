// Local Pages dev server. Visual pose fixtures only; no provider calls.
async page => {
  const assert = (value, message) => {if (!value) throw Error(message);};
  const base = page.url(), errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/src/main.ts', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + `
      window.compassPose = (heading, pitch = 0, roll = 0) => {
        desiredQuaternion.setFromEuler(new THREE.Euler(THREE.MathUtils.degToRad(roll), -THREE.MathUtils.degToRad(heading), THREE.MathUtils.degToRad(pitch), 'YZX'));
        aircraft.quaternion.copy(desiredQuaternion);
      };
      window.compassOpponent = heading => {
        const visual = new THREE.Object3D(); visual.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -THREE.MathUtils.degToRad(heading));
        const run = {samples: [{time: 0, position: [0, 20, 0], quaternion: visual.quaternion.toArray()}], controller: 'jev', score: 0};
        watchedGhost = run;
        activeGhosts.push({run, visual, label: 'Test opponent', color: 0x7187b5, marker: document.createElement('div')});
      };
    `});
  });
  try {
    for (const [width, height] of [[1440, 1000], [390, 844], [320, 667], [844, 390]]) {
      await page.setViewportSize({width, height}); await page.goto(base);
      await page.waitForFunction(() => !document.querySelector('#start').disabled);
      assert(await page.locator('#headingInstrument').isVisible(), 'Compass missing in calm air');
      const fills = await page.evaluate(() => ['headingNeedle', 'windArrow'].map(id => getComputedStyle(document.getElementById(id)).fill));
      assert(fills[0] === fills[1], 'Aircraft and wind symbols have different colors');
      assert(await page.locator('#headingNeedle rect').count() === 1, 'Top-view propeller silhouette missing');
      assert(await page.locator('#compassHeading').innerText() === '0°', 'Idle compass is not northbound');
      await page.locator('#scenarioToggle').click(); await page.locator('#scenario').selectOption('hard'); await page.keyboard.press('Escape');
      const wind = await page.locator('#windInstrument').boundingBox(), compass = await page.locator('#headingInstrument').boundingBox();
      assert(compass.x >= wind.x + wind.width && Math.abs(compass.y - wind.y) < 1, `Compass is not next to wind at ${width}`);
      assert(Math.abs(compass.height - wind.height) < 1, 'Navigation card heights differ');
      assert(compass.x + compass.width <= width && wind.x >= 0, 'Navigation cards overflow');
      for (const [heading, text] of [[0, '0°'], [90, '90°'], [180, '180°'], [270, '270°'], [359, '359°'], [1, '1°'], [14, '14°'], [359.8, '0°']]) {
        await page.evaluate(h => window.compassPose(h, 12, 20), heading);
        await page.waitForFunction(expected => document.querySelector('#compassHeading').textContent === expected, text);
        const angle = await page.locator('#headingNeedle').getAttribute('transform');
        const delta = ((Number(angle.match(/rotate\(([^ ]+)/)[1]) - heading + 540) % 360) - 180;
        assert(Math.abs(delta) < .001, `Bank/pitch changed heading: ${heading}`);
      }
      // Camera changes must not rotate a north-up compass.
      await page.locator('[data-camera="tower"]').click();
      assert(await page.locator('#compassHeading').innerText() === '0°', 'Compass follows camera rather than aircraft');
      await page.locator('.heading-readings .instrument-label').focus();
      assert(await page.getByRole('tooltip').isVisible(), 'Heading definition inaccessible');
      assert((await page.getByRole('tooltip').innerText()).includes('not its ground track'), 'Heading definition is unclear');
      await page.keyboard.press('Escape');
      await page.screenshot({path: `output/playwright/compass-${width}.png`});
    }
    await page.evaluate(() => window.compassOpponent(270));
    await page.waitForFunction(() => document.querySelector('#compassHeading').textContent === '270°');
    assert(await page.locator('#viewport').getAttribute('data-subject') === 'opponent', 'Compass did not follow the watched opponent');
    await page.locator('#reset').click();
    await page.waitForFunction(() => document.querySelector('#compassHeading').textContent === '0°');
    assert(errors.length === 0, errors.join('\n'));
    return {layouts: 4, headings: 'cardinals, north wrap, bank/pitch, camera independence, spectator, reset, keyboard guide', errors};
  } finally {await page.unroute('**/src/main.ts'); await page.goto(base);}
}

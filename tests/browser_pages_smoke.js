// Run with playwright-cli run-code --filename tests/browser_pages_smoke.js on a Pages build.
async page => {
  const assert = (value, message) => { if (!value) throw Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const base = page.url();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', {enabled: true, maxTouchPoints: 5});
  for (const [width, height] of [[390, 844], [320, 667], [844, 390]]) {
    await page.setViewportSize({width, height});
    await page.goto(base);
    await page.locator('#start').waitFor({state: 'visible'});
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow');
    const icon = await page.locator('link[rel="icon"]').getAttribute('href');
    const favicon = await page.request.get(new URL(icon, page.url()).href);
    assert(favicon.ok() && favicon.headers()['content-type'].includes('image/png'), 'Favicon unavailable');
    for (const button of await page.locator('.ctrl-btn').all()) {
      const box = await button.boundingBox();
      assert(box.height >= 44, 'Touch target smaller than 44px');
    }
    const up = page.locator('[data-axis="elevator"][data-dir="-1"]');
    const left = page.locator('[data-axis="aileron"][data-dir="-1"]');
    await up.scrollIntoViewIfNeeded();
    const canvas = await page.locator('#viewport').boundingBox();
    assert(canvas.y < height && canvas.y + canvas.height > 100, 'Scene lost while reaching touch controls');
    await page.locator('#start').click();
    await page.waitForFunction(() => !document.querySelector('#stop').disabled);
    await left.scrollIntoViewIfNeeded();
    const [u, l] = await Promise.all([up.boundingBox(), left.boundingBox()]);
    const point = (b, id) => ({x: b.x + b.width / 2, y: b.y + b.height / 2, id});
    const touches = [point(u, 1), point(l, 2)];
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: touches});
    await page.waitForTimeout(250);
    const value = axis => page.locator(`#${axis}Value`).innerText().then(Number);
    assert(await value('elevator') < .1, 'Touch pitch did not reach controls');
    assert(await value('aileron') < -.2, 'Simultaneous touch roll did not reach controls');
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: [touches[0]]});
    await page.waitForFunction(() => Math.abs(Number(document.querySelector('#elevatorValue').textContent) - .17) < .02, null, {timeout: 5000});
    assert(await value('aileron') < -.2, 'Releasing pitch incorrectly released roll');
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchCancel', touchPoints: []});
    await page.waitForFunction(() => Math.abs(Number(document.querySelector('#aileronValue').textContent) + .15) < .02, null, {timeout: 5000});
    await page.locator('#stop').click();
    await page.locator('#outcomeModal').waitFor({state: 'visible'});
    await page.getByText('Close result', {exact: true}).click();
    await page.locator('#reset').click();
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    console.log(`PASS: ${width}x${height}, favicon, 44px targets, multi-touch, release/cancel, stop/reset`);
  }
  assert(errors.length === 0, errors.join('\n'));
}

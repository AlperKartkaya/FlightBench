// Pages-mode UI with no model calls. Covers mouse, keyboard and phone-size tap guides.
async page => {
  const assert = (value, message) => {if (!value) throw Error(message);};
  const base = page.url(), errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  for (const [width, height] of [[1440, 1000], [390, 844], [320, 667], [844, 390]]) {
    await page.setViewportSize({width, height}); await page.goto(base);
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    await page.locator('#scenarioToggle').click(); await page.locator('#scenario').selectOption('hard');
    await page.keyboard.press('Escape');
    if (width <= 850) await page.locator('#hudToggle').click();
    await page.waitForFunction(() => {const c = document.querySelector('#viewport'); return Math.abs(c.getBoundingClientRect().height - c.parentElement.clientHeight) < 1;});
    const viewport = await page.locator('#viewport').boundingBox(), toolbar = await page.locator('#viewerToolbar').boundingBox();
    assert(toolbar.y + toolbar.height <= viewport.y + viewport.height, `Open instruments push toolbar out of the scene at ${width}`);
    const tip = page.getByRole('tooltip');
    for (const term of await page.locator('.hud-label, .hud-sub-label').all()) {
      await term.focus();
      assert(await tip.isVisible(), `Focus guide missing for ${await term.innerText()} at ${width}`);
      assert((await tip.locator('strong').innerText()).length > 8, 'Missing expanded term');
      assert((await tip.locator('p').innerText()).length > 20, 'Missing plain-language definition');
      assert((await tip.locator('.help-unit').innerText()).length > 0, 'Missing units');
      assert(await term.getAttribute('aria-describedby') === 'instrumentHelp', `Guide is not associated with ${await term.innerText()} at ${width}`);
      const b = await tip.boundingBox();
      assert(b.x >= 8 && b.y >= 8 && b.x + b.width <= width - 7 && b.y + b.height <= height - 7, 'Guide outside viewport');
      await page.keyboard.press('Escape');
      assert(!await tip.isVisible(), 'Escape failed to dismiss guide');
      assert(await page.locator('#hudOverlay').isVisible(), 'Dismissing guide also closed instruments');
    }
    const agl = page.locator('.hud-label').filter({hasText: /^AGL$/});
    await page.evaluate(() => document.activeElement.blur());
    await agl.hover();
    assert(await tip.isVisible(), `Hover guide missing at ${width}`);
    assert(await tip.locator('strong').innerText() === 'Above ground level', 'Wrong hover definition');
    await tip.hover(); await page.waitForTimeout(200);
    assert(await tip.isVisible(), 'Guide disappears when hovered');
    await page.locator('#connectionText').click();
    assert(!await tip.isVisible(), 'Outside click failed to dismiss');
    await agl.click();
    assert(await tip.isVisible(), `Tap/click guide missing at ${width}`);
    assert(await tip.locator('strong').innerText() === 'Above ground level', 'Tap/click failed to open guide');
    await page.screenshot({path: `output/playwright/instrument-guide-${width}.png`});
    await page.keyboard.press('Escape');
  }
  assert(errors.length === 0, errors.join('\n'));
  return {guides: 'hover, keyboard focus, click/tap, Escape, outside dismissal and viewport bounds passed', errors};
}

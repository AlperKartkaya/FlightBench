// Manual live check: uses the owner's Jev credit; stops each version after two decisions.
// Run with playwright-cli run-code --filename tests/browser_jev_smoke.js on public Pages.
async page => {
  const assert = (value, message) => { if (!value) throw Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const base = page.url();
  await page.setViewportSize({width: 390, height: 844});
  for (const model of ['jev-1.13.0', 'jev-1.14.0']) {
    await page.goto(base);
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    await page.locator('#configureToggle').click();
    await page.locator('#controller').selectOption('jev');
    await page.locator('#jevModel').selectOption(model);
    assert(await page.locator('#jevProxy, #jevInvite, input[type="password"]').count() === 0,
      'Public Jev must not ask for credentials or endpoint');
    await page.keyboard.press('Escape');
    try {
      await page.locator('#start').click();
      await page.waitForFunction(() => Number(document.querySelector('#chipDecisionNum strong').textContent.replace('#', '')) >= 2,
        null, {timeout: 15000});
      assert(await page.locator('#ctrlModelTag').innerText() === model, 'Wrong Jev version');
      assert((await page.locator('#errorBanner').innerText()).trim() === '', 'Jev reported an error');
    } finally {
      if (await page.locator('#stop').isEnabled()) await page.locator('#stop').click();
    }
    await page.locator('#outcomeModal').waitFor({state: 'visible'});
    console.log(`PASS: public ${model}, two real decisions, no credentials, explicit stop`);
  }
  assert(errors.length === 0, errors.join('\n'));
}

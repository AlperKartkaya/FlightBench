// Local UI, real human telemetry and synthetic Jev/landing events; no provider calls.
async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(() => {
    const Native = WebSocket;
    window.WebSocket = class extends Native {
      constructor(...args) {
        super(...args); window.testSocket = this;
        this.addEventListener('message', event => {
          const message = JSON.parse(event.data);
          if (message.type === 'state') window.lastHuman = message;
          if (message.type === 'run_finished') window.humanRecord = message.record;
        });
      }
    };
  });
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#start').disabled);
  await page.locator('#start').click();
  await page.waitForFunction(() => window.lastHuman?.observation.time_s > .2);
  await page.evaluate(() => {
    window.emit = message => window.testSocket.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(message)}));
    window.emit({type:'ghost', message:{type:'run_started',run_id:'fixture-jev'}});
    window.emit({type:'ghost', message:{...window.lastHuman,run_id:'fixture-jev'}});
  });
  // Real primary stop, but no real opponent exists; its fixture remains active.
  await page.locator('#stop').click();
  await page.locator('#outcomeModal').waitFor({state:'visible'});
  await page.getByRole('button', {name:'Watch Jev · API usage continues',exact:true}).click();
  const before = await page.locator('#ghostLegend').textContent();
  await page.evaluate(() => {
    const message = structuredClone(window.lastHuman);
    message.run_id = 'fixture-jev'; message.observation.time_s = 100; message.position[0] += 100;
    window.emit({type:'ghost', message});
  });
  await page.waitForFunction(() => document.querySelector('#ghostLegend').textContent.includes('100.0 s'));
  if (before === await page.locator('#ghostLegend').textContent()) throw Error('Spectator time froze');
  if (!await page.locator('#stop').isEnabled()) throw Error('Cannot stop spectator');
  if (await page.locator('#outcomeModal').isVisible()) throw Error('Result remained open');
  await page.screenshot({path:'/tmp/flightbench-spectator.png'});
  await page.evaluate(() => window.emit({type:'ghost',message:{type:'run_finished',run_id:'fixture-jev',record:{outcome:{quality:0,status:'interrupted',success:false}}}}));
  if (await page.locator('#stop').isEnabled()) throw Error('Stop remained enabled after Jev ended');
  if (errors.length) throw Error(errors.join('\n'));
  console.log('Spectator clock, close-result, live Stop and terminal-state checks passed');
};

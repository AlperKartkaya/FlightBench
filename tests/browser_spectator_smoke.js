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
  // Direct server stop simulates a natural terminal acknowledgement, not a UI Stop intent.
  await page.evaluate(() => window.testSocket.send(JSON.stringify({type:'stop'})));
  await page.waitForFunction(() => document.querySelector('#viewport').dataset.subject === 'opponent');
  if (await page.locator('#outcomeModal').isVisible()) throw Error('Primary result blocks automatic spectating');
  for (const mode of ['orbit', 'tower', 'chase', 'orbit']) {
    await page.locator(`[data-camera="${mode}"]`).click();
    await page.waitForFunction(mode => document.querySelector('#viewport').dataset.camera === mode, mode);
    if (await page.locator('#viewport').getAttribute('data-subject') !== 'opponent') throw Error('Camera lost opponent');
  }
  await page.getByRole('button', {name:'Your result',exact:true}).click();
  await page.getByRole('button', {name:'Watch Jev · API usage continues',exact:true}).click();
  const before = await page.locator('#ghostLegend').textContent();
  await page.evaluate(() => {
    const message = structuredClone(window.lastHuman);
    message.run_id = 'fixture-jev'; message.observation.time_s = 2; message.position[0] += 100;
    window.emit({type:'ghost', message});
  });
  await page.waitForFunction(() => document.querySelector('#ghostLegend').textContent.includes('2.0 s'));
  if (before === await page.locator('#ghostLegend').textContent()) throw Error('Spectator time froze');
  if (!await page.locator('#stop').isEnabled()) throw Error('Cannot stop spectator');
  if (await page.locator('#outcomeModal').isVisible()) throw Error('Result remained open');
  if (await page.locator('#manualControlsCard').isVisible()) throw Error('Human inputs shown for spectator');
  await page.screenshot({path:'/tmp/flightbench-spectator.png'});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/flightbench-spectator-mobile.png'});
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('Mobile overflow');
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(() => window.emit({type:'ghost',message:{type:'run_finished',run_id:'fixture-jev',record:{outcome:{quality:0,status:'interrupted',success:false}}}}));
  if (await page.locator('#stop').isEnabled()) throw Error('Stop remained enabled after Jev ended');
  await page.locator('#outcomeModal').waitFor({state:'visible'});
  if (!(await page.locator('#outcomeTitle').textContent()).includes('Live Jev · Interrupted')) throw Error('Wrong opponent result');
  await page.getByRole('button', {name:'Close result',exact:true}).click();
  await page.getByRole('button', {name:'Your result',exact:true}).click();
  if (!(await page.locator('#outcomeTitle').textContent()).includes('Your flight')) throw Error('Primary result was overwritten');
  await page.getByRole('button', {name:'Close result',exact:true}).click();
  // A completed Jev record also continues as a replay after the primary ends.
  await page.locator('#configureToggle').click();
  await page.getByRole('checkbox', {name:'Jev replay',exact:true}).check();
  await page.evaluate(() => { window.lastHuman = null; });
  await page.locator('#start').click();
  await page.waitForFunction(() => window.lastHuman?.observation.time_s > .2);
  await page.evaluate(() => window.testSocket.send(JSON.stringify({type:'stop'})));
  await page.waitForFunction(() => document.querySelector('#runStatus').textContent === 'Watching Jev replay');
  if (await page.locator('#outcomeModal').isVisible()) throw Error('Primary result blocks replay');
  await page.locator('#outcomeModal').waitFor({state:'visible'});
  if (!(await page.locator('#outcomeTitle').textContent()).includes('Jev replay · Interrupted')) throw Error('Replay result missing');
  await page.getByRole('button', {name:'Close result',exact:true}).click();
  await page.locator('#reset').click();
  await page.waitForFunction(() => document.querySelector('#viewport').dataset.subject === 'primary');
  await page.evaluate(() => window.emit({type:'ghost',message:{type:'run_finished',run_id:'fixture-jev',record:{outcome:{quality:0,status:'crash'}}}}));
  if (await page.locator('#outcomeModal').isVisible()) throw Error('Stale result reopened after reset');
  // An opponent finishing first must not steal the primary's camera or input.
  await page.locator('#configureToggle').click();
  await page.getByRole('checkbox', {name:'Jev replay',exact:true}).uncheck();
  await page.evaluate(() => { window.lastHuman = null; });
  await page.locator('#start').click();
  await page.waitForFunction(() => window.lastHuman?.observation.time_s > .2);
  await page.evaluate(() => {
    window.emit({type:'ghost',message:{type:'run_started',run_id:'early-jev'}});
    window.emit({type:'ghost',message:{...window.lastHuman,run_id:'early-jev'}});
    window.emit({type:'ghost',message:{type:'run_finished',run_id:'early-jev',record:{outcome:{status:'controller_error',success:false}}}});
  });
  if (await page.locator('#outcomeModal').isVisible()) throw Error('Opponent stole primary input');
  if (await page.locator('#viewport').getAttribute('data-subject') !== 'primary') throw Error('Opponent stole primary camera');
  await page.locator('#stop').click();
  await page.locator('#outcomeModal').waitFor({state:'visible'});
  await page.getByRole('button', {name:'Close result',exact:true}).click();
  await page.evaluate(() => { window.lastHuman = null; });
  await page.locator('#start').click();
  await page.waitForFunction(() => window.lastHuman?.observation.time_s > .2);
  await page.evaluate(() => {
    window.emit({type:'ghost',message:{type:'run_started',run_id:'disconnect-jev'}});
    window.emit({type:'ghost',message:{...window.lastHuman,run_id:'disconnect-jev'}});
    window.testSocket.send(JSON.stringify({type:'stop'}));
  });
  await page.waitForFunction(() => document.querySelector('#viewport').dataset.subject === 'opponent');
  await page.evaluate(() => window.testSocket.close());
  await page.waitForFunction(() => document.querySelector('#connectionText').textContent === 'OFFLINE');
  if (await page.locator('#stop').isEnabled()) throw Error('Disconnected opponent remains live');
  if (await page.locator('#outcomeModal').isVisible()) throw Error('Disconnect leaves blocking result');
  if (errors.length) throw Error(errors.join('\n'));
  console.log('Automatic live/replay spectating, all camera modes, separate results, replay completion and stale reset checks passed');
};

// Run through playwright-cli run-code on the local backend UI.
// Real human flights, no provider requests or synthetic successful outcomes.
async page => {
await page.addInitScript(()=>{window.messages=[];const Native=WebSocket;window.WebSocket=class extends Native{constructor(...args){super(...args);this.addEventListener('message',e=>window.messages.push(JSON.parse(e.data)));}send(data){window.messages.push({sent:JSON.parse(data)});super.send(data);}}});
await page.reload();await page.waitForFunction(()=>!document.querySelector('#start').disabled);
await page.locator('#configureToggle').click();
await page.locator('#controller').selectOption('human');
if(await page.locator('#ghostRace').inputValue()!=='off')throw Error('not off');
await page.locator('#start').click();await page.waitForTimeout(5000);
await page.locator('#stop').click();await page.waitForFunction(()=>!document.querySelector('#start').disabled);
await page.keyboard.press('Escape');await page.locator('#configureToggle').click();
await page.locator('#ghostRace').selectOption('previous');
const meta=await page.locator('#ghostStatus').textContent();if(!meta.includes('Interrupted'))throw Error(meta);
await page.screenshot({path:'/tmp/ghost-settings-new.png'});
await page.locator('#start').click();await page.keyboard.down('a');await page.waitForTimeout(2000);await page.keyboard.up('a');
await page.screenshot({path:'/tmp/ghost-previous-new.png'});
if(!await page.locator('#ghostLegend').isVisible())throw Error('No legend');
console.log(await page.locator('#ghostLegend').textContent());
await page.locator('#stop').click();await page.waitForFunction(()=>!document.querySelector('#start').disabled);
await page.keyboard.press('Escape');await page.setViewportSize({width:390,height:844});await page.locator('#configureToggle').click();
await page.screenshot({path:'/tmp/ghost-mobile-new.png'});
const result=await page.evaluate(()=>({errors:messages.filter(x=>x.type==='error'),actions:messages.filter(x=>x.sent?.type==='action').map(x=>Object.keys(x.sent.action)),started:messages.filter(x=>x.type==='run_started').length}));console.log(JSON.stringify(result));
if(result.errors.length || result.started !== 2 || !result.actions.length) throw Error(JSON.stringify(result));
};

// Run with playwright-cli run-code --filename tests/browser_ghost_smoke.js on a Pages build.
// Uses synthetic success solely to test replay UI; does not prove safe landing.
async page => {
const errors=[]; page.on("pageerror", e => errors.push(String(e)));
await page.addInitScript(()=>{const Native=Worker;window.Worker=class extends Native{constructor(...args){super(...args);window.worker=this;this.addEventListener('message',e=>{if(e.data.type==='state')window.lastFrame=e.data;});}}});
await page.reload();await page.waitForFunction(()=>!document.querySelector('#start').disabled);
await page.locator('#configureToggle').click();if(await page.locator('#ghostRace').inputValue()!=='off')throw Error('default');
await page.locator('#ghostRace').selectOption('both');await page.locator('#start').click();await page.waitForFunction(()=>window.lastFrame?.observation.time_s>1);
if(!(await page.locator('#ghostStatus').textContent()).includes('unavailable'))throw Error('missing metadata');
// Fixture-only success: test persistence/render plumbing, not landing physics.
await page.evaluate(()=>{window.worker.postMessage({type:'stop'});const frame=structuredClone(window.lastFrame);frame.done=true;frame.result={...frame.result,success:true,quality:70,reason:'landed'};frame.observation.time_s+=0.1;window.worker.dispatchEvent(new MessageEvent('message',{data:frame}));});
await page.waitForFunction(()=>!document.querySelector('#start').disabled);await page.keyboard.press('Escape');await page.locator('#start').click();await page.waitForTimeout(1000);
const status=await page.locator('#ghostStatus').textContent();if(!status.includes('70.0 pts'))throw Error(status);
await page.screenshot({path:'/tmp/flightbench-ghost-render.png'});
await page.keyboard.press('Escape');await page.locator('#reset').click();await page.waitForFunction(()=>!document.querySelector('#start').disabled);
await page.setViewportSize({width:390,height:844});await page.locator('#configureToggle').click();await page.screenshot({path:'/tmp/flightbench-ghost-mobile.png'});
const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
console.log(JSON.stringify({status,canvas:await page.locator('canvas').count(),overflow,errors}));
if (overflow || errors.length) throw Error(JSON.stringify({overflow, errors}));
};

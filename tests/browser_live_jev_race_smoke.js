// OPT-IN: incurs real TypeSafe API usage. Local backend with credentials required.
// Run with playwright-cli run-code --filename tests/browser_live_jev_race_smoke.js.
async page => {
await page.addInitScript(()=>{window.events=[];const Native=WebSocket;window.WebSocket=class extends Native{constructor(...args){super(...args);this.addEventListener('message',event=>window.events.push(JSON.parse(event.data)));}}});
await page.reload();await page.waitForFunction(()=>!document.querySelector('#start').disabled);await page.locator('#configureToggle').click();await page.getByRole('checkbox',{name:'Live Jev',exact:true}).check();await page.screenshot({path:'/tmp/live-race-settings.png'});await page.locator('#start').click();
try{await page.waitForFunction(()=>events.some(e=>e.type==='ghost' && e.message.type==='state' && e.message.decision_count>0),{},{timeout:10000});}finally{if(await page.locator('#stop').isEnabled())await page.locator('#stop').click();}
await page.waitForFunction(()=>events.some(e=>e.type==='run_finished'));await page.keyboard.press('Escape');await page.screenshot({path:'/tmp/live-race-result.png'});
const result=await page.evaluate(()=>({humanStates:events.filter(e=>e.type==='state').length,ghostStates:events.filter(e=>e.type==='ghost'&&e.message.type==='state').length,decisions:Math.max(...events.filter(e=>e.type==='ghost'&&e.message.type==='state').map(e=>e.message.decision_count)),errors:events.filter(e=>e.type==='error'||e.type==='ghost'&&e.message.type==='error'),finished:events.filter(e=>e.type==='run_finished'||e.type==='ghost'&&e.message.type==='run_finished').map(e=>(e.message||e).record.outcome)}));console.log(JSON.stringify(result));if(result.errors.length||result.decisions<1)throw Error('Live race failed');
await page.setViewportSize({width:390,height:844});await page.locator('#configureToggle').click();await page.screenshot({path:'/tmp/live-race-mobile.png'});

};

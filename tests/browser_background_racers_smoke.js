// Local Pages dev server. Synthetic multi-racer rollout/camera fixtures; no provider calls.
async page => {
  const assert = (value, message) => {if (!value) throw Error(message);};
  const base = page.url(), errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/src/main.ts', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + `
      const fixtureState = (id, time, x, ground) => ({type: 'state', run_id: id, position: [x, ground ? 1 : 40, 0], quaternion: [0, 0, 0, 1], score: 0,
        observation: {...structuredClone(lastObservation), time_s: time, phase: ground ? 'ROLLOUT' : 'AIRBORNE / APPROACH', status: {on_ground: ground, main_gear_on_ground: ground}}});
      window.backgroundState = (id, time, x) => receiveMessage({type: 'ghost', opponent_id: id, message: fixtureState(id, time, x, true)});
      window.backgroundFinish = id => receiveMessage({type: 'ghost', opponent_id: id, message: {type: 'run_finished', run_id: id, record: {outcome: {quality: 80, status: 'landed', success: true}}}});
      window.backgroundFixture = () => {
        applyFlightBenchState(fixtureState(activeRunId, 20, 50, true));
        renderRaceTime = 20;
        for (const id of ['watched', 'background', 'finished']) receiveMessage({type: 'ghost', opponent_id: id, message: {type: 'run_started', run_id: id, config: {controller: 'baseline'}}});
        receiveMessage({type: 'ghost', opponent_id: 'watched', message: fixtureState('watched', 20, 100, false)});
        window.backgroundState('background', 10, 30);
        window.backgroundState('finished', 12, 15);
        const run = {key: ghostKey, controller: 'human', score: 80, success: true, status: 'landed', samples: [
          {time: 0, position: [-400, 1, -10], quaternion: [0, 0, 0, 1]},
          {time: 20, position: [0, 1, -10], quaternion: [0, 0, 0, 1]},
          {time: 26, position: [180, 1, -10], quaternion: [0, 0, 0, 1]}]};
        const visual = createGhostVisual(0x7187b5), marker = document.createElement('div');
        scene.add(visual); ghostLegend.parentElement.append(marker);
        activeGhosts.push({run, visual, marker, color: 0x7187b5, label: 'Background replay'});
        receiveMessage({type: 'run_finished', run_id: activeRunId, record: {config: {controller: 'human'}, outcome: {quality: 0, status: 'crash', success: false}}});
      };
      window.backgroundProbe = () => ({watched: watchedGhost === liveOpponents.get('watched')?.run ? 'watched' : watchedGhost === liveOpponents.get('background')?.run ? 'background' : 'replay',
        distance: camera.position.distanceTo(cameraSubject().position),
        replayX: activeGhosts.find(g => g.label === 'Background replay')?.visual.position.x,
        liveX: activeGhosts.find(g => g.run === liveOpponents.get('background')?.run)?.visual.position.x});
      window.restartPose = () => {desiredPosition.set(225, 1, 0); aircraft.position.copy(desiredPosition); setCamera('chase');};
      window.backgroundOrbit = () => {setCamera('orbit'); camera.position.copy(cameraSubject().position).add(new THREE.Vector3(-40, 20, 20)); orbit.update();};
      window.chaseProbe = () => ({distance: camera.position.distanceTo(cameraSubject().position), expected: chaseOffset.length()});
    `});
  });
  try {
    await page.goto(base);
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    await page.locator('#start').click();
    await page.waitForFunction(() => document.querySelector('#flightStatePill').textContent === 'IN FLIGHT');
    await page.evaluate(() => window.backgroundFixture());
    await page.waitForTimeout(150);
    const before = await page.evaluate(() => window.backgroundProbe());
    await page.evaluate(() => window.backgroundState('background', 11, 60));
    await page.waitForTimeout(600);
    const rolling = await page.evaluate(() => window.backgroundProbe());
    assert(rolling.watched === 'watched', 'Background touchdown stole the watched aircraft');
    assert(rolling.liveX > before.liveX + 20, 'Unwatched live aircraft froze during rollout');
    assert(rolling.replayX > before.replayX + 5, 'Background replay froze on the watched live clock');
    await page.evaluate(() => window.backgroundOrbit());
    await page.evaluate(() => window.backgroundFinish('finished'));
    await page.waitForTimeout(150);
    assert((await page.evaluate(() => window.backgroundProbe())).distance > 40, 'Background completion reset the spectator camera');
    // The next live aircraft has a slower simulation clock. Replays must not rewind to it.
    await page.evaluate(() => window.backgroundFinish('watched'));
    await page.waitForTimeout(200);
    const switched = await page.evaluate(() => window.backgroundProbe());
    assert(switched.watched === 'background', 'Spectator did not switch to the remaining live pilot');
    assert(switched.replayX >= rolling.replayX, 'Background replay rewound on camera handoff');
    await page.evaluate(() => window.backgroundState('background', 12, 90));
    await page.waitForFunction(() => window.backgroundProbe().liveX > 85);
    await page.evaluate(() => window.backgroundFinish('background'));
    await page.waitForTimeout(300);
    const finished = await page.evaluate(() => window.backgroundProbe());
    assert(finished.watched === 'replay' && finished.replayX > switched.replayX, 'Remaining replay rollout was skipped');
    assert(Math.abs(finished.liveX - 90) < 1, 'Completed background pilot lost its final rollout position');
    await page.locator('#reset').click();
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    // Restart from a landed pose, as in the supplied video; only startup gets world-space easing.
    await page.evaluate(() => window.restartPose());
    await page.locator('#start').click();
    await page.waitForFunction(() => window.chaseProbe().distance > 100);
    await page.screenshot({path: `output/playwright/start-flyin-${page.viewportSize().width}.png`});
    await page.waitForTimeout(2100);
    const chase = await page.evaluate(() => window.chaseProbe());
    assert(Math.abs(chase.distance - chase.expected) < .5, 'Startup fly-in did not settle to stable chase');
    await page.screenshot({path: `output/playwright/start-settled-${page.viewportSize().width}.png`});
    await page.locator('#reset').click();
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.evaluate(() => window.restartPose());
    await page.locator('#start').click();
    await page.waitForFunction(() => document.querySelector('#flightStatePill').textContent === 'IN FLIGHT');
    await page.waitForTimeout(300);
    const reduced = await page.evaluate(() => window.chaseProbe());
    assert(Math.abs(reduced.distance - reduced.expected) < .1, 'Reduced motion still flies the camera in');
    await page.locator('#reset').click();
    assert(errors.length === 0, errors.join('\n'));
    return {backgrounds: 'live rollout and replay continue, background completion preserves camera, no rewind on handoff, final poses retained', start: 'fly-in then stable chase; reduced motion skips fly-in', errors};
  } finally {
    await page.emulateMedia({reducedMotion: 'no-preference'});
    await page.unroute('**/src/main.ts'); await page.goto(base);
  }
}

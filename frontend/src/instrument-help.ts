// Shared definitions for the viewport instruments and telemetry strip.
const TERMS: Record<string, [string, string, string, string]> = {
  HEADING: ["Aircraft heading", "Compass direction the watched aircraft's nose points toward, not its ground track or the camera direction.", "° true", "000° north · 090° east · 180° south · 270° west. The compass stays north-up."],
  AGL: ["Above ground level", "Height of the aircraft above the runway surface.", "m", "Zero is runway elevation, not sea level."],
  IAS: ["Indicated airspeed", "Speed through the air, as read by the aircraft's airspeed indicator.", "m/s", "Not ground speed: wind changes how fast you cross the ground."],
  "V/S": ["Vertical speed", "How quickly the aircraft is climbing or descending.", "m/s", "+ climb · − descent"],
  FPA: ["Flight path angle", "Angle of the aircraft's actual path above or below the horizon.", "°", "+ climb · − descent. This is not nose pitch."],
  OFFSET: ["Centerline offset", "Sideways distance from the runway's centerline.", "m", "+ right · − left, looking down the runway."],
  GLIDE: ["Glideslope error", "Difference from the target 3° approach path crossing the threshold at 15 m.", "°", "+ above path · − below path"],
  "HDG ERR": ["Heading error", "Difference between the aircraft's nose direction and runway heading.", "°", "+ right · − left. Crosswind may require a nonzero heading."],
  AOA: ["Angle of attack", "Angle between the wing's reference line and the oncoming airflow.", "°", "Different from pitch: a level-looking aircraft can still have high AoA."],
  AIL: ["Aileron", "Wing control surfaces that command roll and bank.", "−1…+1", "Applied control, not the model's pending request."],
  ELE: ["Elevator", "Tail control surface that commands nose pitch.", "−1…+1", "Applied control, not the aircraft's current pitch angle."],
  RUD: ["Rudder", "Vertical tail control surface that commands yaw.", "−1…+1", "Turns the nose left or right."],
  THR: ["Throttle", "Applied engine power command.", "0…1", "0 idle · 1 full power"],
  PHASE: ["Flight phase", "Current stage of the approach, touchdown or rollout.", "state", "Safe landing requires the rollout to finish, not just wheel contact."],
  ALONG: ["Along-runway position", "Distance along the runway axis, measured from its near threshold.", "m", "Negative before the threshold · positive down the runway."],
  THRESHOLD: ["Distance to threshold", "Forward distance remaining to the runway's near end.", "m", "Negative after crossing the threshold."],
  ROLL: ["Roll attitude", "Tilt of the wings relative to the horizon.", "°", "+ right bank · − left bank"],
  PITCH: ["Pitch attitude", "Angle of the aircraft's nose relative to the horizon.", "°", "+ nose up · − nose down"],
  WIND: ["Wind at the aircraft", "Observed wind: horizontal speed and the compass bearing it comes from.", "m/s · °", "HW headwind · XW crosswind · VW vertical wind. North is 0°."],
  "WIND FLOW": ["Downstream wind flow", "The arrow points where the air is going, just like the tail of the 3D windsock.", "m/s · °", "North up. “To” bearing; opposite the source bearing in the strip. Both visuals share a damped response to wind at the aircraft."],
  "MEAN LATENCY": ["Mean decision latency", "Average wall-clock time from sending a model request to receiving its response.", "ms", "1,000 milliseconds = 1 second. This is not simulation time."],
  "EFFECTIVE RATE": ["Effective decision rate", "Applied model decisions per second of wall-clock flight time, averaged over this run.", "Hz", "Hertz = decisions per second. Refreshed every five seconds; not a requested rate."],
  SCORE: ["Landing score · V2", "Approach precision, stability and touchdown quality on a 0–100 scale.", "points", "An unfinished or unsafe rollout scores zero. A safe landing can also round to zero after a very inaccurate approach."],
};

export function setupInstrumentHelp() {
  const tip = document.createElement("div");
  tip.id = "instrumentHelp"; tip.className = "instrument-help"; tip.role = "tooltip"; tip.hidden = true;
  const eyebrow = document.createElement("span"); eyebrow.className = "help-eyebrow"; eyebrow.textContent = "FLIGHT GUIDE";
  const title = document.createElement("strong"), description = document.createElement("p");
  const footer = document.createElement("div"), unit = document.createElement("span"), cue = document.createElement("span");
  footer.className = "help-footer"; unit.className = "help-unit";
  footer.append(unit, cue); tip.append(eyebrow, title, description, footer); document.body.append(tip);
  let active: HTMLElement | null = null;
  let leaveTimer: ReturnType<typeof setTimeout>;
  const hide = () => { clearTimeout(leaveTimer); active?.removeAttribute("aria-describedby"); active = null; tip.hidden = true; };
  const leave = () => { leaveTimer = setTimeout(() => {if (document.activeElement !== active) hide();}, 150); };
  tip.addEventListener("pointerenter", () => clearTimeout(leaveTimer));
  tip.addEventListener("pointerleave", leave);
  const show = (term: HTMLElement, definition: typeof TERMS[string]) => {
    hide(); active = term; term.setAttribute("aria-describedby", tip.id);
    [title.textContent, description.textContent, unit.textContent, cue.textContent] = definition;
    tip.hidden = false;
    const rect = term.getBoundingClientRect(), bounds = tip.getBoundingClientRect();
    tip.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - bounds.width - 8))}px`;
    const below = rect.bottom + 10;
    tip.style.top = `${Math.max(8, Math.min(below + bounds.height <= innerHeight - 8 ? below : rect.top - bounds.height - 10, innerHeight - bounds.height - 8))}px`;
  };
  for (const term of document.querySelectorAll<HTMLElement>(".hud-label, .hud-sub-label, .strip-label, .flight-readout-grid span, .wind-label, .instrument-label")) {
    const definition = TERMS[term.textContent!.trim().toUpperCase()];
    if (!definition) continue;
    term.classList.add("instrument-term"); term.tabIndex = 0;
    term.addEventListener("pointerenter", event => {
      // A resting pointer must not replace a keyboard-focused definition after layout changes.
      if (event.pointerType !== "touch" && !document.activeElement?.classList.contains("instrument-term")) show(term, definition);
    });
    term.addEventListener("pointerleave", leave);
    term.addEventListener("focus", () => show(term, definition));
    term.addEventListener("blur", hide);
    term.addEventListener("click", () => show(term, definition));
  }
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !tip.hidden) {event.stopImmediatePropagation(); hide();}
  });
  document.addEventListener("pointerdown", event => {if (active && !active.contains(event.target as Node) && !tip.contains(event.target as Node)) hide();});
  document.addEventListener("scroll", () => {
    if (active && document.activeElement === active) show(active, TERMS[active.textContent!.trim().toUpperCase()]);
    else hide();
  }, true);
  window.addEventListener("resize", hide);
}

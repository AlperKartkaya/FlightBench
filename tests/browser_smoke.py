"""Optional local UI smoke: Python with Playwright + Chrome, server running on 8000."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    output = Path(os.environ.get("FLIGHTBENCH_SCREENSHOTS", "/tmp/flightbench-smoke"))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get(
                "CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ),
            args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script("""
            window.WebSocket = class extends WebSocket {
                constructor(...args) { super(...args); window.testSocket = this; }
            };
        """)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        url = os.environ.get("FLIGHTBENCH_UI_URL", "http://127.0.0.1:8000")
        page.goto(url)
        expect(page.locator("#start")).to_be_enabled()
        expect(page.locator("#viewport")).to_be_visible()
        expect(page.locator(".profile-github")).to_have_attribute(
            "href", "https://github.com/alperkartkaya"
        )
        expect(page.locator(".profile-linkedin")).to_have_attribute(
            "href", "https://www.linkedin.com/in/alper-kartkaya-boun-cmpe"
        )
        assert page.locator("#review, #prepare, #observe").count() == 0
        assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
        expect(page.locator("#configPanel")).to_be_hidden()
        page.locator("#configureToggle").click()
        expect(page.locator("#configPanel")).to_be_visible()
        # Settings only: no provider requests are started by these selections.
        jev_options = page.locator('#controller option[value^="jev"]')
        expect(jev_options).to_have_count(1)
        assert page.locator("#scenario").count() == 0
        assert page.locator("#mode").count() == 0
        page.locator("#controller").select_option("jev")
        page.locator("#decisionRate").select_option("5")
        expect(page.locator("#configureToggle")).to_contain_text("Jev · 5 Hz")
        expect(page.locator("#liveDecisionCard")).to_be_visible()
        expect(page.locator("#overlayDecision")).to_be_visible()
        page.locator("#controller").select_option("codex")
        expect(page.locator("#ctrlBrandTitle")).to_have_text("Codex Controller")
        page.locator("#controller").select_option("baseline")
        page.locator("#decisionRate").select_option("2")
        page.locator("#configureToggle").click()
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        page.locator("#start").click()
        expect(page.locator("#controller")).to_be_disabled()
        expect(page.locator("#outcomeModal")).to_be_visible(timeout=90000)
        expect(page.locator("#outcomeTitle")).to_have_text("Safe landing")
        records = page.request.get(f"{url}/api/runs").json()["runs"]
        record = page.request.get(f"{url}/api/runs/{records[0]['run_id']}").json()
        assert record["config"]["scenario"] == "easy"
        assert record["config"]["mode"] == "realtime"
        td = record["outcome"]["touchdown"]
        assert record["outcome"]["success"]
        expect(page.locator("#outcomeIasVal")).to_contain_text(f"{td['airspeed_mps']:.1f}")
        page.screenshot(path=str(output / "result.png"), full_page=True)
        page.get_by_text("Close result", exact=True).click()
        page.locator("#configureToggle").click()
        page.locator("#controller").select_option("human")
        page.locator("#configureToggle").click()
        page.locator("#start").click()
        expect(page.locator("#stop")).to_be_enabled()
        page.locator("#stop").click()
        expect(page.locator("#outcomeModal")).to_be_visible()
        expect(page.locator("#outcomeTitle")).to_have_text("Interrupted")
        expect(page.locator("#outcomeIasVal")).to_have_text("N/A")
        page.get_by_text("Close result", exact=True).click()
        page.locator("#start").click()
        expect(page.locator("#stop")).to_be_enabled()
        expect(page.locator("#reset")).to_be_enabled()
        page.locator("#reset").click()
        expect(page.locator("#outcomeModal")).to_be_visible()
        expect(page.locator("#outcomeTitle")).to_have_text("Interrupted")
        page.get_by_text("Close result", exact=True).click()
        before = len(page.request.get(f"{url}/api/runs").json()["runs"])
        page.locator("#reset").click()
        page.reload()
        expect(page.locator("#start")).to_be_enabled()
        assert len(page.request.get(f"{url}/api/runs").json()["runs"]) == before
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#configureToggle").click()
        page.locator("#seed").fill("123")
        expect(page.locator("#seed")).to_have_value("123")
        page.locator("#configureToggle").click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            "page overflows horizontally"
        )
        assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        # Synthetic rendering checks only, not provider/inference evidence.
        commands = {
            axis: record["initial_observation"]["controls"][axis]
            for axis in ("aileron", "elevator", "rudder", "throttle")
        }
        frame = dict(record["final_state"])
        frame.update(type="state", run_id=None, decision_count=1, latency_ms=25)
        for call, controller in enumerate(("codex", "jev"), 1):
            page.locator("#configureToggle").click()
            page.locator("#controller").select_option(controller)
            page.locator("#configureToggle").click()
            info = {
                "controller": controller,
                "command": commands,
                "input": {"test": "synthetic UI fixture"},
                "live_status": {
                    "calls": call,
                    "cadence_hz": 2,
                    "is_deciding": False,
                    "api_errors": 0,
                    "stale_decisions": 0,
                    "late_decisions": 0,
                    "latency_ms": 25,
                    "state_age_ms": 5,
                    "effective_decision_hz": 1.4,
                },
                "timing": {"applied": controller != "jev"},
            }
            if controller == "jev":
                info.update(
                    policy="direct-categorical",
                    input={
                        "phase": "APPROACH",
                        "time_s": 0.5,
                        "flight": {
                            "airspeed_mps": 33.4,
                            "vertical_speed_mps": -1.8,
                            "roll_deg": 1.2,
                            "pitch_deg": -1.0,
                        },
                        "runway": {
                            "altitude_agl_m": 45.0,
                            "centerline_offset_m": 1.5,
                            "glideslope_error_deg": -0.2,
                            "heading_error_deg": 0.4,
                        },
                        "current_controls": commands,
                        "motion": {"cross_track_rate_mps": 0.3},
                        "status": {"on_ground": False},
                    },
                    choices={
                        axis: {
                            "choice": "0",
                            "command": value,
                            "confidence": 0.5,
                            "label": "Only with bank between -3 and +3 degrees: gentle LEFT roll, moving RIGHT faster than +0.5 m/s"
                            if axis == "aileron"
                            else "Normal approach command: maintain descent",
                        }
                        for axis, value in commands.items()
                    },
                )
            frame["decision_info"] = info
            frame["decision_count"] = call
            page.evaluate(
                "message => window.testSocket.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(message)}))",
                frame,
            )
            expect(page.locator("#topProbBars p")).to_have_count(4)
            expect(page.locator("#topProbBars")).to_contain_text("elevator: 0.170")
            expect(page.locator("#jointDecisionCard .ctrl-card-title")).to_have_text(
                "Jev actuator decisions" if controller == "jev" else "Codex actuator decisions"
            )
            expect(page.locator("#decisionSequence")).to_have_text(f"#{call}")
            expect(page.locator("#effectiveRate")).to_have_text("1.4 Hz")
            expect(page.locator("#overlayDecisionText")).to_contain_text("E 0.17")
            expect(page.locator("#decisionState")).to_have_text(
                "DISCARDED" if controller == "jev" else "APPLIED"
            )
        expect(page.locator("#decisionInputFlight")).to_contain_text("IAS 33.4")
        assert page.evaluate("""() => {
            const label = document.querySelector('#decisionInputFlight').previousElementSibling;
            const value = document.querySelector('#decisionInputFlight');
            return label.getBoundingClientRect().bottom <= value.getBoundingClientRect().top;
        }""")
        assert page.locator(".decision-updated").count() == 0
        expect(page.locator("#decisionAileron")).to_contain_text("gentle LEFT roll")
        expect(page.locator("#decisionAileronChange")).to_have_text("FIRST")
        sizes = page.evaluate("""() => ['.workspace', '.hud-panel', '#ctrlIdentityCard', '#liveDecisionCard', '#actuatorRows']
            .map(selector => document.querySelector(selector).getBoundingClientRect().height)""")
        frame["decision_info"]["live_status"].update(calls=3, is_deciding=True, latency_ms=9999)
        frame["decision_info"]["input"]["flight"]["airspeed_mps"] = 27.0
        frame["decision_info"]["choices"]["aileron"]["label"] = (
            "Only with bank between -3 and +3 degrees: gentle RIGHT roll, moving LEFT"
        )
        frame["decision_info"]["choices"]["aileron"]["choice"] = "4"
        frame["decision_info"]["choices"]["aileron"]["command"] = 0.05
        frame["decision_info"]["command"]["aileron"] = 0.05
        frame["decision_info"]["timing"]["applied"] = True
        frame["decision_count"] = 3
        page.evaluate(
            "message => window.testSocket.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(message)}))",
            frame,
        )
        expect(page.locator("#decisionInputFlight")).to_contain_text("IAS 27.0")
        expect(page.locator("#decisionAileron")).to_contain_text("gentle RIGHT roll")
        expect(page.locator("#decisionAileronValue")).to_have_text("0.050")
        expect(page.locator("#decisionAileronChange")).to_contain_text("CHANGED")
        expect(page.locator("#decisionElevatorChange")).to_have_text("SAME")
        expect(page.locator("#decisionState")).to_have_text("APPLIED")
        assert sizes == page.evaluate("""() => ['.workspace', '.hud-panel', '#ctrlIdentityCard', '#liveDecisionCard', '#actuatorRows']
            .map(selector => document.querySelector(selector).getBoundingClientRect().height)""")
        assert not errors, errors
        assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
        # Capture only the outbound config: do not make a Codex provider request.
        page.locator("#configureToggle").click()
        page.locator("#controller").select_option("codex")
        page.locator("#configureToggle").click()
        page.evaluate("""() => {
            const model = document.querySelector('#model');
            model.add(new Option('Mock Codex', 'openai-codex/mock'));
            model.value = 'openai-codex/mock';
            window.testSocket.send = raw => { window.testStart = JSON.parse(raw); };
        }""")
        page.locator("#start").click()
        assert page.evaluate("window.testStart.mode") == "lockstep"
        assert page.evaluate("window.testStart.scenario") == "easy"
        browser.close()
        print(
            f"PASS: single-screen viewer, settings, baseline, touchdown, stop/reset, Jev decision rendering, mobile; {output}"
        )


if __name__ == "__main__":
    main()

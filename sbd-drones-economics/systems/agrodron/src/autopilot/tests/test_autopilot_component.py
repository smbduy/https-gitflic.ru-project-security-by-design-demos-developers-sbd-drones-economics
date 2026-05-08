import os

from components.bus_mock import MockSystemBus
from components.autopilot.src.autopilot import AutopilotComponent
from components.autopilot import config

SM_TOPIC = config.security_monitor_topic()


def _make_component() -> AutopilotComponent:
    bus = MockSystemBus()
    return AutopilotComponent(component_id="autopilot_test", bus=bus)


def test_mission_load_and_start():
    saved = {k: os.environ.pop(k, None) for k in ("ORVD_TOPIC", "DRONEPORT_TOPIC")}
    try:
        _run_mission_load_and_start()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _run_mission_load_and_start():
    comp = _make_component()

    mission = {"mission_id": "m1", "steps": []}
    msg = {
        "action": "mission_load",
        "sender": SM_TOPIC,
        "payload": {"mission": mission},
    }
    result = comp._handle_mission_load(msg)
    assert result and result["ok"]

    cmd_msg = {
        "action": "cmd",
        "sender": SM_TOPIC,
        "payload": {"command": "START"},
    }
    cmd_result = comp._handle_cmd(cmd_msg)
    assert cmd_result and cmd_result["ok"]
    state = comp._handle_get_state({"action": "get_state"})
    assert state["state"] == "EXECUTING"


def test_poll_navigation_unwraps_nested_proxy_response():
    comp = _make_component()
    nav_state = {"lat": 60.0, "lon": 30.0, "alt_m": 10.0, "heading_deg": 90.0}

    comp.bus.request = lambda *args, **kwargs: {
        "success": True,
        "payload": {
            "target_response": {
                "success": True,
                "payload": {
                    "nav_state": nav_state,
                    "payload": nav_state,
                },
            },
        },
    }

    comp._poll_navigation_if_due()

    assert comp._last_nav_state == nav_state


def test_request_departure_orvd_unwraps_nested_proxy_response():
    saved_orvd_topic = os.environ.get("ORVD_TOPIC")
    os.environ["ORVD_TOPIC"] = "v1.ORVD.ORVD001.main"
    try:
        comp = _make_component()

        comp.bus.request = lambda *args, **kwargs: {
            "success": True,
            "payload": {
                "target_response": {
                    "success": True,
                    "payload": {
                        "status": "takeoff_authorized",
                        "mission_id": "m1",
                    },
                },
            },
        }

        assert comp._request_departure_orvd("m1") is True
    finally:
        if saved_orvd_topic is None:
            os.environ.pop("ORVD_TOPIC", None)
        else:
            os.environ["ORVD_TOPIC"] = saved_orvd_topic

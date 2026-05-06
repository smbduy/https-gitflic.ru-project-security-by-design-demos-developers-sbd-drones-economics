import os
import math
from unittest.mock import MagicMock

from systems.agrodron.src.bus_mock import MockSystemBus
from systems.agrodron.src.autopilot.src.autopilot import AutopilotComponent
from systems.agrodron.src.autopilot import config

SM_TOPIC = config.security_monitor_topic()


def _make_component() -> AutopilotComponent:
    bus = MockSystemBus()
    return AutopilotComponent(component_id="autopilot_test", bus=bus)


def _clear_env():
    """Очищает env-переменные, влияющие на ORVD/DronePort."""
    saved = {k: os.environ.pop(k, None) for k in (
        "ORVD_TOPIC",
        "DRONEPORT_TOPIC",
        "AUTOPILOT_ORVD_MOCK_SUCCESS",
        "AUTOPILOT_DRONEPORT_MOCK_SUCCESS",
        "NUS_TOPIC",
    )}
    return saved


def _restore_env(saved):
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def test_mission_load_and_start():
    saved = _clear_env()
    try:
        _run_mission_load_and_start()
    finally:
        _restore_env(saved)


def test_start_with_orvd_topic_uses_mock_without_real_orvd():
    saved = _clear_env()
    try:
        os.environ["ORVD_TOPIC"] = "v1.ORVD.ORVD001.main"
        os.environ["AUTOPILOT_ORVD_MOCK_SUCCESS"] = "1"
        _run_mission_load_and_start()
    finally:
        _restore_env(saved)


def test_start_with_droneport_topic_uses_mock_without_real_droneport():
    saved = _clear_env()
    try:
        os.environ["DRONEPORT_TOPIC"] = "v1.drone_port.1.drone_manager"
        os.environ["AUTOPILOT_DRONEPORT_MOCK_SUCCESS"] = "1"
        _run_mission_load_and_start()
    finally:
        _restore_env(saved)


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


def test_mission_landing_finishes_and_returns_to_idle() -> None:
    comp = _make_component()
    comp._mission = {"mission_id": "m-land-1", "steps": [{"lat": 55.0, "lon": 37.0, "alt_m": 5.0}]}
    comp._state = "LANDING"
    comp._landing_active = True
    comp._last_nav_state = {"lat": 55.0, "lon": 37.0, "alt_m": 0.2, "heading_deg": 90.0}

    comp._step_control()

    state = comp._handle_get_state({"action": "get_state"})
    assert state["state"] == "IDLE"
    assert state["mission_id"] is None


# ----------------------------------------------------------- new tests


def test_mission_load_rejects_untrusted_sender():
    comp = _make_component()
    msg = {
        "action": "mission_load",
        "sender": "bad_sender",
        "payload": {"mission": {"mission_id": "m1", "steps": []}},
    }
    result = comp._handle_mission_load(msg)
    assert result is None


def test_mission_load_invalid_mission():
    comp = _make_component()
    msg = {
        "action": "mission_load",
        "sender": SM_TOPIC,
        "payload": {"mission": "not_a_dict"},
    }
    result = comp._handle_mission_load(msg)
    assert result is not None
    assert result["ok"] is False
    assert result["error"] == "invalid_mission"


def test_cmd_start_without_mission():
    comp = _make_component()
    msg = {
        "action": "cmd",
        "sender": SM_TOPIC,
        "payload": {"command": "START"},
    }
    result = comp._handle_cmd(msg)
    assert result["ok"] is False
    assert result["error"] == "no_mission"


def test_cmd_start_invalid_state():
    comp = _make_component()
    comp._mission = {"mission_id": "m1", "steps": []}
    comp._state = "EXECUTING"
    msg = {
        "action": "cmd",
        "sender": SM_TOPIC,
        "payload": {"command": "START"},
    }
    result = comp._handle_cmd(msg)
    assert result["ok"] is False
    assert "invalid_state" in result["error"]


def test_cmd_pause():
    comp = _make_component()
    comp._state = "EXECUTING"
    msg = {"action": "cmd", "sender": SM_TOPIC, "payload": {"command": "PAUSE"}}
    result = comp._handle_cmd(msg)
    assert result["ok"] is True
    assert result["state"] == "PAUSED"


def test_cmd_resume():
    comp = _make_component()
    comp._state = "PAUSED"
    msg = {"action": "cmd", "sender": SM_TOPIC, "payload": {"command": "RESUME"}}
    result = comp._handle_cmd(msg)
    assert result["ok"] is True
    assert result["state"] == "EXECUTING"


def test_cmd_abort():
    comp = _make_component()
    comp._state = "EXECUTING"
    msg = {"action": "cmd", "sender": SM_TOPIC, "payload": {"command": "ABORT"}}
    result = comp._handle_cmd(msg)
    assert result["ok"] is True
    assert result["state"] == "ABORTED"


def test_cmd_reset():
    comp = _make_component()
    comp._mission = {"mission_id": "m1", "steps": []}
    comp._state = "ABORTED"
    msg = {"action": "cmd", "sender": SM_TOPIC, "payload": {"command": "RESET"}}
    result = comp._handle_cmd(msg)
    assert result["ok"] is True
    assert result["state"] == "IDLE"
    assert comp._mission is None


def test_cmd_emergency_stop():
    comp = _make_component()
    comp._state = "EXECUTING"
    msg = {"action": "cmd", "sender": SM_TOPIC, "payload": {"command": "EMERGENCY_STOP"}}
    result = comp._handle_cmd(msg)
    assert result["ok"] is True
    assert result["state"] == "EMERGENCY_STOP"


def test_cmd_kover():
    comp = _make_component()
    comp._state = "EXECUTING"
    msg = {"action": "cmd", "sender": SM_TOPIC, "payload": {"command": "KOVER"}}
    result = comp._handle_cmd(msg)
    assert result["ok"] is True
    assert comp._kover_active is True


def test_cmd_unknown():
    comp = _make_component()
    msg = {"action": "cmd", "sender": SM_TOPIC, "payload": {"command": "UNKNOWN_CMD"}}
    result = comp._handle_cmd(msg)
    assert result["ok"] is False
    assert result["error"] == "unknown_command"


def test_cmd_rejects_untrusted():
    comp = _make_component()
    msg = {"action": "cmd", "sender": "bad_sender", "payload": {"command": "START"}}
    result = comp._handle_cmd(msg)
    assert result is None


def test_get_state_structure():
    comp = _make_component()
    comp._mission = {"mission_id": "m1", "steps": [{"lat": 1.0, "lon": 2.0, "alt_m": 3.0}]}
    comp._current_step_index = 0

    state = comp._handle_get_state({"action": "get_state"})
    assert state["state"] == "IDLE"
    assert state["mission_id"] == "m1"
    assert state["current_step_index"] == 0
    assert state["total_steps"] == 1
    assert state["sprayer_state"] == "OFF"


def test_is_trusted_sender():
    assert AutopilotComponent._is_trusted_sender({"sender": SM_TOPIC}) is True
    assert AutopilotComponent._is_trusted_sender({"sender": "other"}) is False
    assert AutopilotComponent._is_trusted_sender({}) is False


def test_step_control_no_nav_state():
    comp = _make_component()
    comp._last_nav_state = None
    # Не должно упасть
    comp._step_control()


def test_step_control_kover_landing():
    """KOVER: при достижении земли — переход в PAUSED."""
    comp = _make_component()
    comp._state = "EXECUTING"
    comp._kover_active = True
    comp._last_nav_state = {"lat": 55.0, "lon": 37.0, "alt_m": 0.3, "heading_deg": 0.0}

    comp._step_control()

    assert comp._kover_active is False
    assert comp._state == "PAUSED"


def test_step_control_kover_still_flying():
    """KOVER: при alt > 0.5 — продолжаем снижение."""
    comp = _make_component()
    comp._state = "EXECUTING"
    comp._kover_active = True
    comp._last_nav_state = {"lat": 55.0, "lon": 37.0, "alt_m": 10.0, "heading_deg": 0.0}

    comp._step_control()

    assert comp._kover_active is True


def test_compute_velocity_vectors_level_flight():
    comp = _make_component()
    vx, vy, vz = comp._compute_velocity_vectors(
        heading_deg=90.0,
        ground_speed_mps=5.0,
        current_alt=100.0,
        target_alt=100.0,
    )
    assert abs(vz) < 0.01  # Горизонтальный полёт


def test_compute_velocity_vectors_climb():
    comp = _make_component()
    vx, vy, vz = comp._compute_velocity_vectors(
        heading_deg=0.0,
        ground_speed_mps=5.0,
        current_alt=50.0,
        target_alt=100.0,
    )
    assert vz > 0  # Набор высоты


def test_compute_velocity_vectors_descend():
    comp = _make_component()
    vx, vy, vz = comp._compute_velocity_vectors(
        heading_deg=0.0,
        ground_speed_mps=5.0,
        current_alt=100.0,
        target_alt=50.0,
    )
    assert vz < 0  # Снижение


def test_send_motors_target_publishes():
    comp = _make_component()
    bus = comp.bus
    comp._send_motors_target(
        vx=1.0, vy=2.0, vz=0.0,
        alt_m=100.0, lat=55.0, lon=37.0,
        heading_deg=90.0, drop=False,
    )
    sm_topic = config.security_monitor_topic()
    published = [m for t, m in bus.published if t == sm_topic]
    assert len(published) == 1
    assert published[0]["action"] == "proxy_publish"


def test_send_sprayer():
    comp = _make_component()
    bus = comp.bus
    comp._send_sprayer(True)
    assert comp._sprayer_state == "ON"

    comp._send_sprayer(False)
    assert comp._sprayer_state == "OFF"


def test_step_control_landing_waiting_port():
    """LANDING: ожидание подтверждения DronePort."""
    saved = _clear_env()
    try:
        os.environ["DRONEPORT_TOPIC"] = "v1.drone_port.1.drone_manager"
        os.environ["AUTOPILOT_DRONEPORT_MOCK_SUCCESS"] = "0"

        comp = _make_component()
        comp._state = "LANDING"
        comp._landing_active = True
        comp._landing_port_confirmed = False
        comp._last_nav_state = {"lat": 55.0, "lon": 37.0, "alt_m": 50.0, "heading_deg": 90.0}

        # Мокируем request для DronePort
        comp.bus.request = MagicMock(return_value=None)

        comp._step_control()
        # Должен остаться в LANDING, ожидая порт
        assert comp._state == "LANDING"
    finally:
        _restore_env(saved)


def test_droneport_battery_pct_from_nav():
    comp = _make_component()
    comp._last_nav_state = {"battery_pct": 85.0}
    assert comp._droneport_battery_pct(default=50.0) == 85.0


def test_droneport_battery_pct_default():
    comp = _make_component()
    comp._last_nav_state = {}
    assert comp._droneport_battery_pct(default=50.0) == 50.0


def test_self_diagnostics():
    comp = _make_component()
    assert comp._self_diagnostics() is True


def test_unwrap_droneport_response_with_port_id():
    resp = {"port_id": "p1", "battery": 80.0}
    result = AutopilotComponent._unwrap_droneport_response(resp)
    assert result is not None
    assert result["port_id"] == "p1"


def test_unwrap_droneport_response_with_error():
    resp = {"error": "port_full"}
    result = AutopilotComponent._unwrap_droneport_response(resp)
    assert result is not None
    assert result["error"] == "port_full"


def test_unwrap_droneport_response_nested():
    resp = {
        "payload": {
            "target_response": {
                "port_id": "p1",
            },
        },
    }
    result = AutopilotComponent._unwrap_droneport_response(resp)
    assert result is not None
    assert result["port_id"] == "p1"


def test_unwrap_droneport_response_none():
    result = AutopilotComponent._unwrap_droneport_response(None)
    assert result is None


def test_droneport_takeoff_ok():
    resp = {"port_id": "p1", "battery": 95.0}
    comp = _make_component()
    assert comp._droneport_takeoff_ok(resp) is True


def test_droneport_takeoff_ok_denied():
    resp = {"error": "port_unavailable"}
    comp = _make_component()
    assert comp._droneport_takeoff_ok(resp) is False


def test_droneport_landing_ok():
    resp = {"port_id": "p1"}
    comp = _make_component()
    assert comp._droneport_landing_ok(resp) is True


def test_droneport_landing_ok_denied():
    resp = {"error": "port_full"}
    comp = _make_component()
    assert comp._droneport_landing_ok(resp) is False


def test_notify_nus_publishes():
    saved = _clear_env()
    try:
        os.environ["NUS_TOPIC"] = "v1.nus.main"
        comp = _make_component()
        bus = comp.bus
        comp._notify_nus("test_event", {"key": "val"})

        sm_topic = config.security_monitor_topic()
        published = [m for t, m in bus.published if t == sm_topic]
        assert len(published) == 1
    finally:
        _restore_env(saved)


def test_notify_nus_no_topic():
    saved = _clear_env()
    try:
        comp = _make_component()
        bus = comp.bus
        comp._notify_nus("test_event", {"key": "val"})
        # NUS_TOPIC не задан — публикация не происходит
        assert len(bus.published) == 0
    finally:
        _restore_env(saved)

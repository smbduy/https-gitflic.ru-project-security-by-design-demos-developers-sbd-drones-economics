"""Unit-тесты компонента navigation."""
import time
from unittest.mock import MagicMock, patch

import pytest

from systems.agrodron.src.bus_mock import MockSystemBus
from systems.agrodron.src.navigation import config
from systems.agrodron.src.navigation.src.navigation import NavigationComponent


SM_TOPIC = config.security_monitor_topic()


def _make_component() -> NavigationComponent:
    bus = MockSystemBus()
    return NavigationComponent(
        component_id="navigation_test",
        bus=bus,
        topic=config.component_topic(),
    )


# ------------------------------------------------------------------ handlers


def test_nav_state_and_get_state():
    comp = _make_component()

    nav_payload = {
        "lat": 60.123450,
        "lon": 30.123400,
        "alt_m": 4.9,
        "ground_speed_mps": 4.8,
        "heading_deg": 90.0,
        "fix": "3D",
        "satellites": 14,
        "hdop": 0.7,
    }
    msg = {
        "action": "nav_state",
        "sender": SM_TOPIC,
        "payload": nav_payload,
    }
    result = comp._handle_nav_state(msg)
    assert result and result["ok"]

    state_msg = {"action": "get_state", "sender": SM_TOPIC, "payload": {}}
    state = comp._handle_get_state(state_msg)
    assert state is not None
    assert state["nav_state"] is not None
    assert state["nav_state"]["lat"] == nav_payload["lat"]


def test_nav_state_rejects_untrusted_sender():
    comp = _make_component()
    msg = {
        "action": "nav_state",
        "sender": "untrusted_sender",
        "payload": {"lat": 1.0, "lon": 2.0},
    }
    result = comp._handle_nav_state(msg)
    assert result is None


def test_nav_state_invalid_payload():
    comp = _make_component()
    msg = {
        "action": "nav_state",
        "sender": SM_TOPIC,
        "payload": "not_a_dict",
    }
    result = comp._handle_nav_state(msg)
    assert result is not None
    assert result["ok"] is False


def test_get_state_rejects_untrusted():
    comp = _make_component()
    msg = {"action": "get_state", "sender": "bad_sender", "payload": {}}
    result = comp._handle_get_state(msg)
    assert result is None


def test_handle_update_config():
    comp = _make_component()
    new_config_params = {
        "poll_interval_s": 0.5,
        "request_timeout_s": 2.0,
    }
    message = {
        "payload": new_config_params,
        "sender": SM_TOPIC,
    }
    result = comp._handle_update_config(message)
    assert result is not None
    assert result["ok"] is True
    assert "poll_interval_s" in result["config"]


def test_handle_update_config_rejects_untrusted():
    comp = _make_component()
    message = {
        "payload": {"poll_interval_s": 0.5},
        "sender": "bad_sender",
    }
    result = comp._handle_update_config(message)
    assert result is None


def test_handle_update_config_invalid_payload():
    comp = _make_component()
    message = {
        "payload": "invalid",
        "sender": SM_TOPIC,
    }
    result = comp._handle_update_config(message)
    assert result is not None
    assert result["ok"] is False


# ---------------------------------------------------------------- lifecycle


def test_lifecycle_start_stop():
    comp = _make_component()
    assert comp._running is False

    comp.start()
    time.sleep(0.3)
    assert comp._running is True

    comp.stop()
    time.sleep(0.1)
    assert comp._running is False


# ----------------------------------------------------------------- SITL poll


def test_poll_sitl_once_success():
    comp = _make_component()
    bus = comp.bus

    mock_data = {
        "lat": 55.75, "lon": 37.61, "alt": 100.0,
        "vx": 1.0, "vy": 2.0, "vz": 0.0,
        "heading": 90.0, "gps_fix_type": 3, "satellites_visible": 10,
    }

    original_request = bus.request
    bus.request = MagicMock(return_value={
        "payload": {
            "target_response": {
                "payload": mock_data,
            },
        },
    })

    try:
        comp._poll_sitl_once()
        assert comp._last_nav_state is not None
        assert comp._last_nav_state["lat"] == 55.75

        nav_topic = config.agrodron_nav_state_topic()
        published = [m for t, m in bus.published if t == nav_topic]
        assert len(published) > 0, "Данные не были опубликованы в шину"
    finally:
        bus.request = original_request


def test_poll_sitl_none_response():
    comp = _make_component()
    bus = comp.bus

    original_request = bus.request
    bus.request = MagicMock(return_value=None)

    try:
        comp._poll_sitl_once()
        # Не должно упасть, состояние не обновляется
        assert True
    finally:
        bus.request = original_request


def test_poll_sitl_error_handling():
    """Исключение в _request_sitl_state пробрасывается из _poll_sitl_once,
    но ловится в _housekeeping_loop."""
    comp = _make_component()
    bus = comp.bus

    original_request = bus.request
    bus.request = MagicMock(side_effect=ConnectionError("SITL unreachable"))

    try:
        # _poll_sitl_once НЕ ловит исключения — они всплывают в _housekeeping_loop
        with pytest.raises(ConnectionError):
            comp._poll_sitl_once()
    finally:
        bus.request = original_request


# --------------------------------------------------------- publish / helpers


def test_publish_nav_state_adds_drone_id():
    comp = _make_component()
    bus = comp.bus
    comp._config = {"drone_id": "drone_001"}

    nav_state = {"lat": 55.0, "lon": 37.0, "alt_m": 100.0}
    comp._publish_nav_state(nav_state)

    nav_topic = config.agrodron_nav_state_topic()
    published = [m for t, m in bus.published if t == nav_topic]
    assert len(published) == 1
    assert published[0]["drone_id"] == "drone_001"


def test_publish_nav_state_without_drone_id():
    comp = _make_component()
    bus = comp.bus
    comp._config = {}

    nav_state = {"lat": 55.0, "lon": 37.0, "alt_m": 100.0}
    comp._publish_nav_state(nav_state)

    nav_topic = config.agrodron_nav_state_topic()
    published = [m for t, m in bus.published if t == nav_topic]
    assert len(published) == 1
    assert "drone_id" not in published[0]


def test_is_trusted_sender():
    assert NavigationComponent._is_trusted_sender({"sender": SM_TOPIC}) is True
    assert NavigationComponent._is_trusted_sender({"sender": "other"}) is False
    assert NavigationComponent._is_trusted_sender({}) is False
    assert NavigationComponent._is_trusted_sender({"sender": 123}) is False


def test_log_gps_degraded():
    comp = _make_component()
    bus = comp.bus

    nav_state = {"lat": 0.0, "lon": 0.0, "alt_m": 0.0}
    comp._log_gps_degraded(nav_state)

    sm_topic = config.security_monitor_topic()
    published = [m for t, m in bus.published if t == sm_topic]
    assert len(published) == 1
    payload = published[0]["payload"]
    assert payload["data"]["event"] == "NAVIGATION_GPS_DEGRADED"


def test_request_sitl_state_returns_raw():
    comp = _make_component()
    bus = comp.bus

    mock_raw = {"lat": 55.0, "lon": 37.0, "alt": 100.0, "vx": 1.0}
    original_request = bus.request
    bus.request = MagicMock(return_value={
        "payload": {
            "target_response": {
                "payload": mock_raw,
            },
        },
    })

    try:
        result = comp._request_sitl_state()
        assert result is not None
        assert result["lat"] == 55.0
    finally:
        bus.request = original_request


def test_request_sitl_state_returns_none_on_bad_response():
    comp = _make_component()
    bus = comp.bus

    original_request = bus.request
    bus.request = MagicMock(return_value={"unexpected": True})

    try:
        result = comp._request_sitl_state()
        assert result is None
    finally:
        bus.request = original_request


# -------------------------------------------------------- housekeeping loop


def test_housekeeping_loop_integration():
    comp = _make_component()
    bus = comp.bus

    mock_data = {
        "lat": 0.0, "lon": 0.0, "alt": 50.0,
        "gps_fix_type": 3, "heading": 0,
        "vx": 0, "vy": 0, "vz": 0, "satellites_visible": 4,
    }

    original_request = bus.request
    bus.request = MagicMock(return_value={
        "payload": {
            "target_response": {
                "payload": mock_data,
            },
        },
    })

    try:
        comp.start()
        time.sleep(1.5)
        comp.stop()
        time.sleep(0.1)

        nav_topic = config.agrodron_nav_state_topic()
        published = [m for t, m in bus.published if t == nav_topic]
        assert len(published) >= 1, f"Цикл не отработал ни разу за 1.5 сек"
    finally:
        bus.request = original_request

"""Unit-тесты компонента gateway (AgrodronGateway)."""
import os
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from broker.system_bus import SystemBus
from systems.agrodron.src.gateway.src.gateway import AgrodronGateway
from systems.agrodron.src.gateway.topics import ComponentTopics, GatewayActions, SystemTopics


class MockGatewayBus(SystemBus):
    """Мок шины для тестов gateway."""

    def __init__(self, response: Optional[Dict[str, Any]] = None) -> None:
        self.published: list = []
        self._response = response
        self.requests: list = []

    def publish(self, topic: str, message: Dict[str, Any]) -> bool:
        self.published.append((topic, message))
        return True

    def subscribe(self, topic: str, callback) -> bool:
        return True

    def unsubscribe(self, topic: str) -> bool:
        return True

    def request(
        self,
        topic: str,
        message: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        self.requests.append((topic, message))
        return self._response

    def request_async(self, topic, message, timeout=30.0):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        fut = loop.create_future()
        fut.set_result(self.request(topic, message, timeout))
        return fut

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _make_gateway(bus: Optional[MockGatewayBus] = None) -> AgrodronGateway:
    if bus is None:
        bus = MockGatewayBus()
    return AgrodronGateway(
        system_id="gateway_test",
        bus=bus,
        health_port=None,
    )


# ------------------------------------------------------------------ helpers


def test_extract_sender_from_message():
    gw = _make_gateway()
    assert gw._extract_sender({"sender": "test_sender"}) == "test_sender"


def test_extract_sender_empty():
    gw = _make_gateway()
    assert gw._extract_sender({"sender": ""}) == gw._default_sender


def test_extract_sender_missing():
    gw = _make_gateway()
    assert gw._extract_sender({}) == gw._default_sender


def test_extract_sender_whitespace():
    gw = _make_gateway()
    assert gw._extract_sender({"sender": "   "}) == gw._default_sender


def test_extract_mission_payload():
    payload = {"mission_id": "m1", "wpl_content": "QGC WPL 110"}
    mid, wpl = AgrodronGateway._extract_mission_payload(payload)
    assert mid == "m1"
    assert wpl == "QGC WPL 110"


def test_extract_mission_payload_missing():
    payload = {}
    mid, wpl = AgrodronGateway._extract_mission_payload(payload)
    assert mid is None
    assert wpl is None


def test_unwrap_target_response_nested():
    response = {
        "target_response": {
            "ok": True,
            "state": "LOADED",
        },
    }
    result = AgrodronGateway._unwrap_target_response(response)
    assert result["ok"] is True


def test_unwrap_target_response_in_payload():
    response = {
        "payload": {
            "target_response": {
                "ok": True,
                "state": "LOADED",
            },
        },
    }
    result = AgrodronGateway._unwrap_target_response(response)
    assert result["ok"] is True


def test_unwrap_target_response_fallback():
    """Если нет target_response — возвращаем исходный dict."""
    response = {"ok": True, "state": "IDLE"}
    result = AgrodronGateway._unwrap_target_response(response)
    assert result == response


# ----------------------------------------------------------- proxy_request


def test_proxy_request_success():
    bus = MockGatewayBus(response={
        "target_response": {"ok": True, "state": "LOADED"},
    })
    gw = _make_gateway(bus)

    result = gw._proxy_request(
        "sender1",
        ComponentTopics.MISSION_HANDLER,
        GatewayActions.LOAD_MISSION,
        {"mission_id": "m1"},
    )
    assert isinstance(result, dict)
    assert bus.requests


def test_proxy_request_unavailable():
    bus = MockGatewayBus(response=None)
    gw = _make_gateway(bus)

    result = gw._proxy_request(
        "sender1",
        ComponentTopics.SECURITY_MONITOR,
        "test_action",
        {},
    )
    assert result["ok"] is False
    assert result["error"] == "security_monitor_unavailable"


def test_proxy_request_sends_correct_message():
    bus = MockGatewayBus(response={"ok": True})
    gw = _make_gateway(bus)

    gw._proxy_request("my_sender", "target_topic", "target_action", {"key": "val"})

    assert len(bus.requests) == 1
    topic, msg = bus.requests[0]
    assert topic == ComponentTopics.SECURITY_MONITOR
    assert msg["action"] == "proxy_request"
    assert msg["sender"] == "my_sender"
    assert msg["payload"]["target"]["topic"] == "target_topic"
    assert msg["payload"]["target"]["action"] == "target_action"
    assert msg["payload"]["data"] == {"key": "val"}


# ------------------------------------------------------------- handlers


def test_handle_load_mission():
    bus = MockGatewayBus(response={
        "target_response": {"ok": True, "state": "LOADED", "mission_id": "m1"},
    })
    gw = _make_gateway(bus)

    message = {
        "sender": "external_system",
        "payload": {
            "mission_id": "m1",
            "wpl_content": "QGC WPL 110\n0\t1\t...",
        },
    }
    result = gw._handle_load_mission(message)
    assert result["ok"] is True


def test_handle_validate_only():
    bus = MockGatewayBus(response={
        "target_response": {"ok": True, "valid": True},
    })
    gw = _make_gateway(bus)

    message = {
        "sender": "external_system",
        "payload": {
            "mission_id": "m2",
            "wpl_content": "QGC WPL 110\n0\t1\t...",
        },
    }
    result = gw._handle_validate_only(message)
    assert result["ok"] is True


def test_handle_cmd():
    bus = MockGatewayBus(response={
        "target_response": {"ok": True, "state": "EXECUTING"},
    })
    gw = _make_gateway(bus)

    message = {
        "sender": "external_system",
        "payload": {"command": "START"},
    }
    result = gw._handle_cmd(message)
    assert result["ok"] is True


def test_handle_get_state():
    bus = MockGatewayBus(response={
        "target_response": {
            "state": "EXECUTING",
            "mission_id": "m1",
        },
    })
    gw = _make_gateway(bus)

    message = {
        "sender": "external_system",
        "payload": {},
    }
    result = gw._handle_get_state(message)
    assert result["state"] == "EXECUTING"


def test_handle_load_mission_empty_payload():
    bus = MockGatewayBus(response={"target_response": {}})
    gw = _make_gateway(bus)

    message = {"sender": "ext", "payload": {}}
    result = gw._handle_load_mission(message)
    # Не должно упасть
    assert isinstance(result, dict)


def test_handle_load_mission_no_sender():
    bus = MockGatewayBus(response={
        "target_response": {"ok": True},
    })
    gw = _make_gateway(bus)

    message = {"payload": {"mission_id": "m1"}}
    result = gw._handle_load_mission(message)
    # Используется default_sender
    assert bus.requests


def test_default_sender_from_env(monkeypatch):
    monkeypatch.setenv("AGRODRON_GATEWAY_SENDER", "custom_sender")
    gw = _make_gateway()
    assert gw._default_sender == "custom_sender"


def test_default_sender_fallback_nus(monkeypatch):
    monkeypatch.delenv("AGRODRON_GATEWAY_SENDER", raising=False)
    monkeypatch.setenv("NUS_TOPIC", "nus_topic_val")
    gw = _make_gateway()
    assert gw._default_sender == "nus_topic_val"


def test_default_sender_fallback_default(monkeypatch):
    monkeypatch.delenv("AGRODRON_GATEWAY_SENDER", raising=False)
    monkeypatch.delenv("NUS_TOPIC", raising=False)
    gw = _make_gateway()
    assert gw._default_sender == "gateway"

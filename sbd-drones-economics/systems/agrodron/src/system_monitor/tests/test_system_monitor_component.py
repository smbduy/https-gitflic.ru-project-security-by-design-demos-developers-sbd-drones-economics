"""Тесты system_monitor."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Optional
from unittest.mock import MagicMock

import pytest
from broker.system_bus import SystemBus
from systems.agrodron.src.system_monitor import config
from systems.agrodron.src.system_monitor.src.system_monitor import SystemMonitorComponent
from systems.agrodron.scripts.proxy_reply import unwrap_proxy_target_response
from systems.agrodron.src.topic_utils import topic_for


@pytest.fixture(autouse=True)
def _disable_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEM_MONITOR_HTTP", "0")


SM = topic_for("security_monitor")


class MockBus(SystemBus):
    def __init__(self) -> None:
        self._callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self.requests: list = []

    def publish(self, topic: str, message: Dict[str, Any]) -> bool:
        return True

    def subscribe(self, topic: str, callback: Callable[[Dict[str, Any]], None]) -> bool:
        self._callbacks[topic] = callback
        return True

    def unsubscribe(self, topic: str) -> bool:
        self._callbacks.pop(topic, None)
        return True

    def request(
        self,
        topic: str,
        message: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        self.requests.append((topic, message))
        if message.get("action") == "proxy_request":
            return {
                "action": "response",
                "payload": {
                    "target_topic": "t",
                    "target_action": "get_state",
                    "target_response": {
                        "payload": {
                            "motors": {"mode": "IDLE"},
                            "sprayer": None,
                            "navigation": None,
                            "last_poll_ts": 1.0,
                        },
                    },
                },
            }
        return None

    def request_async(
        self,
        topic: str,
        message: Dict[str, Any],
        timeout: float = 30.0,
    ):
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

    def inject_journal(self, msg: Dict[str, Any]) -> None:
        cb = self._callbacks.get(config.journal_topic())
        if cb:
            cb(msg)


def _make(bus: MockBus) -> SystemMonitorComponent:
    return SystemMonitorComponent(
        component_id="system_monitor_test",
        bus=bus,
        topic=config.component_topic(),
    )


# ---------------------------------------------------------------- existing tests


def test_journal_tap_collects_log_event() -> None:
    bus = MockBus()
    comp = _make(bus)
    comp.start()
    bus.inject_journal(
        {
            "action": "log_event",
            "sender": SM,
            "payload": {"event": "E1", "source": "x"},
        }
    )
    snap = comp._snapshot()
    assert len(snap["journal_events"]) == 1
    assert snap["journal_events"][0]["payload"]["event"] == "E1"
    comp.stop()


def test_fetch_telemetry_via_proxy() -> None:
    bus = MockBus()
    comp = _make(bus)
    comp.start()
    out, dbg = comp._fetch_telemetry()
    assert out is not None
    assert dbg is None
    assert out.get("motors", {}).get("mode") == "IDLE"
    assert bus.requests
    comp.stop()


def test_unwrap_proxy_accepts_flat_target_response() -> None:
    flat = {
        "target_response": {
            "payload": {"motors": {"mode": "X"}, "last_poll_ts": 0.0},
        }
    }
    tr = unwrap_proxy_target_response(flat)
    assert tr is not None
    assert tr.get("payload", {}).get("motors", {}).get("mode") == "X"


# ---------------------------------------------------------------- new tests


def test_journal_tap_ignores_non_log_event() -> None:
    """Сообщения с action != log_event не попадают в буфер."""
    bus = MockBus()
    comp = _make(bus)
    comp.start()
    bus.inject_journal(
        {
            "action": "other_action",
            "sender": SM,
            "payload": {"event": "E2", "source": "x"},
        }
    )
    snap = comp._snapshot()
    assert len(snap["journal_events"]) == 0
    comp.stop()


def test_journal_tap_stores_multiple_events() -> None:
    """Буфер накапливает несколько событий."""
    bus = MockBus()
    comp = _make(bus)
    comp.start()
    for i in range(5):
        bus.inject_journal(
            {
                "action": "log_event",
                "sender": SM,
                "payload": {"event": f"E{i}", "source": "x"},
            }
        )
    snap = comp._snapshot()
    assert len(snap["journal_events"]) == 5
    comp.stop()


def test_extract_telemetry_snapshot_from_payload() -> None:
    """Снимок телеметрии извлекается из payload."""
    target_response = {
        "payload": {
            "motors": {"mode": "ACTIVE"},
            "sprayer": {"state": "ON"},
            "navigation": None,
            "last_poll_ts": 123.0,
        }
    }
    result = SystemMonitorComponent._extract_telemetry_snapshot(target_response)
    assert result is not None
    assert result["motors"]["mode"] == "ACTIVE"


def test_extract_telemetry_snapshot_from_root() -> None:
    """Снимок телеметрии извлекается из корня ответа, если нет payload."""
    target_response = {
        "motors": {"mode": "IDLE"},
        "sprayer": None,
        "navigation": None,
        "last_poll_ts": 0.0,
    }
    result = SystemMonitorComponent._extract_telemetry_snapshot(target_response)
    assert result is not None
    assert result["motors"]["mode"] == "IDLE"


def test_extract_telemetry_snapshot_returns_none() -> None:
    """Нет полей motors/sprayer/navigation — возвращает None."""
    target_response = {"some_key": "value"}
    result = SystemMonitorComponent._extract_telemetry_snapshot(target_response)
    assert result is None


def test_fetch_telemetry_non_dict_response() -> None:
    """Не-dict ответ от шины — возвращает (None, diagnostics)."""
    bus = MockBus()

    # Override request to return None
    bus.request = MagicMock(return_value=None)

    comp = _make(bus)
    comp.start()
    out, dbg = comp._fetch_telemetry()
    assert out is None
    assert dbg is not None
    comp.stop()


def test_fetch_telemetry_proxy_failed() -> None:
    """proxy_request вернул ok=False — retry и diagnostics."""
    bus = MockBus()
    bus.request = MagicMock(return_value={
        "payload": {"ok": False, "error": "proxy_failed"},
    })

    comp = _make(bus)
    comp.start()
    out, dbg = comp._fetch_telemetry()
    assert out is None
    assert dbg is not None
    comp.stop()


def test_fetch_telemetry_unwrap_fails() -> None:
    """unwrap_proxy_target_response не разобрал ответ."""
    bus = MockBus()
    bus.request = MagicMock(return_value={
        "action": "response",
        "payload": {"no_target_response": True},
    })

    comp = _make(bus)
    comp.start()
    out, dbg = comp._fetch_telemetry()
    assert out is None
    assert dbg is not None
    comp.stop()


def test_fetch_telemetry_no_snapshot_keys() -> None:
    """Ответ содержит target_response, но без полей motors/sprayer/navigation."""
    bus = MockBus()
    bus.request = MagicMock(return_value={
        "action": "response",
        "payload": {
            "target_response": {
                "payload": {"unrelated_key": "value"},
            },
        },
    })

    comp = _make(bus)
    comp.start()
    out, dbg = comp._fetch_telemetry()
    assert out is None
    assert dbg is not None
    comp.stop()


def test_fetch_telemetry_trust_error() -> None:
    """telemetry отклонила sender — возвращаем None с диагностикой."""
    bus = MockBus()
    bus.request = MagicMock(return_value={
        "action": "response",
        "payload": {
            "target_response": {
                "payload": {
                    "motors": {"mode": "IDLE"},
                    "sprayer": None,
                    "navigation": None,
                    "last_poll_ts": 0.0,
                    "telemetry_trust_error": True,
                    "sender_expected": "sm_topic",
                    "sender_received": "bad_sender",
                },
            },
        },
    })

    comp = _make(bus)
    comp.start()
    out, dbg = comp._fetch_telemetry()
    assert out is None
    assert dbg is not None
    comp.stop()


def test_snapshot_structure() -> None:
    """_snapshot возвращает корректную структуру."""
    bus = MockBus()
    comp = _make(bus)
    comp.start()
    snap = comp._snapshot()
    assert "journal_events" in snap
    assert "telemetry" in snap
    assert "telemetry_ts" in snap
    assert "telemetry_error" in snap
    assert "telemetry_debug" in snap
    assert "component_id" in snap
    assert snap["component_id"] == "system_monitor_test"
    comp.stop()


def test_snapshot_includes_telemetry_after_poll() -> None:
    """После опроса телеметрии snapshot содержит данные."""
    bus = MockBus()
    comp = _make(bus)
    comp.start()

    # Принудительно вызываем fetch и обновляем состояние как poll_loop
    snap_data, _ = comp._fetch_telemetry()
    with comp._lock:
        comp._last_telemetry = snap_data

    snap = comp._snapshot()
    assert snap["telemetry"] is not None
    assert snap["telemetry"]["motors"]["mode"] == "IDLE"
    comp.stop()


def test_telemetry_poll_loop_error_handling() -> None:
    """_telemetry_poll_loop обрабатывает исключения и продолжает работу."""
    bus = MockBus()
    bus.request = MagicMock(side_effect=RuntimeError("bus error"))

    comp = _make(bus)
    comp.start()

    # Ждём, чтобы poll loop отработал (1.5s начальная задержка + poll)
    time.sleep(3.0)

    snap = comp._snapshot()
    # Ошибка должна быть записана
    assert snap["telemetry_error"] is not None
    comp.stop()


def test_subscribe_failure_warning() -> None:
    """Если subscribe возвращает False, компонент логирует предупреждение."""
    bus = MockBus()
    bus.subscribe = MagicMock(return_value=False)

    comp = _make(bus)
    # Не должно упасть
    comp.start()
    comp.stop()


def test_start_http_server_disabled(monkeypatch) -> None:
    """HTTP-сервер не запускается при SYSTEM_MONITOR_HTTP=0."""
    bus = MockBus()
    comp = _make(bus)
    comp.start()
    assert comp._http_thread is None
    comp.stop()


def test_on_journal_message_fields() -> None:
    """Запись в буфер содержит ts, action, sender, payload."""
    bus = MockBus()
    comp = _make(bus)
    comp.start()

    bus.inject_journal({
        "action": "log_event",
        "sender": SM,
        "payload": {"event": "TEST_EVENT", "source": "unit"},
    })

    snap = comp._snapshot()
    entry = snap["journal_events"][0]
    assert "ts" in entry
    assert entry["action"] == "log_event"
    assert entry["sender"] == SM
    comp.stop()


def test_stop_unsubscribes() -> None:
    """stop() отписывается от топика журнала."""
    bus = MockBus()
    comp = _make(bus)
    comp.start()
    assert config.journal_topic() in bus._callbacks

    comp.stop()
    assert config.journal_topic() not in bus._callbacks

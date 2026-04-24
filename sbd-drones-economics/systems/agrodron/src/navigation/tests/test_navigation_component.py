from systems.agrodron.src.bus_mock import MockSystemBus
from systems.agrodron.src.navigation import config
from systems.agrodron.src.navigation.src.navigation import NavigationComponent
import time

SM_TOPIC = config.security_monitor_topic()


def _make_component() -> NavigationComponent:
    bus = MockSystemBus()
    return NavigationComponent(
        component_id="navigation_test",
        bus=bus,
        topic=config.component_topic(),
    )


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


def test_lifecycle_start_stop():
    """
    НОВЫЙ ТЕСТ: Проверка запуска и остановки компонента.
    Покрывает методы: start(), stop().
    """
    comp = _make_component()
    
    # Изначально компонент остановлен
    assert hasattr(comp, '_running')
    assert comp._running is False
    
    # Запуск компонента
    comp.start()
    time.sleep(0.2)  # Даем время на запуск потока
    
    assert comp._running is True, "Компонент не перешел в состояние запуска"
    
    # Остановка компонента
    comp.stop()
    time.sleep(0.1)  # Даем время на завершение потока
    
    assert comp._running is False, "Компонент не перешел в состояние остановки"


def test_poll_sitl_once_success():
    """
    НОВЫЙ ТЕСТ: Проверка успешного однократного опроса SITL.
    Покрывает методы: _poll_sitl_once(), _publish_nav_state().
    """
    comp = _make_component()
    
    # Мокированные данные от симулятора
    mock_sitl_response = {
        "lat": 55.751244,
        "lon": 37.618423,
        "alt": 100.5,
        "vx": 1.0,
        "vy": 2.0,
        "vz": 0.5,
        "heading": 90.0,
        "gps_fix_type": 3,
        "satellites_visible": 10,
        "timestamp": time.time()
    }
    
    # Подменяем метод request у шины
    def mock_request(action, target, payload=None, timeout=None):
        return {"payload": mock_sitl_response, "ok": True}
    
    original_request = comp._bus.request
    comp._bus.request = mock_request
    
    try:
        comp._poll_sitl_once()
        
        # 1. Проверяем, что внутреннее состояние обновилось
        assert comp._last_nav_state is not None
        assert comp._last_nav_state["lat"] == mock_sitl_response["lat"]
        
        # 2. Проверяем публикацию в шину
        expected_topic = config.agrodron_nav_state_topic()
        found_publish = False
        
        for msg in comp._bus.published_messages:
            if msg.get("topic") == expected_topic:
                assert msg["payload"]["lat"] == mock_sitl_response["lat"]
                found_publish = True
                break
        
        assert found_publish, f"Данные не опубликованы в {expected_topic}"
        
    finally:
        comp._bus.request = original_request


def test_poll_sitl_timeout_handling():
    """
    НОВЫЙ ТЕСТ: Проверка обработки ошибок при опросе SITL.
    Покрывает ветки обработки исключений в _poll_sitl_once().
    """
    comp = _make_component()
    
    def mock_error_request(*args, **kwargs):
        raise TimeoutError("SITL service unavailable")
    
    original_request = comp._bus.request
    comp._bus.request = mock_error_request
    
    try:
        # Метод должен перехватить исключение внутри себя
        comp._poll_sitl_once()
        # Если код дошел сюда - ок
        assert True 
    except Exception as e:
        pytest.fail(f"_poll_sitl_once не обработал исключение: {e}")
    finally:
        comp._bus.request = original_request


def test_handle_update_config():
    """
    НОВЫЙ ТЕСТ: Проверка динамического обновления конфигурации.
    Покрывает метод: _handle_update_config().
    """
    comp = _make_component()
    
    new_config_params = {
        "poll_interval_s": 0.5,
        "request_timeout_s": 2.0
    }
    
    message = {
        "payload": new_config_params,
        "sender": SM_TOPIC
    }
    
    result = comp._handle_update_config(message)
    
    assert result is not None, "Обработчик должен возвращать результат"


def test_housekeeping_loop_integration():
    """
    НОВЫЙ ИНТЕГРАЦИОННЫЙ ТЕСТ: Проверка работы фонового цикла.
    Покрывает метод: _housekeeping_loop().
    """
    comp = _make_component()
    
    mock_response_data = {
        "lat": 55.0,
        "lon": 37.0,
        "alt": 50.0,
        "gps_fix_type": 3,
        "heading": 180.0,
        "vx": 0.0, "vy": 0.0, "vz": 0.0,
        "satellites_visible": 8
    }
    
    def static_mock_request(*args, **kwargs):
        return {"payload": mock_response_data, "ok": True}
    
    original_request = comp._bus.request
    comp._bus.request = static_mock_request
    
    try:
        comp.start()
        time.sleep(2.5)  # Ждем 2-3 цикла опроса
        comp.stop()
        time.sleep(0.1)
        
        expected_topic = config.agrodron_nav_state_topic()
        nav_messages = [
            m for m in comp._bus.published_messages 
            if m.get("topic") == expected_topic
        ]
        
        assert len(nav_messages) > 0, "Цикл не опубликовал данные навигации"
        
    finally:
        comp._bus.request = original_request

def test_start_stop_lifecycle():
    """
    Покрывает: NavigationComponent.start, NavigationComponent.stop
    """
    comp, bus = _make_component()
    
    # Проверка начального состояния
    assert comp._running is False
    
    # Запуск
    comp.start()
    time.sleep(0.3)  # Ждем запуска потока
    assert comp._running is True
    
    # Остановка
    comp.stop()
    time.sleep(0.1)  # Ждем завершения потока
    assert comp._running is False

def test_poll_sitl_once_success():
    """
    Покрывает: NavigationComponent._poll_sitl_once, NavigationComponent._publish_nav_state
    """
    comp, bus = _make_component()
    
    # Данные, которые якобы вернул симулятор
    mock_data = {
        "lat": 55.75, "lon": 37.61, "alt": 100.0,
        "vx": 1.0, "vy": 2.0, "vz": 0.0,
        "heading": 90.0, "gps_fix_type": 3, "satellites_visible": 10
    }
    
    # Подменяем метод request, чтобы он не ходил в сеть, а возвращал mock_data
    def mock_request(*args, **kwargs):
        return {"payload": mock_data}
    
    original_req = comp._bus.request
    comp._bus.request = mock_request
    
    try:
        comp._poll_sitl_once()
        
        # 1. Проверка, что внутреннее состояние обновилось
        assert comp._last_nav_state is not None
        assert comp._last_nav_state["lat"] == 55.75
        
        # 2. Проверка, что данные ушли в шину (опубликовались)
        nav_topic = config.agrodron_nav_state_topic()
        published = [m for m in bus.published_messages if m.get("topic") == nav_topic]
        assert len(published) > 0, "Данные не были опубликованы в шину"
        
    finally:
        comp._bus.request = original_req

def test_poll_sitl_error_handling():
    """
    Покрывает: ветку except внутри NavigationComponent._poll_sitl_once
    """
    comp, bus = _make_component()
    
    # Имитируем ошибку сети
    def mock_error(*args, **kwargs):
        raise ConnectionError("SITL unreachable")
    
    original_req = comp._bus.request
    comp._bus.request = mock_error
    
    try:
        # Метод должен поймать ошибку внутри и не упасть
        comp._poll_sitl_once()
        # Если дошли сюда — тест пройден (ошибка обработана)
    except Exception:
        pytest.fail("Метод _poll_sitl_once не обработал исключение корректно")
    finally:
        comp._bus.request = original_req

def test_handle_update_config_full():
    """
    Покрывает: NavigationComponent._handle_update_config
    """
    comp, bus = _make_component()
    
    new_params = {
        "poll_interval_s": 0.5,
        "request_timeout_s": 2.0
    }
    
    msg = {"payload": new_params, "sender": config.security_monitor_topic()}
    result = comp._handle_update_config(msg)
    
    assert result is not None

def test_housekeeping_loop_integration():
    """
    Покрывает: NavigationComponent._housekeeping_loop (фоновый цикл)
    Интеграционный тест: запускает поток и ждет публикаций.
    """
    comp, bus = _make_component()
    
    mock_data = {
        "lat": 0.0, "lon": 0.0, "alt": 50.0,
        "gps_fix_type": 3, "heading": 0,
        "vx": 0, "vy": 0, "vz": 0, "satellites_visible": 4
    }
    
    def mock_request(*args, **kwargs):
        return {"payload": mock_data}
    
    original_req = comp._bus.request
    comp._bus.request = mock_request
    
    try:
        comp.start()
        # Ждем 1.5 секунды (стандартный интервал опроса обычно 1с)
        time.sleep(1.5)
        comp.stop()
        time.sleep(0.1)
        
        nav_topic = config.agrodron_nav_state_topic()
        published = [m for m in bus.published_messages if m.get("topic") == nav_topic]
        
        assert len(published) >= 1, f"Цикл не отработал ни разу за 1.5 сек. Сообщений: {len(bus.published_messages)}"
        
    finally:
        comp._bus.request = original_req


"""
Интеграционные тесты для regulator system.

Требуют запущенного брокера (MQTT или Kafka).
Запускаются в среде интегратора через: make test-all-docker
"""
import pytest


@pytest.mark.skip(reason="Интеграционные тесты запускаются только в среде интегратора с брокером")
def test_placeholder():
    pass

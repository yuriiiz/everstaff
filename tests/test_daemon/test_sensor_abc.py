"""Tests for Sensor ABC contract."""
import pytest
from everstaff.daemon.sensors.base import Sensor


def test_sensor_is_abstract():
    """Cannot instantiate Sensor directly."""
    with pytest.raises(TypeError):
        Sensor()


def test_sensor_subclass_must_implement_start_and_stop():
    """Subclass missing methods raises TypeError on instantiation."""

    class BadSensor(Sensor):
        pass

    with pytest.raises(TypeError):
        BadSensor()


def test_sensor_subclass_with_methods_instantiates():
    """Subclass implementing both methods instantiates fine."""

    class GoodSensor(Sensor):
        async def start(self, event_bus):
            pass

        async def stop(self):
            pass

    s = GoodSensor()
    assert isinstance(s, Sensor)

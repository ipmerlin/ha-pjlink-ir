"""Lamp operating time, actual power phase and PJLink error severities."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import callback

from .entity import LampEntity, ProjectorDataEntity
from .protocol import ERROR_FIELDS, ERROR_STATES, POWER_PHASES


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([PowerPhase(coordinator), *[ErrorSeverity(coordinator, key) for key in ERROR_FIELDS]])
    added = set()

    @callback
    def discover_lamps():
        count = max(1, len((coordinator.data or {}).get("lamps") or []))
        new = [LampHours(coordinator, index) for index in range(count) if index not in added]
        added.update(range(count))
        if new:
            async_add_entities(new)

    discover_lamps()
    entry.async_on_unload(coordinator.async_add_listener(discover_lamps))


class LampHours(LampEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lightbulb-clock-outline"

    def __init__(self, coordinator, index):
        super().__init__(coordinator, index)
        self._attr_translation_key = "lamp_hours" if index == 0 else "additional_lamp_hours"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_lamp_{index + 1}_hours"

    @property
    def native_value(self):
        return self.lamp["hours"] if self.lamp is not None else None


class PowerPhase(ProjectorDataEntity, SensorEntity):
    _data_key = "power"
    _attr_translation_key = "power_phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(POWER_PHASES.values())
    _attr_icon = "mdi:projector"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_power_phase"

    @property
    def native_value(self):
        return POWER_PHASES.get((self.coordinator.data or {}).get("power"))


class ErrorSeverity(ProjectorDataEntity, SensorEntity):
    _data_key = "errors"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(ERROR_STATES)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self.key = key
        self._attr_translation_key = f"{key}_status"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}_status"

    @property
    def native_value(self):
        return ((self.coordinator.data or {}).get("errors") or {}).get(self.key)

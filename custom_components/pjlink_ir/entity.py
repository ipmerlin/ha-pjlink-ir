"""Shared device metadata."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class ProjectorEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=entry.data.get("manufacturer") or None,
            model=entry.data.get("model") or None,
        )


class ProjectorDataEntity(ProjectorEntity):
    """Telemetry is unavailable while the network/value is unavailable."""

    _data_key = None

    @property
    def available(self):
        data = self.coordinator.data or {}
        return super().available and bool(data.get("connected")) and data.get(self._data_key) is not None


class LampEntity(ProjectorDataEntity):
    _data_key = "lamps"

    def __init__(self, coordinator, index):
        super().__init__(coordinator)
        self.index = index
        self._attr_translation_placeholders = {"number": str(index + 1)}

    @property
    def available(self):
        return super().available and len((self.coordinator.data or {}).get("lamps") or []) > self.index

    @property
    def lamp(self):
        lamps = (self.coordinator.data or {}).get("lamps") or []
        return lamps[self.index] if self.index < len(lamps) else None

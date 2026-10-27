"""Generate consistent English and Russian Home Assistant UI resources."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "pjlink_ir"


def make(ru=False):
    def t(en, russian):
        return russian if ru else en

    fields = {
        "remote_entity_id": t("IR transmitter", "ИК-передатчик"),
        "ir_device": t(
            "Saved device name (if required by the transmitter)",
            "Имя сохранённого устройства (если требуется передатчику)",
        ),
        "ir_command": t("Power-on command name or code", "Имя или код команды включения"),
        "command_setup": t("Command setup", "Настройка команды"),
        "wake_timeout": t("Wait for power confirmation (seconds)", "Ожидание подтверждения включения (секунды)"),
    }
    return {
        "title": "Panasonic Projector",
        "config": {
            "step": {
                "user": {
                    "title": t("Connect to the projector", "Подключение к проектору"),
                    "description": t(
                        "Turn on the projector so its network interface is available. Manufacturer and model will be read automatically.",
                        "Включите проектор, чтобы он был доступен по сети. Производитель и модель определятся автоматически.",
                    ),
                    "data": {
                        "host": t("IP address or hostname", "IP-адрес или имя узла"),
                        "port": t("PJLink port", "Порт PJLink"),
                        "password": t("PJLink password", "Пароль PJLink"),
                    },
                },
                "ir": {
                    "title": t("Infrared power on", "Включение по ИК"),
                    "description": t(
                        "Manufacturer: {manufacturer}. Model: {model}. Select a remote entity. Enter the existing command name/code, or choose learning. For Broadlink and Xiaomi IR, use a saved device name such as panasonic_projector. Other remotes may not need this field; leave it empty. Command names are managed by the transmitter integration.",
                        "Производитель: {manufacturer}. Модель: {model}. Выберите передатчик. Укажите имя или код готовой команды либо выберите обучение. Для Broadlink и Xiaomi IR укажите имя устройства, например panasonic_projector. Для других передатчиков это поле можно оставить пустым, если оно им не нужно. Имена команд хранятся в интеграции передатчика.",
                    ),
                    "data": fields,
                },
                "learn_start": {
                    "title": t("Prepare the original remote", "Подготовьте пульт проектора"),
                    "description": t(
                        "After pressing Submit, point the original remote at the IR transmitter and press Power On within 30 seconds. This stores a received IR code without transmitting it. Prefer a separate Power On button. A toggle button needs a physical test from standby. Learning the same device/command name may overwrite its existing code.",
                        "После нажатия «Отправить» направьте штатный пульт на ИК-передатчик и в течение 30 секунд нажмите кнопку включения. Передатчик запишет код без отправки команды проектору. Предпочтительна отдельная кнопка ВКЛ. Если кнопка переключает питание, проверьте её работу из режима ожидания. Обучение с теми же именами устройства и команды может перезаписать прежний код.",
                    ),
                },
                "learn_confirm": {
                    "title": t("Check the learning result", "Проверьте результат обучения"),
                    "description": t(
                        "The learning request has finished. Some transmitter integrations only report a failure in notifications or logs. Check them and confirm the command was saved. Leave the box unchecked to learn again. The projector has not been switched on by this wizard.",
                        "Запрос обучения завершён. Некоторые интеграции сообщают о неудаче только в уведомлениях или журнале Home Assistant. Проверьте их и подтвердите сохранение команды. Если команда не записалась, оставьте флажок снятым — обучение можно повторить. Мастер не отправлял команду включения проектору.",
                    ),
                    "data": {"confirmed": t("Command was saved", "Команда сохранена")},
                },
                "learn_failed": {
                    "title": t("Learning failed", "Обучение не завершено"),
                    "description": t(
                        "Check that the selected transmitter is available and supports standard remote.learn_command. Press Submit to prepare another attempt. Close this dialog to cancel.",
                        "Проверьте доступность передатчика и поддержку стандартного обучения remote.learn_command. Нажмите «Отправить», чтобы подготовить повторную попытку. Для отмены закройте окно.",
                    ),
                },
            },
            "progress": {
                "learning": t(
                    "Point the original remote at the selected transmitter and press Power On. Waiting for the IR code…",
                    "Направьте штатный пульт на выбранный передатчик и нажмите кнопку включения. Ожидание ИК-кода…",
                )
            },
            "error": {
                "cannot_connect": t(
                    "Cannot read PJLink state. Turn on the projector and check the address, port and network.",
                    "Не удалось прочитать состояние PJLink. Включите проектор и проверьте адрес, порт и сеть.",
                ),
                "invalid_auth": t("Check the PJLink password.", "Проверьте пароль PJLink."),
                "invalid_host": t(
                    "Enter an IP address or hostname without a URL or port.",
                    "Введите IP-адрес или имя узла без URL и порта.",
                ),
                "remote_unavailable": t(
                    "The transmitter is missing, off or unavailable.",
                    "Передатчик отсутствует, выключен или недоступен.",
                ),
                "cannot_learn": t(
                    "The transmitter is unavailable or does not support standard command learning. Use a saved command instead.",
                    "Передатчик недоступен или не поддерживает стандартное обучение команд. Можно использовать готовую команду.",
                ),
                "empty_command": t("Enter a power-on command name or code.", "Укажите имя или код команды включения."),
            },
            "abort": {
                "already_configured": t(
                    "This address and port are already configured.", "Этот адрес и порт уже настроены."
                ),
                "reconfigure_successful": t("IR settings updated.", "Настройки ИК обновлены."),
            },
        },
        "options": {
            "step": {"init": {
                "title": t("Panasonic controls", "Управление Panasonic"),
                "description": t(
                    "Uses Panasonic command control on the same projector, independently of PJLink. Enable NETWORK CONTROL in the projector menu. The password is the web administrator password (PJLink password by default); username is usually admin1. An empty password is valid only for an unprotected command connection. Changes reload this integration without repeating IR learning.",
                    "Используется управление командами Panasonic на том же проекторе, отдельно от PJLink. Включите NETWORK CONTROL в меню проектора. Пароль — от веб-доступа администратора (по умолчанию пароль PJLink); имя пользователя обычно admin1. Пустой пароль подходит только для подключения без авторизации. Изменения перезагрузят интеграцию без повторного обучения ИК.",
                ),
                "data": {
                    "panasonic_enabled": t("Enable additional Panasonic controls", "Дополнительное управление Panasonic"),
                    "panasonic_port": t("Panasonic command port", "Порт команд Panasonic"),
                    "panasonic_username": t("Web administrator username", "Имя администратора веб-интерфейса"),
                    "panasonic_password": t("Web administrator password", "Пароль администратора веб-интерфейса"),
                },
            }},
            "abort": {"daylight_not_supported": t(
                "Additional Panasonic controls are currently supported for FW300 models only.",
                "Дополнительное управление Panasonic сейчас поддерживается только для FW300.",
            )},
        },
        "selector": {
            "command_setup": {
                "options": {
                    "saved": t("Use saved command", "Использовать готовую команду"),
                    "learn": t("Learn power on now", "Обучить включению сейчас"),
                }
            }
        },
        "entity": {
            "select": {"daylight_view": {
                "name": "Daylight View",
                "state": {"off": t("Off", "Выключено"), "auto": t("Auto", "Авто"), "on": t("On", "Включено")},
            }, "picture_mode": {
                "name": t("Picture mode", "Режим изображения"),
                "state": {key: t(en, russian) for key, en, russian in (
                    ("dynamic", "Dynamic", "Динамический"), ("standard", "Standard", "Стандартный"),
                    ("natural", "Natural", "Натуральный"), ("cinema", "Cinema", "Кино"),
                    ("blackboard", "Blackboard", "Школьная доска"),
                )},
            }, "color_temperature": {
                "name": t("Color temperature", "Цветовая температура"),
                "state": {"low": t("Low", "Низкая"), "default": t("Default", "Стандартная"), "high": t("High", "Высокая")},
            }, "aspect": {
                "name": t("Aspect ratio", "Формат изображения"),
                "state": {"auto": t("Auto", "Авто"), "4_3": "4:3", "16_9": "16:9",
                          "h_fit": t("Fit width", "По ширине"), "v_fit": t("Fit height", "По высоте"),
                          "hv_fit": t("Fill screen", "Заполнить экран"), "through": t("Through", "Без масштабирования")},
            }},
            "number": {
                "volume": {"name": t("Volume", "Громкость")},
                "brightness": {"name": t("Brightness", "Яркость")},
                "contrast": {"name": t("Contrast", "Контраст")},
            },
            "binary_sensor": {
                "connectivity": {"name": t("PJLink connection", "Связь PJLink")},
                "lamp_lit": {"name": t("Lamp lit", "Лампа включена")},
                "additional_lamp_lit": {"name": t("Lamp {number} lit", "Лампа {number} включена")},
                "problem": {"name": t("Problem", "Неисправность")},
            },
            "sensor": {
                **{key: {"name": t(en, russian)} for key, en, russian in (
                    ("intake_temperature", "Intake air temperature", "Температура входящего воздуха"),
                    ("exhaust_temperature", "Exhaust air temperature", "Температура выходящего воздуха"),
                    ("filter_hours", "Filter operating time", "Наработка фильтра"),
                    ("filter_rewinds", "Filter rewinds", "Перемотки фильтра"),
                    ("filter_since_rewind", "Time since filter rewind", "Время после перемотки фильтра"),
                    ("filter_remaining", "Estimated filter time remaining", "Расчётный остаток фильтра"),
                )},
                "lamp_hours": {"name": t("Lamp operating time", "Наработка лампы")},
                "additional_lamp_hours": {"name": t("Lamp {number} operating time", "Наработка лампы {number}")},
                "power_phase": {
                    "name": t("Power phase", "Фаза питания"),
                    "state": {
                        "standby": t("Standby", "Ожидание"),
                        "on": t("On", "Включён"),
                        "cooling": t("Cooling down", "Охлаждение"),
                        "warming": t("Warming up", "Прогрев"),
                    },
                },
                **{
                    f"{key}_status": {
                        "name": t(en, russian),
                        "state": {
                            "ok": t("OK", "Норма"),
                            "warning": t("Warning", "Предупреждение"),
                            "error": t("Error", "Ошибка"),
                        },
                    }
                    for key, en, russian in (
                        ("fan", "Fan status", "Состояние вентилятора"),
                        ("lamp", "Lamp status", "Состояние лампы"),
                        ("temperature", "Temperature status", "Состояние температуры"),
                        ("cover", "Cover status", "Состояние крышки"),
                        ("filter", "Filter status", "Состояние фильтра"),
                        ("other", "Other status", "Прочие неисправности"),
                    )
                },
            },
            "switch": {"av_mute": {"name": t("AV mute", "AV Mute")}, "freeze": {"name": t("Freeze", "Стоп-кадр")}},
            "button": {
                "refresh": {"name": t("Refresh status", "Обновить данные")},
                "auto_setup": {"name": t("Auto setup", "Автонастройка изображения")},
                "zoom_in": {"name": t("Digital zoom in", "Увеличить изображение")},
                "zoom_out": {"name": t("Digital zoom out", "Уменьшить изображение")},
                "side_by_side": {"name": t("Side by Side", "Два изображения рядом")},
            },
        },
    }


if __name__ == "__main__":
    (ROOT / "translations").mkdir(exist_ok=True)
    for name, data in (
        ("strings.json", make()),
        ("translations/en.json", make()),
        ("translations/ru.json", make(True)),
    ):
        (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

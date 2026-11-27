"""The generated app and its generator must both admit web-view microphone use."""

import json
import plistlib
from pathlib import Path

import yaml

APPLE = Path(__file__).resolve().parents[2] / "mobile/src-tauri/gen/apple"
PERMISSION = "NSMicrophoneUsageDescription"


def test_microphone_purpose_is_present_in_the_shipped_app_and_generator() -> None:
    with (APPLE / "agenticos-mobile_iOS/Info.plist").open("rb") as source:
        shipped = plistlib.load(source)
    assert isinstance(shipped.get(PERMISSION), str)
    assert shipped[PERMISSION].strip()
    project: object = yaml.safe_load((APPLE / "project.yml").read_text())
    assert isinstance(project, dict)
    targets = project["targets"]
    assert isinstance(targets, dict)
    target = targets["agenticos-mobile_iOS"]
    assert isinstance(target, dict)
    info = target["info"]
    assert isinstance(info, dict)
    properties = info["properties"]
    assert isinstance(properties, dict)
    assert properties[PERMISSION] == shipped[PERMISSION]


def test_microphone_purpose_is_translated_in_every_existing_native_locale() -> None:
    catalog: object = json.loads((APPLE / "agenticos-mobile_iOS/InfoPlist.xcstrings").read_text())
    assert isinstance(catalog, dict)
    strings = catalog["strings"]
    assert isinstance(strings, dict)
    camera = strings["NSCameraUsageDescription"]
    microphone = strings[PERMISSION]
    assert isinstance(camera, dict) and isinstance(microphone, dict)
    locales = camera["localizations"]
    translated = microphone["localizations"]
    assert isinstance(locales, dict) and isinstance(translated, dict)
    assert translated.keys() == locales.keys()
    for language in locales:
        entry = translated[language]
        assert isinstance(entry, dict)
        unit = entry["stringUnit"]
        assert isinstance(unit, dict)
        assert unit["state"] == "translated"
        assert isinstance(unit["value"], str) and unit["value"].strip()

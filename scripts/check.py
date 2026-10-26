"""Offline syntax, metadata, translation and archive prerequisites."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "pjlink_ir"


def main():
    for path in list(COMPONENT.rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    keys = list(manifest)
    assert keys == ["domain", "name", *sorted(keys[2:])]
    assert manifest["domain"] == "pjlink_ir" and manifest["config_flow"]
    assert manifest["version"]
    resources = [
        json.loads((COMPONENT / p).read_text(encoding="utf-8"))
        for p in ("strings.json", "translations/en.json", "translations/ru.json")
    ]

    def paths(value, prefix=""):
        return {prefix + "." + k for k in value} | set().union(
            *(paths(v, prefix + "." + k) for k, v in value.items() if isinstance(v, dict)), set()
        )

    assert paths(resources[0]) == paths(resources[1]) == paths(resources[2])
    flow = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
    methods = {
        node.name.removeprefix("async_step_")
        for node in ast.walk(flow)
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("async_step_")
    }
    for step in resources[0]["config"]["step"]:
        assert step in methods, step
    assert not any(p.suffix in (".env", ".sqlite") for p in COMPONENT.rglob("*"))
    print("Syntax, manifest ordering, UI steps and EN/RU translation structure: OK")


if __name__ == "__main__":
    main()

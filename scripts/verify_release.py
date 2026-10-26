"""Download published release assets and compare them to the intended package."""

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "ipmerlin/ha-pjlink-ir"
VERSION = json.loads((ROOT / "custom_components" / "pjlink_ir" / "manifest.json").read_text(encoding="utf-8"))[
    "version"
]
TAG = f"v{VERSION}"
NAME = f"pjlink_ir-{VERSION}.zip"


def main():
    output = ROOT / "dist" / "published"
    output.mkdir(exist_ok=True)
    subprocess.run(
        [
            "gh",
            "release",
            "download",
            TAG,
            "--repo",
            REPOSITORY,
            "--dir",
            str(output),
            "--pattern",
            NAME,
            "--pattern",
            NAME + ".sha256",
            "--clobber",
        ],
        check=True,
    )
    local = ROOT / "dist" / NAME
    remote = output / NAME
    digest = hashlib.sha256(remote.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(local.read_bytes()).hexdigest(), "Published archive differs from local package"
    assert (output / (NAME + ".sha256")).read_text(encoding="ascii").split()[0] == digest
    with zipfile.ZipFile(remote) as archive:
        assert archive.testzip() is None
        component = ROOT / "custom_components" / "pjlink_ir"
        expected = {
            p.relative_to(ROOT).as_posix() for p in component.rglob("*") if p.is_file() and "__pycache__" not in p.parts
        }
        assert set(archive.namelist()) == expected
        for name in archive.namelist():
            assert archive.read(name) == (ROOT / name).read_bytes(), name
    print(f"Published archive verified: {len(expected)} files, SHA256 {digest}")


if __name__ == "__main__":
    main()

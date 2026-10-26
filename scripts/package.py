"""Build and independently compare every archived byte to its source."""

from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "pjlink_ir"


def main():
    version = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]
    output = ROOT / "dist" / f"pjlink_ir-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    files = sorted(p for p in COMPONENT.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {p.relative_to(ROOT).as_posix() for p in files}
        for path in files:
            assert archive.read(path.relative_to(ROOT).as_posix()) == path.read_bytes()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(f"Verified {len(files)} files: {output.name}; SHA256 {digest}")


if __name__ == "__main__":
    main()

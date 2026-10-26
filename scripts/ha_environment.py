"""Provision a project-local HA test environment; never connects to devices."""

from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".uv-tool"))
import uv  # noqa: E402

env = dict(os.environ)
env["UV_PYTHON_INSTALL_DIR"] = str(ROOT / ".runtimes")
env["UV_CACHE_DIR"] = str(ROOT / ".uv-cache")
uv_exe = uv.find_uv_bin()


def run(*args):
    subprocess.run([uv_exe, *args], env=env, cwd=ROOT, check=True)


if __name__ == "__main__":
    run("python", "install", "3.14", "--no-bin")
    run("venv", "--python", "3.14", ".ha-venv")
    run(
        "pip",
        "install",
        "--python",
        str(ROOT / ".ha-venv" / "Scripts" / "python.exe"),
        "pytest-homeassistant-custom-component==0.13.373",
    )

import os
import sys
import time
import shutil
import json
from typing import Tuple

import urllib.request


"""
Simple self-updater for the YouTube TTS bot executable.

Design
------
- The main app (your EXE) should *not* try to overwrite itself.
  Instead, when it detects an update is available, it should:

    1. Download the new EXE into this `tts_updater` folder
       (for example as `TTS-BOT-new.exe`).
    2. Spawn this updater script in a new process and then exit.

- This script waits for the old EXE to fully exit, replaces it with
  the new file, updates `version.txt`, and optionally restarts the
  app.

Configuration
-------------
You can control where updates come from by editing `update_config.json`
in this same folder. Example:

{
  "current_version": "1.0.0",
  "remote_version_url": "https://raw.githubusercontent.com/<user>/<repo>/main/tts_updater/version.txt",
  "remote_exe_url": "https://github.com/<user>/<repo>/releases/latest/download/TTS-BOT.exe",
  "exe_name": "YT-TTS-Bot.exe"
}

Usage
-----
1) To *check* whether an update exists (no file replacement):

    python updater.py --check

2) To run a full update-and-replace cycle from the main app:

    python updater.py --auto

   This will:
   - Compare local `version.txt` with the remote version.
   - Download the new EXE if needed.
   - Wait for the running EXE to exit.
   - Replace the old EXE with the new one.
"""

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPDATER_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(UPDATER_DIR, "version.txt")
UPDATE_CONFIG_FILE = os.path.join(UPDATER_DIR, "update_config.json")


def _read_local_version() -> str:
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return "0.0.0"


def _write_local_version(ver: str) -> None:
    try:
        with open(VERSION_FILE, "w", encoding="utf-8") as fh:
            fh.write(ver.strip())
    except OSError:
        pass


def _load_update_config() -> dict:
    data = {
        "current_version": _read_local_version(),
        "remote_version_url": "",
        "remote_exe_url": "",
        "exe_name": "YT-TTS-Bot.exe",
    }
    try:
        if os.path.isfile(UPDATE_CONFIG_FILE):
            with open(UPDATE_CONFIG_FILE, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data.update(loaded)
    except Exception:
        pass
    return data


def _fetch_text(url: str, timeout: int = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace").strip()


def _download_file(url: str, dest_path: str, timeout: int = 30) -> None:
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(dest_path, "wb") as out:
        shutil.copyfileobj(resp, out)


def _compare_versions(a: str, b: str) -> int:
    """
    Return -1 if a<b, 0 if equal, 1 if a>b (semantic-ish comparison).
    """
    def _split(v: str) -> Tuple[int, int, int]:
        parts = (v or "0.0.0").split(".")
        parts += ["0"] * (3 - len(parts))
        return tuple(int(p or 0) for p in parts[:3])

    va = _split(a)
    vb = _split(b)
    return (va > vb) - (va < vb)


def check_for_update(verbose: bool = True) -> Tuple[bool, str, str]:
    """
    Check remote version vs local version.

    Returns (update_available, local_version, remote_version).
    """
    cfg = _load_update_config()
    local_ver = cfg.get("current_version") or _read_local_version()
    remote_url = cfg.get("remote_version_url", "")

    if not remote_url:
        if verbose:
            print("[Updater] remote_version_url not configured in update_config.json")
        return False, local_ver, local_ver

    try:
        remote_ver = _fetch_text(remote_url)
        if verbose:
            print(f"[Updater] Local version:  {local_ver}")
            print(f"[Updater] Remote version: {remote_ver}")
        need_update = _compare_versions(remote_ver, local_ver) > 0
        return need_update, local_ver, remote_ver
    except Exception as exc:
        if verbose:
            print(f"[Updater] Failed to fetch remote version: {exc}")
        return False, local_ver, local_ver


def run_auto_update() -> None:
    """
    End-to-end update flow:
    - Check if a newer version exists.
    - Download it into `tts_updater/`.
    - Replace the existing EXE.
    """
    cfg = _load_update_config()
    exe_name = cfg.get("exe_name") or "YT-TTS-Bot.exe"
    main_exe_path = os.path.join(BASE_DIR, exe_name)

    need_update, local_ver, remote_ver = check_for_update(verbose=True)
    if not need_update:
        print("[Updater] No update available.")
        return

    remote_exe_url = cfg.get("remote_exe_url", "")
    if not remote_exe_url:
        print("[Updater] remote_exe_url not configured in update_config.json")
        return

    tmp_exe_path = os.path.join(UPDATER_DIR, f"{exe_name}.download")
    print("[Updater] Update found – downloading new version, please wait...")
    try:
        _download_file(remote_exe_url, tmp_exe_path)
    except Exception as exc:
        print(f"[Updater] Download failed: {exc}")
        if os.path.exists(tmp_exe_path):
            os.remove(tmp_exe_path)
        return

    print("[Updater] Download complete. Waiting for application to exit...")

    # Wait for the old EXE to be released by Windows.
    for _ in range(60):
        try:
            # Try renaming as a simple "is it locked?" test.
            probe = main_exe_path + ".probe"
            if os.path.exists(main_exe_path):
                os.replace(main_exe_path, probe)
                os.replace(probe, main_exe_path)
            break
        except OSError:
            time.sleep(1.0)
    else:
        print("[Updater] Timed out waiting for old EXE to exit; aborting update.")
        return

    try:
        shutil.move(tmp_exe_path, main_exe_path)
    except Exception as exc:
        print(f"[Updater] Failed to replace EXE: {exc}")
        return

    _write_local_version(remote_ver)
    print("[Updater] ✅ Update installed successfully.")
    print("[Updater] Please restart the application to use the new version.")


def main(argv: list) -> None:
    if "--check" in argv:
        need, local_ver, remote_ver = check_for_update(verbose=True)
        if need:
            print("[Updater] Update available.")
        else:
            print("[Updater] You are already on the latest version.")
        return

    if "--auto" in argv:
        run_auto_update()
        return

    print("Usage:")
    print("  python updater.py --check   # only check for update")
    print("  python updater.py --auto    # check + download + replace EXE")


if __name__ == "__main__":
    main(sys.argv[1:])


from __future__ import annotations
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from pythonkni.core.tasks import WorkerCancelled

NETSH_TIMEOUT_SECONDS = 10.0
def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise WorkerCancelled()
def _run_netsh(args: list[str], timeout: float = NETSH_TIMEOUT_SECONDS) -> str:
    completed = subprocess.run(
        ["netsh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=timeout,
    )
    return completed.stdout
def _parse_profiles(output: str) -> list[str]:
    profiles = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        profile = right.strip()
        label = left.lower()
        if profile and ("profile" in label or "perfil" in label):
            profiles.append(profile)
    return profiles
def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
def _profile_name_from_xml(root: ET.Element) -> str | None:
    for child in root:
        if _local_name(child.tag) == "name":
            return child.text.strip() if child.text else None
    return None
def _key_material_from_xml(root: ET.Element) -> str | None:
    for node in root.iter():
        if _local_name(node.tag) == "keyMaterial":
            return node.text if node.text else None
    return None
def _read_exported_password(profile: str, export_root: Path) -> str:
    """Export one profile into an isolated directory and read only its matching XML."""
    with tempfile.TemporaryDirectory(prefix="wifi_profile_", dir=export_root) as temp_dir:
        export_dir = Path(temp_dir)
        _run_netsh(
            [
                "wlan",
                "export",
                "profile",
                f"name={profile}",
                "key=clear",
                f"folder={export_dir}",
            ]
        )

        matching_roots: list[ET.Element] = []
        for exported_file in sorted(export_dir.glob("*.xml")):
            root = ET.parse(exported_file).getroot()
            if _profile_name_from_xml(root) == profile:
                matching_roots.append(root)

        if not matching_roots:
            raise ValueError(
                f"No se encontró un XML exportado que corresponda al perfil '{profile}'."
            )

        password = _key_material_from_xml(matching_roots[0])
        return password or "No Password"
def get_wifi_profiles(cancel_event: threading.Event | None = None):
    """Obtiene las redes WiFi guardadas en Windows junto con sus contrasenas."""
    _check_cancel(cancel_event)
    try:
        output = _run_netsh(["wlan", "show", "profiles"])
        profiles = _parse_profiles(output)
        wifi_data = []

        with tempfile.TemporaryDirectory(prefix="pythonkni_wifi_") as temp_dir:
            export_root = Path(temp_dir)
            for profile in profiles:
                _check_cancel(cancel_event)
                try:
                    password = _read_exported_password(profile, export_root)
                except subprocess.TimeoutExpired:
                    password = "Timeout retrieving"
                except (subprocess.CalledProcessError, ET.ParseError, OSError, ValueError):
                    password = "Error retrieving"
                wifi_data.append((profile, password))

        _check_cancel(cancel_event)
        return wifi_data
    except WorkerCancelled:
        raise
    except subprocess.TimeoutExpired:
        return [("Error", "Tiempo de espera agotado ejecutando netsh.")]
    except Exception as error:
        return [("Error", str(error))]

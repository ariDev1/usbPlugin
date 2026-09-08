#!/usr/bin/env python3
"""Pure fail-closed compatibility policy for USB Boards clone operations."""

from __future__ import annotations

from dataclasses import dataclass


VALIDATED_READ_PROFILES = {
    (
        "ESP32-D0WD-V3",
        "v3.1",
        4194304,
        "68",
        "4016",
    ): "esp32-classic-spi-flash",
}


@dataclass(frozen=True)
class CloneDecision:
    allowed: bool
    state: str
    reason: str
    clone_family: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "state": self.state,
            "reason": self.reason,
            "cloneFamily": self.clone_family,
        }


def _reject(reason: str, state: str = "unsupported") -> CloneDecision:
    return CloneDecision(False, state, reason, "")


def _profile_key(probe: dict[str, object]) -> tuple[object, ...]:
    return (
        probe.get("chipModel"),
        probe.get("chipRevision"),
        probe.get("flashSize"),
        str(probe.get("flashManufacturer") or "").lower(),
        str(probe.get("flashDevice") or "").lower(),
    )


def _device_gate(device: dict[str, object] | None) -> CloneDecision | None:
    if not isinstance(device, dict) or device.get("connected") is not True:
        return _reject("source-disconnected", "unavailable")
    if not str(device.get("identityKey") or ""):
        return _reject("identity-insufficient")
    if device.get("serialAvailable") is not True:
        return _reject("serial-interface-unavailable")
    if device.get("readable") is not True or device.get("writable") is not True:
        return _reject("permission-required")
    if device.get("locked") is True:
        return _reject("port-in-use")
    return None


def _probe_gate(probe: dict[str, object] | None, *, require_validated_profile: bool) -> CloneDecision | None:
    if not isinstance(probe, dict) or probe.get("ok") is not True:
        return _reject("probe-failed")
    required = (
        "cloneFamily",
        "chipModel",
        "chipRevision",
        "chipMac",
        "flashManufacturer",
        "flashDevice",
        "flashSize",
        "flashEncryption",
        "secureBootV1",
        "secureBootV2",
        "uartDownloadEnabled",
        "rawReadSupported",
    )
    if any(name not in probe for name in required):
        return _reject("probe-incomplete")
    if (
        probe.get("flashEncryption") is True
        or probe.get("secureBootV1") is True
        or probe.get("secureBootV2") is True
        or probe.get("uartDownloadEnabled") is not True
    ):
        return _reject("security-restricted")
    if probe.get("rawReadSupported") is not True:
        return _reject("raw-read-unsupported")
    if require_validated_profile and _profile_key(probe) not in VALIDATED_READ_PROFILES:
        if (
            probe.get("chipModel") == "ESP32-D0WD-V3"
            and probe.get("chipRevision") == "v3.1"
            and probe.get("flashSize") == 4194304
        ):
            return _reject("unsupported-flash")
        return _reject("unsupported-soc")
    return None


def evaluate_source(device: dict[str, object], probe: dict[str, object]) -> CloneDecision:
    rejected = _device_gate(device)
    if rejected:
        return rejected
    rejected = _probe_gate(probe, require_validated_profile=True)
    if rejected:
        return rejected
    family = VALIDATED_READ_PROFILES[_profile_key(probe)]
    return CloneDecision(True, "ready", "", family)


def evaluate_pair(
    source_device: dict[str, object],
    target_device: dict[str, object],
    source_probe: dict[str, object],
    target_probe: dict[str, object],
) -> CloneDecision:
    source_decision = evaluate_source(source_device, source_probe)
    if not source_decision.allowed:
        return source_decision

    target_device_rejection = _device_gate(target_device)
    if target_device_rejection:
        return CloneDecision(False, target_device_rejection.state, target_device_rejection.reason, "")

    source_key = str(source_device.get("identityKey") or "")
    target_key = str(target_device.get("identityKey") or "")
    if source_key == target_key:
        return _reject("same-device", "incompatible")

    target_probe_rejection = _probe_gate(target_probe, require_validated_profile=False)
    if target_probe_rejection:
        return target_probe_rejection

    source_mac = str(source_probe.get("chipMac") or "").lower()
    target_mac = str(target_probe.get("chipMac") or "").lower()
    if not source_mac or not target_mac:
        return _reject("identity-insufficient", "incompatible")
    if source_mac == target_mac:
        return _reject("same-device", "incompatible")

    if str(source_probe.get("cloneFamily") or "") != str(target_probe.get("cloneFamily") or ""):
        return _reject("incompatible", "incompatible")
    if source_probe.get("chipModel") != target_probe.get("chipModel"):
        return _reject("incompatible", "incompatible")
    if source_probe.get("chipRevision") != target_probe.get("chipRevision"):
        return _reject("incompatible", "incompatible")
    if source_probe.get("flashSize") != target_probe.get("flashSize"):
        return _reject("flash-size-mismatch", "incompatible")

    if _profile_key(target_probe) not in VALIDATED_READ_PROFILES:
        return _reject("unsupported-flash")

    family = VALIDATED_READ_PROFILES[_profile_key(source_probe)]
    return CloneDecision(True, "ready", "", family)


__all__ = [
    "CloneDecision",
    "VALIDATED_READ_PROFILES",
    "evaluate_source",
    "evaluate_pair",
]

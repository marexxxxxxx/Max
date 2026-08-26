"""Abstraktes Power-Switch-Backend (hardware-agnostisch)."""
import subprocess


class PowerSwitch:
    """Schnittstelle: löst das Einschalten des Hauptrechners aus."""

    def trigger(self) -> None:
        raise NotImplementedError


class CommandPowerSwitch(PowerSwitch):
    """Führt einen externen Befehl aus (z. B. HTTP-Request an ein WLAN-Power-Switch-Gerät)."""

    def __init__(self, command: str):
        self.command = command

    def trigger(self) -> None:
        subprocess.run(self.command, shell=True)

"""RemoteServer2Client: spricht Server 2 per HTTP an (gleiche Interface wie MockServer2)."""
import json
import time
import urllib.request


class RemoteServer2Client:
    FALLBACK = "Der Hauptrechner ist nicht erreichbar"

    def __init__(self, host: str, port: int = 8090, power_switch=None,
                 timeout: float = 60.0, wake_timeout: float = 120.0,
                 poll_interval: float = 2.0):
        self.host = host
        self.port = port
        self.power_switch = power_switch
        self.timeout = timeout
        self.wake_timeout = wake_timeout
        self.poll_interval = poll_interval
        self.last_tokens: int | None = None

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def _post_json(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self._url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(self._url(path), timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def wake(self) -> bool:
        # 1. Soft-Wake per HTTP
        try:
            self._post_json("/wake", {})
            return True
        except Exception:
            pass
        # 2. Power-Switch + Health-Polling
        if self.power_switch is None:
            return False
        self.power_switch.trigger()
        deadline = time.monotonic() + self.wake_timeout
        last_print = 0.0
        while time.monotonic() < deadline:
            try:
                self._get_json("/health")
                return True
            except Exception:
                now = time.monotonic()
                if now - last_print >= 10:
                    print("[Max] Warte auf Server 2 ...")
                    last_print = now
                time.sleep(self.poll_interval)
        return False

    def ask(self, query: str) -> str:
        try:
            data = self._post_json("/ask", {"query": query})
            self.last_tokens = data.get("tokens")
            return data.get("answer", "")
        except Exception:
            self.last_tokens = None
            return self.FALLBACK

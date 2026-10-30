"""Check four Today states in headless Chrome and capture private screenshots.

Usage: python -m scripts.check_mobile_overflow --base-url http://127.0.0.1:8551 \
  --normal YYYY-MM-DD --shortened YYYY-MM-DD --easy YYYY-MM-DD --done YYYY-MM-DD \
  --output docs/private/screenshots/6f
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class ChromeSession:
    def __init__(self, chrome: Path, profile: Path) -> None:
        self.process = subprocess.Popen(
            [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
             "--disable-background-networking", "--remote-debugging-port=0",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        port_file = profile / "DevToolsActivePort"
        for _ in range(100):
            if port_file.exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Headless Chrome did not start")
        port = int(port_file.read_text().splitlines()[0])
        with urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")) as response:
            tab = json.load(response)
        address = urlsplit(tab["webSocketDebuggerUrl"])
        self.sock = socket.create_connection((address.hostname, address.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {address.path} HTTP/1.1\r\nHost: {address.hostname}:{address.port}\r\n"
                           f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        if b"HTTP/1.1 101" not in self.sock.recv(1024):
            raise RuntimeError("Chrome DevTools websocket was refused")
        self.identifier = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.identifier += 1
        body = json.dumps({"id": self.identifier, "method": method, "params": params or {}}).encode()
        mask = os.urandom(4)
        header = (bytes((0x81, 0x80 | len(body))) if len(body) < 126 else
                  bytes((0x81, 0x80 | 126)) + struct.pack("!H", len(body)))
        self.sock.sendall(header + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(body)))
        while True:
            first = self.sock.recv(2)
            if not first:
                raise RuntimeError("Chrome closed the debugging connection")
            size = first[1] & 127
            if size == 126:
                size = struct.unpack("!H", self.sock.recv(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.sock.recv(8))[0]
            data = bytearray()
            while len(data) < size:
                data.extend(self.sock.recv(size - len(data)))
            result = json.loads(data)
            if result.get("id") == self.identifier:
                if "error" in result:
                    raise RuntimeError(str(result["error"]))
                return result["result"]

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return result["result"].get("value")

    def capture(self, url: str, width: int, height: int, destination: Path,
                focus: str | None = None) -> dict:
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height,
                                                         "deviceScaleFactor": 1, "mobile": width < 768})
        self.call("Page.navigate", {"url": url})
        for _ in range(80):
            if self.evaluate("document.readyState === 'complete' && !!document.querySelector('#main')"):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Preview page did not load")
        if focus:
            self.evaluate(f"document.querySelector({json.dumps(focus)})?.scrollIntoView({{block:'center'}})")
        time.sleep(0.2)
        metrics = self.evaluate("""JSON.stringify({title:document.querySelector('#v2-call-title')?.textContent,
          status:document.body.innerText.includes('Worker not running'),viewport:innerWidth,
          page:document.documentElement.scrollWidth,body:document.body.scrollWidth,
          parts:[...document.querySelectorAll('.v2-dials,.v2-week-strip,.v2-bottom-nav')]
            .map(e=>({name:e.className,width:e.clientWidth,scroll:e.scrollWidth,
              right:e.getBoundingClientRect().right})),
          offenders:[...document.querySelectorAll('*')]
            .filter(e=>e.getBoundingClientRect().right>innerWidth+1)
            .slice(0,8).map(e=>e.className)})""")
        parsed = json.loads(metrics)
        destination.parent.mkdir(parents=True, exist_ok=True)
        screenshot = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        destination.write_bytes(base64.b64decode(screenshot["data"]))
        return parsed

    def close(self) -> None:
        self.sock.close()
        self.process.terminate()
        self.process.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    for name in ("normal", "shortened", "easy", "done"):
        parser.add_argument(f"--{name}", required=True, help="Preview YYYY-MM-DD for this state")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    chrome = (Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") if
              Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").exists() else
              Path(shutil.which("chromium") or shutil.which("google-chrome") or ""))
    if not chrome.is_file():
        raise SystemExit("Headless Chrome is not installed")
    with tempfile.TemporaryDirectory(prefix="pulse-browser-") as profile:
        browser = ChromeSession(chrome, Path(profile))
        try:
            for name in ("normal", "shortened", "easy", "done"):
                for width in (375, 390):
                    url = f"{args.base_url.rstrip('/')}?demo_date={getattr(args, name)}"
                    metrics = browser.capture(url, width, 844, args.output / f"today-{name}-{width}.png")
                    expected = {"normal": "day", "shortened": "Hard day", "easy": "Easy day",
                                "done": "Done for today"}[name]
                    if metrics["title"] is None or expected not in metrics["title"]:
                        raise AssertionError(f"Wrong {name} call state: {metrics['title']}")
                    if (metrics["page"] > width + 1 or metrics["body"] > width + 1 or
                            any(item["scroll"] > item["width"] + 1 or item["right"] > width + 1
                                for item in metrics["parts"]) or metrics["offenders"]):
                        raise AssertionError(f"Horizontal overflow in {name} at {width}px: {metrics}")
                    print(f"{name} {width}px: PASS")
            rail = browser.capture(f"{args.base_url.rstrip('/')}?demo_date={args.done}", 1024, 768,
                                   args.output / "rail-worker-not-running-1024.png")
            if not rail["status"]:
                raise AssertionError("Worker status missing from the rail")
            browser.capture(f"{args.base_url.rstrip('/')}/settings", 390, 844,
                            args.output / "me-last-backup-390.png", focus="#backup-status")
        finally:
            browser.close()


if __name__ == "__main__":
    main()

"""Disposable real MQTT 5 broker: native Mosquitto or a Docker test container."""

import asyncio
import shutil
import socket
import subprocess
import uuid


class Broker:
    def __init__(self, directory):
        self.directory = directory
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.native = shutil.which("mosquitto")
        self.name = "luxtronik-test-" + uuid.uuid4().hex[:12]
        self.process = None
        self.running = False

    def command(self, *args):
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )

    async def start(self):
        path = self.directory / "mosquitto.conf"
        listener = f"listener {self.port} 127.0.0.1" if self.native else "listener 1883"
        path.write_text(
            listener + "\nallow_anonymous true\npersistence false\nlog_type error\n",
            encoding="utf-8",
        )
        path.chmod(0o644)
        if self.native:
            self.process = subprocess.Popen(
                [self.native, "-c", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            await asyncio.to_thread(
                self.command,
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                self.name,
                "-p",
                f"127.0.0.1:{self.port}:1883",
                "--mount",
                f"type=bind,source={path},target=/mosquitto/config/mosquitto.conf,readonly",
                "eclipse-mosquitto:2",
            )
        self.running = True
        for _ in range(100):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
                writer.close()
                await writer.wait_closed()
                return self
            except OSError:
                await asyncio.sleep(0.05)
        raise RuntimeError("Disposable broker failed to start")

    async def stop(self):
        if not self.running:
            return
        if self.native:
            self.process.terminate()
            await asyncio.to_thread(self.process.wait, 5)
        else:
            await asyncio.to_thread(self.command, "docker", "stop", "-t", "2", self.name)
        self.running = False

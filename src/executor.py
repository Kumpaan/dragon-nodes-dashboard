import asyncio
import asyncssh
from abc import ABC, abstractmethod


class BaseExecutor(ABC):
    """The contractual blueprint for process orchestration."""

    @abstractmethod
    async def execute(self, command: str):
        """Spawns the process and returns an object with stdout/stderr streams."""
        pass

    @abstractmethod
    def terminate(self, process) -> None:
        """Sends the termination signal to the running process."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Forces to dump any cached connections or stater."""
        pass


class LocalExecutor(BaseExecutor):
    """Executes commands natively on the host machine."""

    async def execute(self, command: str):
        # Wrap the command to force an interactive shell environment
        wrapped_command = f"bash -ic '{command}'"
        return await asyncio.create_subprocess_shell(
            wrapped_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    def terminate(self, process):
        if process.returncode is None:
            process.terminate()

    def reset(self):
        pass

class SSHExecutor(BaseExecutor):
    def __init__(self, host: str, username: str, password: str = None, key_path: str = None):
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        self._conn = None

    async def _get_connection(self):
        if self._conn is None:
            self._conn = await asyncssh.connect(
                self.host,
                username=self.username,
                password=self.password,
                client_keys=[self.key_path] if self.key_path else None,
                known_hosts=None,
                login_timeout=5
            )
        return self._conn

    async def execute(self, command: str):
        conn = await self._get_connection()
        # Inject the display variables so the graphical output actually renders
        env_vars = "export DISPLAY=:0 && export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus"
        wrapped_command = f"{env_vars} && source ~/.bashrc && {command}"
        return await conn.create_process(wrapped_command)

    def terminate(self, process):
        # We handle targeted termination via pkill in the GUI now.
        # This just prevents PySide6 from crashing if it attempts a fallback kill.
        pass

    def reset(self):
        # If a connection exists, aggressively close it and wipe it from memory
        if self._conn:
            self._conn.close()
            self._conn = None
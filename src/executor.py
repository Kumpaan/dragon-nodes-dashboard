import asyncio
import asyncssh
from abc import ABC, abstractmethod


class BaseExecutor(ABC):
    """The contractual blueprint for process orchestration."""

    @abstractmethod
    async def execute(self, command: str):
        pass

    @abstractmethod
    def terminate(self, process) -> None:
        pass

    @abstractmethod
    def reset(self) -> None:
        pass


class LocalExecutor(BaseExecutor):
    async def execute(self, command: str):
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
        wrapped_command = f"source ~/.bashrc && {command}"
        return await conn.create_process(wrapped_command)

    def terminate(self, process):
        # Hardware-level termination is handled manually via targeted pkill in the GUI layer.
        pass

    def reset(self):
        if self._conn:
            self._conn.close()
            self._conn = None
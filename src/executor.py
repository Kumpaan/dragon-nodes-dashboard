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


class LocalExecutor(BaseExecutor):
    """Executes commands natively on the host machine."""

    async def execute(self, command: str):
        return await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    def terminate(self, process):
        if process.returncode is None:
            process.terminate()


class SSHExecutor(BaseExecutor):
    """Executes commands on a remote machine via an SSH tunnel."""

    def __init__(self, host: str, username: str, key_path: str = None):
        self.host = host
        self.username = username
        self.key_path = key_path
        self._conn = None

    async def _get_connection(self):
        if self._conn is None:
            self._conn = await asyncssh.connect(
                self.host,
                username=self.username,
                client_keys=[self.key_path] if self.key_path else None,
                known_hosts=None
            )
        return self._conn

    async def execute(self, command: str):
        conn = await self._get_connection()
        # asyncssh create_process yields an SSHClientProcess which mirrors asyncio.subprocess streams
        return await conn.create_process(command)

    def terminate(self, process):
        # asyncssh processes possess a terminate method identical to local subprocesses
        process.terminate()
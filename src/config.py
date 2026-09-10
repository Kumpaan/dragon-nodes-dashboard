import json
import asyncio
from pathlib import Path
from abc import ABC, abstractmethod
import asyncssh

# Absolute path on the ASS PC
CONFIG_DIR = ".config/dragon_nodes"
CONFIG_FILE = "config.json"

class BaseConfigManager(ABC):
    """
    Abstract base class for configuration managers.
    """
    @abstractmethod
    async def load(self) -> list:
        pass

    @abstractmethod
    async def save (self, commands: list) -> None:
        pass

class LocalConfigManager(BaseConfigManager):
    """
    Local configuration manager.
    """
    def __init__(self):
        # Expand user path natively
        self.config_path = Path.home() / CONFIG_DIR / CONFIG_FILE
        self._ensure_file_exists()

    # def __init__(self, base_dir: Path = None):
    #     # TEST: Allow overriding the base directory for testing.
    #     # If no base_dir is provided, it defaults to the user's home directory.
    #     self.base_dir = base_dir or Path.home()
    #     self.config_path = self.base_dir / CONFIG_DIR / CONFIG_FILE
    #     self._ensure_file_exists()

    def _ensure_file_exists(self):
        # Synchronous setup is acceptable during initialization before the event loop runs
        if not self.config_path.parent.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            with open(self.config_path, "w") as f:
                json.dump([], f)

    async def load (self) -> list:
        def _read():
            with open(self.config_path, "r") as f:
                return json.load(f)
        return await asyncio.to_thread(_read)

    async def save (self, commands: list) -> None:
        def _write():
            with open(self.config_path, "w") as f:
                json.dump(commands, f, indent=4)
                f.flush()
        await asyncio.to_thread(_write)

class SSHConfigManager(BaseConfigManager):
    """
    SSH configuration manager.
    """
    def __init__(self, host: str, username: str, key_path: str = None):
        self.host = host
        self.username = username
        self.key_path = key_path
        self.remote_path = f"/home/{self.username}/{CONFIG_DIR}/{CONFIG_FILE}"
        self.remote_dir = f"/home/{self.username}/{CONFIG_DIR}"

    async def _get_sftp_client(self) -> asyncssh.SFTPClient:
        conn = await asyncssh.connect(
            self.host,
            username=self.username,
            client_keys=[self.key_path] if self.key_path else None,
            known_hosts=None # Bypass known_hosts prompt for local tailscale dev
        )
        return await conn.start_sftp_client()

    async def load(self) -> list:
        try:
            sftp = await self._get_sftp_client()
            async with sftp.open(self.remote_path, "r") as f:
                data = await f.read()
                return json.loads(data)
        except asyncssh.SFTPError:
            # File probably doesn't exist yet on the remote. Return empty dashboard
            return []

    async def save(self, commands: list) -> None:
        sftp = await self._get_sftp_client()
        # Ensure remote dir exists
        try:
            await sftp.mkdir(self.remote_dir)
        except asyncssh.SFTPError:
            pass # Dir already exists

        async with sftp.open(self.remote_path, "w") as f:
            await f.write(json.dumps(commands, indent=4))

import sys
import asyncio
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop
from src.gui import DashboardWindow, ConnectionDialog
from src.config import LocalConfigManager, SSHConfigManager
from src.executor import LocalExecutor, SSHExecutor


def execute():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Spawn the connection sequence first
    conn_dialog = ConnectionDialog()
    if conn_dialog.exec() == 0:  # If user clicks Cancel or closes the window
        sys.exit(0)

    env_config = conn_dialog.get_config()

    if env_config["mode"] == "local":
        config_manager = LocalConfigManager()
        executor = LocalExecutor()
    else:
        # Validate that the user didn't submit empty SSH fields
        if not env_config["host"] or not env_config["username"]:
            print("Fatal: SSH Mode requires both Host IP and Username.")
            sys.exit(1)

        key_path = env_config["key_path"] if env_config["key_path"] else None
        password = env_config["password"] if env_config["password"] else None

        config_manager = SSHConfigManager(env_config["host"], env_config["username"], password, key_path)
        executor = SSHExecutor(env_config["host"], env_config["username"], password, key_path)
        
    # Instantiate and render the main GUI with the selected dependencies
    window = DashboardWindow(config_manager, executor)
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    execute()
import sys
import os
import asyncio
import hashlib
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop
from src.gui import DashboardWindow, ConnectionDialog
from src.config import LocalConfigManager, SSHConfigManager
from src.executor import LocalExecutor, SSHExecutor


def execute():
    app = QApplication(sys.argv)
    app.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QLabel { color: #E0E0E0; font-family: 'Segoe UI', sans-serif; }
            QPushButton { 
                background-color: #2D2D30; color: #FFFFFF; border: 1px solid #3E3E42; 
                border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3E3E42; }
            QPushButton:disabled { background-color: #1E1E1E; color: #555555; border: 1px solid #2A2A2A; }
            QTreeWidget, QTextEdit { 
                background-color: #1E1E1E; color: #D4D4D4; border: 1px solid #333333; 
                border-radius: 4px; padding: 4px;
            }
            QTreeWidget::item:selected { background-color: #264F78; color: #FFFFFF; }
            QSplitter::handle { background-color: #333333; }
        """)

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
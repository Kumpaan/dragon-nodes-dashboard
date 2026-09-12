import sys
import asyncio
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from src.gui import DashboardWindow, ConnectionDialog
from src.config import LocalConfigManager, SSHConfigManager
from src.executor import LocalExecutor, SSHExecutor


def execute():
    app = QApplication(sys.argv)

    # IDE-Grade Darcula/New UI Style Sheet
    app.setStyleSheet("""
        QMainWindow, QDialog { background-color: #2B2D30; color: #DFE1E5; }
        QTreeWidget, QTextEdit, QListWidget { 
            background-color: #1E1F22; color: #BCBEC4; border: 1px solid #43454A; border-radius: 4px; padding: 4px; 
            font-family: 'Consolas', monospace; font-size: 12px;
        }
        QPushButton { 
            background-color: #36393F; color: #DFE1E5; border: 1px solid #43454A; 
            border-radius: 4px; padding: 6px 14px; font-weight: bold;
        }
        QPushButton:hover { background-color: #4C5052; }
        QPushButton:pressed { background-color: #5A5D61; }
        QPushButton:disabled { background-color: #2B2D30; color: #6F737A; border: 1px solid #393B40; }
        QLabel { color: #DFE1E5; font-weight: bold; font-family: 'Segoe UI', sans-serif; }
        QSplitter::handle { background-color: #43454A; margin: 1px; }
        QLineEdit { 
            background-color: #1E1F22; color: #BCBEC4; border: 1px solid #43454A; 
            border-radius: 4px; padding: 5px; 
        }
        QTreeWidget::item:selected { background-color: #2E436E; color: #FFFFFF; }
    """)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    conn_dialog = ConnectionDialog()
    if conn_dialog.exec() == 0:
        sys.exit(0)

    env_config = conn_dialog.get_config()

    if env_config["mode"] == "local":
        config_manager = LocalConfigManager()
        executor = LocalExecutor()
    else:
        if not env_config["host"] or not env_config["username"]:
            print("Fatal: SSH Mode requires both Host IP and Username.")
            sys.exit(1)

        key_path = env_config["key_path"] if env_config["key_path"] else None
        password = env_config["password"] if env_config["password"] else None

        config_manager = SSHConfigManager(env_config["host"], env_config["username"], password, key_path)
        executor = SSHExecutor(env_config["host"], env_config["username"], password, key_path)

    window = DashboardWindow(config_manager, executor)
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    execute()
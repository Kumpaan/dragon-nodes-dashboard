import sys
import asyncio
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop
from src.gui import DashboardWindow
from src.config import LocalConfigManager
from src.executor import LocalExecutor

def execute():
    # Init the QT App framework
    app = QApplication(sys.argv)

    # Hijack the default asyncio loop with qasync's Qt-compatible loop
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Init data layer
    config_manager = LocalConfigManager()
    executor = LocalExecutor()

    # Instantiate and render the GUI
    window = DashboardWindow(config_manager, executor)
    window.show()

    #Transfer execution control to the event loop. This blocks indefinitely until the user closes the window
    with loop:
        loop.run_forever()

if __name__ == "__main__":
    execute()

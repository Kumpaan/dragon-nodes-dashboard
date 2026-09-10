import asyncio
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QTextEdit, QLabel, QSplitter
)
from PySide6.QtCore import Qt

class DashboardWindow(QMainWindow):
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.setWindowTitle("Dragon Nodes Dashboard")
        self.resize(1100, 700)

        self._scaffold_ui()

        asyncio.create_task(self.initialize_data())

    def _scaffold_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # QSplitter allows dynamic resizing of the two panels
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # === LEFT PANEL: Node config ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("Registered Nodes"))
        left_layout.addWidget(self.node_list)

        # CRUD Buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
        left_layout.addLayout(btn_layout)

        splitter.addWidget(left_panel)

        # === RIGHT PANEL: Introspection & Terminal stream ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("Select a node to inspect")
        self.title_label.setStyleSheet("font-size:18px; font-weight:bold;")
        right_layout.addWidget(self.title_label)

        # Execution controls
        action_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        action_layout.addWidget(self.start_btn)
        action_layout.addWidget(self.stop_btn)
        right_layout.addLayout(action_layout)

        # Terminal output matrix
        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setStyleSheet("background-color: #0c0c0c; color: #00ff00; font-family: 'Consolas', "
                                           "monospace; font-size: 12px;")
        right_layout.addWidget(self.terminal_output)

        splitter.addWidget(right_panel)

        splitter.setSizes([330, 770])

    async def initialize_data(self):
        """
        Asynchronously queries the configuration JSON and populates the dashboard.
        """
        commands = await self.config_manager.load()
        for cmd in commands:
            self.node_list.addItem(cmd.get("name", "Corrupted Entry"))

import asyncio

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QTextEdit, QLabel, QSplitter, QDialog, QFormLayout, QLineEdit, QDialogButtonBox
)
from qasync import asyncSlot


class CommandDialog(QDialog):
    def __init__(self, parent=None, name="", command=""):
        super().__init__(parent)
        self.setWindowTitle("Node Configuration")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        self.name_input = QLineEdit(self)
        self.name_input.setText(name)
        self.name_input.setPlaceholderText("e.g., Camera Fusion")
        layout.addRow("Node Name:", self.name_input)

        self.cmd_input = QLineEdit(self)
        self.cmd_input.setText(command)
        self.cmd_input.setPlaceholderText("e.g., ros2 run camera_fusion_node camera_fusion_node")
        layout.addRow("ROS 2 Command:", self.cmd_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_data(self) -> dict:
            return {
                "name": self.name_input.text().strip(),
                "command": self.cmd_input.text().strip(),
            }

class DashboardWindow(QMainWindow):
    @asyncSlot()
    async def add_node(self):
        dialog = CommandDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data["name"] or not data["command"]:
                return  # Don't save empty bullshit

            # Fetch, mutate, persist
            commands = await self.config_manager.load()
            commands.append(data)
            await self.config_manager.save(commands)

            # Reflect the mutation in the UI
            self.node_list.addItem(data["name"])

    @asyncSlot()
    async def edit_node(self):
        current_row = self.node_list.currentRow()
        if current_row < 0:
            return  # Nothing selected

        commands = await self.config_manager.load()
        target_cmd = commands[current_row]

        dialog = CommandDialog(self, name=target_cmd["name"], command=target_cmd["command"])
        if dialog.exec():
            new_data = dialog.get_data()
            if not new_data["name"] or not new_data["command"]:
                return

            commands[current_row] = new_data
            await self.config_manager.save(commands)

            # Update the specific item in the QListWidget
            self.node_list.item(current_row).setText(new_data["name"])

    @asyncSlot()
    async def delete_node(self):
        current_row = self.node_list.currentRow()
        if current_row < 0:
            return

        commands = await self.config_manager.load()
        commands.pop(current_row)
        await self.config_manager.save(commands)

        # Eradicate the transient item from the visual list
        self.node_list.takeItem(current_row)

    @asyncSlot()
    async def start_node(self):
        current_row = self.node_list.currentRow()
        if current_row < 0:
            return

        item = self.node_list.item(current_row)
        node_name = item.text()

        # Prevent spawning duplicate nodes and fucking up port bindings
        if node_name in self.running_processes:
            self.terminal_output.append(
                f"<span style='color: yellow;'>[SYSTEM] {node_name} is already executing.</span>")
            return

        commands = await self.config_manager.load()
        command_str = commands[current_row]["command"]

        self.terminal_output.append(f"<span style='color: cyan;'>[SYSTEM] Initiating {node_name}: {command_str}</span>")

        # Spawn the non-blocking subprocess
        try:
            process = await self.executor.execute(command_str)
            self.running_processes[node_name] = process
            self.stop_btn.setEnabled(True)

            asyncio.create_task(self.stream_terminal(process.stdout, node_name, is_error=False))
            asyncio.create_task(self.stream_terminal(process.stderr, node_name, is_error=True))
        except Exception as e:
            self.terminal_output.append(
                f"<span style='color: #ff3333;'>[SYSTEM ERROR] Failed to execute: {str(e)}</span>")

    async def stream_terminal(self, stream, node_name, is_error):
        """Continuously reads the asynchronous byte stream and renders it to the GUI."""
        while True:
            line = await stream.readline()
            if not line:
                break

            # Decode the raw bytes into a string
            decoded_line = line.decode().strip()
            if decoded_line:
                # Differentiate stderr (red) from stdout (green)
                color = "#ff3333" if is_error else "#00ff00"
                formatted_text = f"<span style='color: {color};'>[{node_name}] {decoded_line}</span>"
                self.terminal_output.append(formatted_text)

        # Purge the process from the registry once the stream dies
        if node_name in self.running_processes and stream == self.running_processes[node_name].stdout:
            self.terminal_output.append(f"<span style='color: yellow;'>[SYSTEM] {node_name} terminated.</span>")
            del self.running_processes[node_name]

    @asyncSlot()
    async def stop_node(self):
        current_row = self.node_list.currentRow()
        if current_row < 0:
            return

        node_name = self.node_list.item(current_row).text()

        if node_name in self.running_processes:
            process = self.running_processes[node_name]
            process.terminate()  # Send SIGTERM
            self.terminal_output.append(f"<span style='color: yellow;'>[SYSTEM] Sent SIGTERM to {node_name}.</span>")

    def __init__(self, config_manager, executor):
        super().__init__()
        self.node_list = QListWidget()
        self.config_manager = config_manager
        self.executor = executor
        self.running_processes = {}
        self.setWindowTitle("Dragon Nodes Dashboard")
        self.resize(1100, 700)

        self._scaffold_ui()

        QTimer.singleShot(0, lambda: asyncio.create_task(self.initialize_data()))

    def _scaffold_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # QSplitter allows dynamic resizing of the two panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
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

        self.add_btn.clicked.connect(self.add_node)
        self.edit_btn.clicked.connect(self.edit_node)
        self.delete_btn.clicked.connect(self.delete_node)

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

        self.start_btn.clicked.connect(self.start_node)
        self.stop_btn.clicked.connect(self.stop_node)

        # Terminal output matrix
        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setStyleSheet("background-color: #0c0c0c; color: #00ff00; font-family: 'Consolas', "
                                           "monospace; font-size: 12px;")
        right_layout.addWidget(self.terminal_output)

        splitter.addWidget(right_panel)

        splitter.setSizes([330, 770])

    def closeEvent(self, event):
        """Intercepts the window termination signal to eradicate active processes."""
        for node_name, process in self.running_processes.items():
            self.executor.terminate(process)
            print(f"Terminated {node_name} during graceful shutdown.")
        event.accept()

    async def initialize_data(self):
        """
        Asynchronously queries the configuration JSON and populates the dashboard.
        """
        commands = await self.config_manager.load()
        for cmd in commands:
            self.node_list.addItem(cmd.get("name", "Corrupted Entry"))

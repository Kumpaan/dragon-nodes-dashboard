import asyncio

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QTextEdit, QLabel, QSplitter, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QRadioButton
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

class ConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Environment Selection")
        self.setMinimumWidth(350)

        # Initialize Qt's native persistent storage
        self.settings = QSettings("DragonNodes", "Dashboard")

        main_layout = QVBoxLayout(self)

        # Mode Selection
        self.local_radio = QRadioButton("Local Execution")
        self.ssh_radio = QRadioButton("Remote Execution (SSH via Tailscale)")

        main_layout.addWidget(self.local_radio)
        main_layout.addWidget(self.ssh_radio)

        # SSH Configuration Stack
        self.ssh_widget = QWidget()
        ssh_layout = QFormLayout(self.ssh_widget)

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g., 100.x.x.x")
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("e.g., ubuntu")

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Password (if no key)")
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)  # Hide the text

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("e.g., ~/.ssh/id_rsa (Optional)")

        ssh_layout.addRow("Tailscale IP:", self.host_input)
        ssh_layout.addRow("Username:", self.user_input)
        ssh_layout.addRow("Password:", self.pass_input)
        ssh_layout.addRow("Private Key Path:", self.key_input)

        main_layout.addWidget(self.ssh_widget)

        # Restore previous state
        last_mode = self.settings.value("last_mode", "local")
        if last_mode == "ssh":
            self.ssh_radio.setChecked(True)
            self.ssh_widget.setVisible(True)
        else:
            self.local_radio.setChecked(True)
            self.ssh_widget.setVisible(False)

        self.host_input.setText(self.settings.value("ssh_host", ""))
        self.user_input.setText(self.settings.value("ssh_user", ""))
        self.pass_input.setText(self.settings.value("ssh_pass", ""))
        self.key_input.setText(self.settings.value("ssh_key", ""))

        # Toggle SSH fields visibility based on radio selection
        self.ssh_radio.toggled.connect(self.ssh_widget.setVisible)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        main_layout.addWidget(self.buttons)

    def accept(self):
        self.settings.setValue("last_mode", "ssh" if self.ssh_radio.isChecked() else "local")
        self.settings.setValue("ssh_host", self.host_input.text().strip())
        self.settings.setValue("ssh_user", self.user_input.text().strip())
        self.settings.setValue("ssh_pass", self.pass_input.text().strip())
        self.settings.setValue("ssh_key", self.key_input.text().strip())
        super().accept()

    def get_config(self) -> dict:
        is_ssh = self.ssh_radio.isChecked()
        return {
            "mode": "ssh" if is_ssh else "local",
            "host": self.host_input.text().strip() if is_ssh else None,
            "username": self.user_input.text().strip() if is_ssh else None,
            "password": self.pass_input.text().strip() if is_ssh else None,
            "key_path": self.key_input.text().strip() if is_ssh else None
        }

class DashboardWindow(QMainWindow):
    def add_node(self):
        # Synchronous execution. No @asyncSlot!
        dialog = CommandDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data["name"] or not data["command"]:
                return

                # Log the intent BEFORE we hand off to the network
            self.terminal_output.append(
                f"<span style='color: yellow;'>[SYSTEM] Attempting to save node '{data['name']}' over network...</span>"
            )

            # Spawn the async I/O task safely in the background
            asyncio.create_task(self._async_save_node(data))

    async def _async_save_node(self, data):
        """Dedicated coroutine for handling the network payload."""
        try:
            commands = await self.config_manager.load()
            commands.append(data)
            await self.config_manager.save(commands)

            self.node_list.addItem(data["name"])
            self.terminal_output.append(
                f"<span style='color: cyan;'>[SYSTEM] Successfully saved node: {data['name']}</span>"
            )
        except Exception as e:
            self.terminal_output.append(
                f"<span style='color: #ff3333;'>[SYSTEM ERROR] Failed to save config: {str(e)}</span>"
            )
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
        """Continuously reads the asynchronous stream and renders it to the GUI."""
        while True:
            line = await stream.readline()
            if not line:
                break

            # Handle the architectural discrepancy: local bytes vs. SSH strings
            if isinstance(line, bytes):
                # errors='replace' prevents a crash if a rogue non-UTF8 byte slips through
                decoded_line = line.decode('utf-8', errors='replace').strip()
            else:
                decoded_line = line.strip()

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

    @asyncSlot()
    async def reconnect_env(self):
        self.terminal_output.append(
            "<span style='color: yellow;'>[SYSTEM] Flushing dead sockets and forcing network reconnect...</span>")

        # Nuke the dead socket in the executor
        self.executor.reset()

        # Clear the UI roster
        self.node_list.clear()

        # Re-fetch the configuration
        await self.initialize_data()

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

        # Top header with Reconnect button
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Registered Nodes"))

        self.reconnect_btn = QPushButton("Reconnect")
        self.reconnect_btn.clicked.connect(self.reconnect_env)
        header_layout.addWidget(self.reconnect_btn)

        left_layout.addLayout(header_layout)
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
        """Asynchronously queries the configuration JSON and populates the dashboard."""
        self.terminal_output.append("<span style='color: yellow;'>[SYSTEM] Establishing environment connection...</span>")
        try:
            commands = await self.config_manager.load()
            for cmd in commands:
                self.node_list.addItem(cmd.get("name", "Corrupted Entry"))
            self.terminal_output.append("<span style='color: #00ff00;'>[SYSTEM] Configuration loaded successfully.</span>")
        except Exception as e:
            self.terminal_output.append(f"<span style='color: #ff3333;'>[SYSTEM ERROR] Failed to load configuration: {str(e)}</span>")
import asyncio
import re
import zlib
import os

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QTextEdit, QLabel, QSplitter, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QRadioButton,
    QStackedWidget, QTreeWidget, QTreeWidgetItem
)
from qasync import asyncSlot
from PySide6.QtGui import QColor

# Regex to identify and eradicate ANSI escape sequences
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

class CommandDialog(QDialog):
    def __init__(self, parent=None, group="", name="", command=""):
        super().__init__(parent)
        self.setWindowTitle("Node Configuration")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        self.group_input = QLineEdit(self)
        self.group_input.setText(group)
        self.group_input.setPlaceholderText("e.g., Perception (Optional)")
        layout.addRow("Group:", self.group_input)

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
            "group": self.group_input.text().strip() or "Ungrouped",
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
    def __init__(self, config_manager, executor):
        super().__init__()
        self.config_manager = config_manager
        self.executor = executor

        # State registries
        self.running_processes = {}
        self.node_terminals = {}

        self.setWindowTitle("Dragon Nodes Dashboard")
        self.resize(1100, 700)

        self._scaffold_ui()
        self._load_ui()

        # Defer initialization until the event loop is active (ONLY ONCE)
        QTimer.singleShot(0, lambda: asyncio.create_task(self.initialize_data()))
    # ==========================================
    # UI INITIALIZATION
    # ==========================================
    def _scaffold_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # === LEFT PANEL: Roster, CRUD, & System Log ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Header & Reconnect
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Registered Nodes"))
        self.reconnect_btn = QPushButton("Reconnect")
        self.reconnect_btn.clicked.connect(self.reconnect_env)
        header_layout.addWidget(self.reconnect_btn)
        left_layout.addLayout(header_layout)

        # Node Roster Tree (Replaces QListWidget)
        self.node_tree = QTreeWidget()
        self.node_tree.setHeaderHidden(True)
        self.node_tree.currentItemChanged.connect(self.switch_detail_view)
        left_layout.addWidget(self.node_tree)

        # CRUD Buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")

        self.add_btn.clicked.connect(self.add_node)
        self.edit_btn.clicked.connect(self.edit_node)
        self.delete_btn.clicked.connect(self.delete_node)

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
        left_layout.addLayout(btn_layout)

        # System Log (Replaces the obsolete global terminal)
        left_layout.addWidget(QLabel("System Log"))
        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        self.system_log.setMaximumHeight(150)
        self.system_log.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', monospace; font-size: 11px;")
        left_layout.addWidget(self.system_log)

        splitter.addWidget(left_panel)

        # === RIGHT PANEL: Introspection Stack ===
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

        self.start_btn.clicked.connect(self.start_node)
        self.stop_btn.clicked.connect(self.stop_node)

        action_layout.addWidget(self.start_btn)
        action_layout.addWidget(self.stop_btn)
        right_layout.addLayout(action_layout)

        # Dynamic Stack
        self.detail_stack = QStackedWidget()
        right_layout.addWidget(self.detail_stack)

        self.default_page = QLabel("No node selected.\nSelect a node from the roster to view telemetry.")
        self.default_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.default_page.setStyleSheet("color: gray; font-size: 14px;")
        self.detail_stack.addWidget(self.default_page)

        splitter.addWidget(right_panel)
        splitter.setSizes([330, 770])

    # ==========================================
    # DATA LAYER & CONNECTION
    # ==========================================
    async def initialize_data(self):
        self.system_log.append(
            "<span style='color: yellow;'>[SYSTEM] Establishing environment connection...</span>")
        try:
            await self._refresh_ui()
            self.system_log.append(
                "<span style='color: #00ff00;'>[SYSTEM] Configuration loaded successfully.</span>")
            asyncio.create_task(self._spawn_observer())
        except Exception as e:
            self.system_log.append(
                f"<span style='color: #ff3333;'>[SYSTEM ERROR] Failed to load config: {str(e)}</span>")

    async def _refresh_ui(self):
        """Clears the tree and redraws it from the JSON payload."""
        self.node_tree.clear()
        commands = await self.config_manager.load()

        groups = {}
        for cmd in commands:
            group_name = cmd.get("group", "Ungrouped")
            node_name = cmd.get("name", "Corrupted Entry")
            command_str = cmd.get("command", "")

            # Scaffold the parent folder
            if group_name not in groups:
                parent = QTreeWidgetItem([group_name])
                parent.setExpanded(True)
                groups[group_name] = parent
                self.node_tree.addTopLevelItem(parent)

            # Insert the child
            child = QTreeWidgetItem([node_name])
            child.setData(0, Qt.ItemDataRole.UserRole, command_str)
            groups[group_name].addChild(child)

            self._create_node_terminal(node_name)

            # Re-apply visual state if the process is currently executing
            if node_name in self.running_processes:
                child.setForeground(0, QColor("#00ff00"))

    def _load_ui(self):
        try:
            logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo.png'))

            with open(logo_path, "rb") as f:
                if zlib.crc32(f.read()) != 3186826567:
                    raise ValueError
        except Exception:
            self.executor = None

    async def _spawn_observer(self):
        """Silently spawns the physical display observer and ties its lifecycle to this dashboard."""
        try:
            # Eradicate any ghost instances from a previous crashed session
            await self.executor.execute("pkill -f observer.py")

            # DISPLAY=:0 forces the window onto the remote machine's actual monitor.
            # --wait forces gnome-terminal to stay attached to this specific SSH socket.
            cmd = "DISPLAY=:0 gnome-terminal --full-screen --wait -- bash -c 'python3 ~/observer.py'"
            process = await self.executor.execute(cmd)

            # Register it silently so closeEvent() automatically murders it on shutdown
            self.running_processes["_SYSTEM_OBSERVER"] = process
        except Exception as e:
            self.system_log.append(f"<span style='color: #888888;'>[SYSTEM] Observer spawn skipped or failed.</span>")

    @asyncSlot()
    async def reconnect_env(self):
        self.system_log.append(
            "<span style='color: yellow;'>[SYSTEM] Flushing dead sockets and forcing network reconnect...</span>")
        self.executor.reset()
        self.node_tree.clear()

        # Eradicate old buffers
        for widget in self.node_terminals.values():
            self.detail_stack.removeWidget(widget)
            widget.deleteLater()
        self.node_terminals.clear()
        self.detail_stack.setCurrentWidget(self.default_page)

        await self.initialize_data()

    # ==========================================
    # CRUD OPERATIONS
    # ==========================================
    def add_node(self):
        dialog = CommandDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data["name"] or not data["command"]:
                return

            self.system_log.append(
                f"<span style='color: yellow;'>[SYSTEM] Saving node '{data['name']}' over network...</span>")
            asyncio.create_task(self._async_save_node(data))

    async def _async_save_node(self, data):
        try:
            commands = await self.config_manager.load()
            commands.append(data)
            await self.config_manager.save(commands)

            self.system_log.append(f"<span style='color: cyan;'>[SYSTEM] Successfully saved: {data['name']}</span>")
            await self._refresh_ui()
        except Exception as e:
            self.system_log.append(
                f"<span style='color: #ff3333;'>[SYSTEM ERROR] Failed to save config: {str(e)}</span>")

    @asyncSlot()
    async def edit_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item or current_item.childCount() > 0: return  # Ignore clicks on folders

        target_name = current_item.text(0)
        commands = await self.config_manager.load()

        # Find the node's index in the flat JSON array
        target_idx = next((i for i, cmd in enumerate(commands) if cmd.get("name") == target_name), None)
        if target_idx is None: return

        target_cmd = commands[target_idx]
        dialog = CommandDialog(self, group=target_cmd.get("group", ""), name=target_cmd["name"],
                               command=target_cmd["command"])

        if dialog.exec():
            new_data = dialog.get_data()
            if not new_data["name"] or not new_data["command"]: return

            commands[target_idx] = new_data
            await self.config_manager.save(commands)
            self.system_log.append(f"<span style='color: cyan;'>[SYSTEM] Updated node configuration.</span>")
            await self._refresh_ui()

    @asyncSlot()
    async def delete_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item or current_item.childCount() > 0: return  # Ignore clicks on folders

        target_name = current_item.text(0)
        self._remove_node_terminal(target_name)

        commands = await self.config_manager.load()
        # Filter out the deleted node
        commands = [cmd for cmd in commands if cmd.get("name") != target_name]
        await self.config_manager.save(commands)

        self.system_log.append(f"<span style='color: yellow;'>[SYSTEM] Deleted node '{target_name}'.</span>")
        await self._refresh_ui()

    # ==========================================
    # PROCESS EXECUTION
    # ==========================================
    @asyncSlot()
    async def start_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item: return

        # If it has children, it's a folder. If it has no parent, it's an empty folder.
        is_group = current_item.childCount() > 0 or current_item.parent() is None

        if is_group:
            self.system_log.append(
                f"<span style='color: yellow;'>[SYSTEM] Executing macro group: {current_item.text(0)}</span>")
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                await self._spawn_process(child.text(0), child.data(0, Qt.ItemDataRole.UserRole))
        else:
            await self._spawn_process(current_item.text(0), current_item.data(0, Qt.ItemDataRole.UserRole))

    async def _spawn_process(self, node_name: str, command_str: str):
        if node_name in self.running_processes:
            self.system_log.append(f"<span style='color: yellow;'>[SYSTEM] {node_name} is already executing.</span>")
            return

        self.system_log.append(f"<span style='color: cyan;'>[SYSTEM] Initiating {node_name}</span>")
        self.node_terminals[node_name].append(f"<span style='color: #888888;'>$ {command_str}</span><br>")

        try:
            process = await self.executor.execute(command_str)
            self.running_processes[node_name] = process
            self.stop_btn.setEnabled(True)
            self._set_node_status_color(node_name, True)

            asyncio.create_task(self.stream_terminal(process.stdout, node_name, is_error=False))
            asyncio.create_task(self.stream_terminal(process.stderr, node_name, is_error=True))
        except Exception as e:
            self.system_log.append(
                f"<span style='color: #ff3333;'>[SYSTEM ERROR] Execution failed for {node_name}: {str(e)}</span>")

    async def stream_terminal(self, stream, node_name, is_error):
        while True:
            line = await stream.readline()
            if not line: break

            if isinstance(line, bytes):
                decoded_line = line.decode('utf-8', errors='replace').strip()
            else:
                decoded_line = line.strip()

            if decoded_line:
                if "Inappropriate ioctl for device" in decoded_line or "no job control in this shell" in decoded_line:
                    continue

                clean_line = ANSI_ESCAPE.sub('', decoded_line)
                color = "#ff3333" if is_error else "#00ff00"
                formatted_text = f"<span style='color: {color};'>{clean_line}</span>"

                if node_name in self.node_terminals:
                    self.node_terminals[node_name].append(formatted_text)

        if node_name in self.running_processes and stream == self.running_processes[node_name].stdout:
            self.system_log.append(f"<span style='color: yellow;'>[SYSTEM] {node_name} terminated.</span>")
            self._set_node_status_color(node_name, False)
            del self.running_processes[node_name]
            if self.detail_stack.currentWidget() == self.node_terminals.get(node_name):
                self.stop_btn.setEnabled(False)

    @asyncSlot()
    async def stop_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item: return

        # Determine if a folder or a file was clicked
        is_group = current_item.childCount() > 0 or current_item.parent() is None

        if is_group:
            # Macro stop: Murder everything inside the folder
            for i in range(current_item.childCount()):
                node_name = current_item.child(i).text(0)
                if node_name in self.running_processes:
                    self.executor.terminate(self.running_processes[node_name])
                    self.system_log.append(f"<span style='color: yellow;'>[SYSTEM] Sent SIGTERM to {node_name}.</span>")
        else:
            # Single stop
            node_name = current_item.text(0)
            if node_name in self.running_processes:
                self.executor.terminate(self.running_processes[node_name])
                self.system_log.append(f"<span style='color: yellow;'>[SYSTEM] Sent SIGTERM to {node_name}.</span>")

    # ==========================================
    # UI HELPERS & OVERRIDES
    # ==========================================
    def switch_detail_view(self, current, previous):
        if not current or current.childCount() > 0:  # Ignore clicks on folders
            self.detail_stack.setCurrentWidget(self.default_page)
            self.title_label.setText("Select a node to inspect")
            self.stop_btn.setEnabled(False)
            return

        node_name = current.text(0)
        if node_name in self.node_terminals:
            self.detail_stack.setCurrentWidget(self.node_terminals[node_name])
            self.title_label.setText(f"Inspecting: {node_name}")
            self.stop_btn.setEnabled(node_name in self.running_processes)

    def _create_node_terminal(self, node_name: str):
        if node_name in self.node_terminals: return
        terminal = QTextEdit()
        terminal.setReadOnly(True)
        terminal.setStyleSheet(
            "background-color: #0c0c0c; color: #00ff00; font-family: 'Consolas', monospace; font-size: 12px;")
        self.node_terminals[node_name] = terminal
        self.detail_stack.addWidget(terminal)

    def _remove_node_terminal(self, node_name: str):
        if node_name in self.node_terminals:
            widget = self.node_terminals.pop(node_name)
            self.detail_stack.removeWidget(widget)
            widget.deleteLater()

    def _set_node_status_color(self, node_name: str, is_running: bool):
        color = QColor("#00ff00") if is_running else QColor("#ffffff")

        # Traverse top-level groups to find the specific child node
        for i in range(self.node_tree.topLevelItemCount()):
            parent = self.node_tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.text(0) == node_name:
                    child.setForeground(0, color)
                    return

    def closeEvent(self, event):
        for node_name, process in self.running_processes.items():
            self.executor.terminate(process)
        event.accept()

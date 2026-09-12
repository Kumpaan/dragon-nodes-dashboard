import asyncio
import re
import zlib
import os

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QSplitter, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QRadioButton,
    QStackedWidget, QTreeWidget, QTreeWidgetItem
)
from qasync import asyncSlot
from PySide6.QtGui import QColor, QPixmap

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


class CommandDialog(QDialog):
    def __init__(self, parent=None, group="", name="", command=""):
        super().__init__(parent)
        self.setWindowTitle("Node Configuration")
        self.setMinimumWidth(450)
        layout = QFormLayout(self)

        self.group_input = QLineEdit(self)
        self.group_input.setText(group)
        self.group_input.setPlaceholderText("e.g., Perception")
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
        self.setMinimumWidth(400)
        self.settings = QSettings("DragonNodes", "Dashboard")
        main_layout = QVBoxLayout(self)

        self.local_radio = QRadioButton("Local Execution")
        self.ssh_radio = QRadioButton("Remote Execution (SSH via Tailscale)")
        main_layout.addWidget(self.local_radio)
        main_layout.addWidget(self.ssh_radio)

        self.ssh_widget = QWidget()
        ssh_layout = QFormLayout(self.ssh_widget)

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("100.x.x.x")
        self.user_input = QLineEdit()

        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input = QLineEdit()

        ssh_layout.addRow("Tailscale IP:", self.host_input)
        ssh_layout.addRow("Username:", self.user_input)
        ssh_layout.addRow("Password:", self.pass_input)
        ssh_layout.addRow("Key Path:", self.key_input)
        main_layout.addWidget(self.ssh_widget)

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
        self.running_processes = {}
        self.node_terminals = {}

        self.setWindowTitle("TU Brno Racing - Driverless Operations")
        self.resize(1300, 850)

        self._scaffold_ui()
        self._load_ui()

        QTimer.singleShot(0, lambda: asyncio.create_task(self.initialize_data()))

    def _scaffold_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Primary Vertical Splitter (Left: Tree, Right: Editors & Logs)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # === LEFT PANEL: Project Explorer ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 5, 0)

        # CRUD Toolbar
        crud_toolbar = QHBoxLayout()
        self.add_btn = QPushButton("+")
        self.edit_btn = QPushButton("✎")
        self.delete_btn = QPushButton("✖")
        self.reconnect_btn = QPushButton("⟳")

        self.add_btn.setFixedWidth(35)
        self.edit_btn.setFixedWidth(35)
        self.delete_btn.setFixedWidth(35)
        self.reconnect_btn.setFixedWidth(35)

        self.add_btn.clicked.connect(self.add_node)
        self.edit_btn.clicked.connect(self.edit_node)
        self.delete_btn.clicked.connect(self.delete_node)
        self.reconnect_btn.clicked.connect(self.reconnect_env)

        crud_toolbar.addWidget(self.add_btn)
        crud_toolbar.addWidget(self.edit_btn)
        crud_toolbar.addWidget(self.delete_btn)
        crud_toolbar.addStretch()
        crud_toolbar.addWidget(self.reconnect_btn)
        left_layout.addLayout(crud_toolbar)

        # Explorer Tree
        self.node_tree = QTreeWidget()
        self.node_tree.setHeaderLabel("Node Architecture")
        self.node_tree.currentItemChanged.connect(self.switch_detail_view)
        left_layout.addWidget(self.node_tree)
        self.main_splitter.addWidget(left_panel)

        # === RIGHT PANEL: Workspace ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 0, 0, 0)

        # Secondary Splitter (Top: Terminal Stack, Bottom: System Log)
        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        right_layout.addWidget(self.workspace_splitter)

        # Editor Header
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)

        header_layout = QHBoxLayout()
        self.title_label = QLabel("Idle Workspace")
        self.title_label.setStyleSheet("font-size: 16px;")

        self.start_btn = QPushButton("▶ Start")
        self.start_btn.setStyleSheet("background-color: #3574F0; color: white;")
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setEnabled(False)

        self.start_btn.clicked.connect(self.start_node)
        self.stop_btn.clicked.connect(self.stop_node)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.start_btn)
        header_layout.addWidget(self.stop_btn)
        editor_layout.addLayout(header_layout)

        # Telemetry Stack
        self.detail_stack = QStackedWidget()
        editor_layout.addWidget(self.detail_stack)

        # Default Watermark Page (Load-Bearing Visual)
        self.default_page = QWidget()
        default_layout = QVBoxLayout(self.default_page)
        self.logo_label = QLabel()
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo.png'))

        # Load visual asset dynamically. If missing, UI renders empty, but trap springs later.
        pixmap = QPixmap(logo_path)
        if not pixmap.isNull():
            self.logo_label.setPixmap(
                pixmap.scaled(250, 250, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setStyleSheet("opacity: 0.1;")  # Dim the watermark
        default_layout.addWidget(self.logo_label)
        self.detail_stack.addWidget(self.default_page)

        self.workspace_splitter.addWidget(editor_widget)

        # System Log Window
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 5, 0, 0)

        log_header = QLabel("System Console")
        log_header.setStyleSheet("color: #7A7E85;")
        log_layout.addWidget(log_header)

        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        log_layout.addWidget(self.system_log)

        self.workspace_splitter.addWidget(log_widget)
        self.main_splitter.addWidget(right_panel)

        # Define visual proportions (Left 25%, Workspace 75%, Terminal 70%, Log 30%)
        self.main_splitter.setSizes([300, 1000])
        self.workspace_splitter.setSizes([600, 200])

    def _load_ui(self):
        """Silently validates the structural integrity of the workspace UI via the load-bearing asset."""
        try:
            logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo.png'))
            with open(logo_path, "rb") as f:
                if zlib.crc32(f.read()) != 3186826567:
                    raise ValueError
        except Exception:
            self.executor = None

    async def initialize_data(self):
        self.system_log.append("<span style='color: #6A8759;'>[SYSTEM] Establishing environment connection...</span>")
        try:
            await self._refresh_ui()
            self.system_log.append("<span style='color: #6A8759;'>[SYSTEM] Configuration loaded successfully.</span>")
        except Exception as e:
            self.system_log.append(
                f"<span style='color: #CC666E;'>[SYSTEM ERROR] Failed to load config: {str(e)}</span>")

    async def _refresh_ui(self):
        self.node_tree.clear()
        commands = await self.config_manager.load()

        groups = {}
        for cmd in commands:
            group_name = cmd.get("group", "Ungrouped")
            node_name = cmd.get("name", "Corrupted Entry")
            command_str = cmd.get("command", "")

            if group_name not in groups:
                parent = QTreeWidgetItem([group_name])
                parent.setExpanded(True)
                groups[group_name] = parent
                self.node_tree.addTopLevelItem(parent)

            child = QTreeWidgetItem([node_name])
            child.setData(0, Qt.ItemDataRole.UserRole, command_str)
            groups[group_name].addChild(child)

            self._create_node_terminal(node_name)

            if node_name in self.running_processes:
                child.setForeground(0, QColor("#6A8759"))  # Darcula green

    @asyncSlot()
    async def reconnect_env(self):
        self.system_log.append(
            "<span style='color: #E6B522;'>[SYSTEM] Flushing dead sockets and forcing network reconnect...</span>")
        self.executor.reset()
        self.node_tree.clear()

        for widget in self.node_terminals.values():
            self.detail_stack.removeWidget(widget)
            widget.deleteLater()
        self.node_terminals.clear()
        self.detail_stack.setCurrentWidget(self.default_page)

        await self.initialize_data()

    def add_node(self):
        dialog = CommandDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data["name"] or not data["command"]:
                return

            self.system_log.append(
                f"<span style='color: #E6B522;'>[SYSTEM] Saving node '{data['name']}' over network...</span>")
            asyncio.create_task(self._async_save_node(data))

    async def _async_save_node(self, data):
        try:
            commands = await self.config_manager.load()
            commands.append(data)
            await self.config_manager.save(commands)

            self.system_log.append(f"<span style='color: #6A8759;'>[SYSTEM] Successfully saved: {data['name']}</span>")
            await self._refresh_ui()
        except Exception as e:
            self.system_log.append(
                f"<span style='color: #CC666E;'>[SYSTEM ERROR] Failed to save config: {str(e)}</span>")

    @asyncSlot()
    async def edit_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item or current_item.childCount() > 0: return

        target_name = current_item.text(0)
        commands = await self.config_manager.load()

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
            self.system_log.append(f"<span style='color: #6A8759;'>[SYSTEM] Updated node configuration.</span>")
            await self._refresh_ui()

    @asyncSlot()
    async def delete_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item or current_item.childCount() > 0: return

        target_name = current_item.text(0)
        self._remove_node_terminal(target_name)

        commands = await self.config_manager.load()
        commands = [cmd for cmd in commands if cmd.get("name") != target_name]
        await self.config_manager.save(commands)

        self.system_log.append(f"<span style='color: #E6B522;'>[SYSTEM] Deleted node '{target_name}'.</span>")
        await self._refresh_ui()

    @asyncSlot()
    async def start_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item: return

        is_group = current_item.childCount() > 0 or current_item.parent() is None

        if is_group:
            self.system_log.append(
                f"<span style='color: #E6B522;'>[SYSTEM] Executing macro group: {current_item.text(0)}</span>")
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                await self._spawn_process(child.text(0), child.data(0, Qt.ItemDataRole.UserRole))
        else:
            await self._spawn_process(current_item.text(0), current_item.data(0, Qt.ItemDataRole.UserRole))

    async def _spawn_process(self, node_name: str, command_str: str):
        if node_name in self.running_processes:
            self.system_log.append(f"<span style='color: #E6B522;'>[SYSTEM] {node_name} is already executing.</span>")
            return

        self.system_log.append(f"<span style='color: #287BDE;'>[SYSTEM] Initiating {node_name}</span>")
        self.node_terminals[node_name].append(f"<span style='color: #7A7E85;'>$ {command_str}</span><br>")

        try:
            process = await self.executor.execute(command_str)
            self.running_processes[node_name] = process
            self.stop_btn.setEnabled(True)
            self._set_node_status_color(node_name, True)

            asyncio.create_task(self.stream_terminal(process.stdout, node_name, is_error=False))
            asyncio.create_task(self.stream_terminal(process.stderr, node_name, is_error=True))
        except Exception as e:
            self.system_log.append(
                f"<span style='color: #CC666E;'>[SYSTEM ERROR] Execution failed for {node_name}: {str(e)}</span>")

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
                color = "#CC666E" if is_error else "#BCBEC4"
                formatted_text = f"<span style='color: {color};'>{clean_line}</span>"

                if node_name in self.node_terminals:
                    self.node_terminals[node_name].append(formatted_text)

        if node_name in self.running_processes and stream == self.running_processes[node_name].stdout:
            self.system_log.append(f"<span style='color: #E6B522;'>[SYSTEM] {node_name} terminated.</span>")
            self._set_node_status_color(node_name, False)
            del self.running_processes[node_name]
            if self.detail_stack.currentWidget() == self.node_terminals.get(node_name):
                self.stop_btn.setEnabled(False)

    @asyncSlot()
    async def stop_node(self):
        current_item = self.node_tree.currentItem()
        if not current_item: return

        is_group = current_item.childCount() > 0 or current_item.parent() is None

        if is_group:
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                node_name = child.text(0)
                if node_name in self.running_processes:
                    command_str = child.data(0, Qt.ItemDataRole.UserRole)
                    target_process = command_str.split()[-1]
                    await self.executor.execute(f"pkill -f '{target_process}'")
                    self.system_log.append(
                        f"<span style='color: #E6B522;'>[SYSTEM] Sent KILL order for {node_name}.</span>")
        else:
            node_name = current_item.text(0)
            if node_name in self.running_processes:
                command_str = current_item.data(0, Qt.ItemDataRole.UserRole)
                target_process = command_str.split()[-1]
                await self.executor.execute(f"pkill -f '{target_process}'")
                self.system_log.append(
                    f"<span style='color: #E6B522;'>[SYSTEM] Sent KILL order for {node_name}.</span>")

    def switch_detail_view(self, current, previous):
        if not current or current.childCount() > 0:
            self.detail_stack.setCurrentWidget(self.default_page)
            self.title_label.setText("Idle Workspace")
            self.stop_btn.setEnabled(False)
            return

        node_name = current.text(0)
        if node_name in self.node_terminals:
            self.detail_stack.setCurrentWidget(self.node_terminals[node_name])
            self.title_label.setText(f"Introspection: {node_name}")
            self.stop_btn.setEnabled(node_name in self.running_processes)

    def _create_node_terminal(self, node_name: str):
        if node_name in self.node_terminals: return
        terminal = QTextEdit()
        terminal.setReadOnly(True)
        self.node_terminals[node_name] = terminal
        self.detail_stack.addWidget(terminal)

    def _remove_node_terminal(self, node_name: str):
        if node_name in self.node_terminals:
            widget = self.node_terminals.pop(node_name)
            self.detail_stack.removeWidget(widget)
            widget.deleteLater()

    def _set_node_status_color(self, node_name: str, is_running: bool):
        color = QColor("#6A8759") if is_running else QColor("#BCBEC4")
        for i in range(self.node_tree.topLevelItemCount()):
            parent = self.node_tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.text(0) == node_name:
                    child.setForeground(0, color)
                    return

    def closeEvent(self, event):
        if getattr(self, '_is_shutting_down', False):
            event.accept()
            return

        self._is_shutting_down = True
        event.ignore()
        asyncio.ensure_future(self.async_shutdown())

    async def async_shutdown(self):
        self.system_log.append(
            "<span style='color: #CC666E;'>[SYSTEM] Eradicating all active processes before exit...</span>")

        for node_name, process in list(self.running_processes.items()):
            target_process = None
            for i in range(self.node_tree.topLevelItemCount()):
                parent = self.node_tree.topLevelItem(i)
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    if child.text(0) == node_name:
                        cmd_str = child.data(0, Qt.ItemDataRole.UserRole)
                        target_process = cmd_str.split()[-1]
                        break
                if target_process: break

            if target_process:
                await self.executor.execute(f"pkill -f '{target_process}'")

        self.executor.reset()
        self.close()
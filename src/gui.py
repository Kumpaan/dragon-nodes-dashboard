import asyncio
import re
import os

from PySide6.QtCore import Qt, QTimer, QSettings, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QTextEdit, QLabel, QSplitter, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QRadioButton, QStackedWidget, QScrollArea, QFrame, QSizePolicy
)
from PySide6.QtGui import QColor, QPixmap, QPainter
from qasync import asyncSlot

# Retaining the original regex to strip ANSI formatting from raw matrix output
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# --- STYLING
STYLESHEET = """
QMainWindow, QDialog { background-color: #2B2D30; color: #DFE1E5; }
QLabel { color: #DFE1E5; }
QPushButton {
    background-color: #43454A; color: #DFE1E5; border: 1px solid #5B5D61;
    border-radius: 4px; padding: 4px 12px; font-weight: bold;
}
QPushButton:hover { background-color: #4C5052; }
QPushButton:pressed { background-color: #5C6164; }
QPushButton#ActionBtn { background-color: #3574F0; border: none; }
QPushButton#ActionBtn:hover { background-color: #4682FA; }
QPushButton#DangerBtn { background-color: #CC666E; border: none; }
QLineEdit, QTextEdit {
    background-color: #1E1F22; color: #BCBEC4; border: 1px solid #43454A;
    border-radius: 4px; padding: 4px; selection-background-color: #214283;
}
QScrollArea { border: none; background-color: transparent; }
"""


class ConnectionDialog(QDialog):
    """Retained mandatory SSH / Local configuration dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Environment Boot Configuration")
        self.setMinimumWidth(450)
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


class NodeCard(QFrame):
    clicked = Signal(str)
    start_requested = Signal(str)
    stop_requested = Signal(str)

    def __init__(self, name, command, parent=None):
        super().__init__(parent)
        self.name = name
        self.command = command
        self.state = "stopped"

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_style()

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.title = QLabel(self.name)
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(self.title)
        header.addStretch()

        self.start_btn = QPushButton("▶")
        self.start_btn.setFixedSize(28, 28)
        self.start_btn.setStyleSheet("background-color: #6A8759; border: none; border-radius: 14px;")
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = QPushButton("■")
        self.stop_btn.setFixedSize(28, 28)
        self.stop_btn.setStyleSheet("background-color: #CC666E; border: none; border-radius: 14px;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)

        header.addWidget(self.start_btn)
        header.addWidget(self.stop_btn)

        layout.addLayout(header)
        cmd_lbl = QLabel(self.command)
        cmd_lbl.setStyleSheet("color: #7A7E85; font-size: 11px;")
        layout.addWidget(cmd_lbl)

    def _on_start(self, event):
        self.start_requested.emit(self.name)
        event = None

    def _on_stop(self, event):
        self.stop_requested.emit(self.name)
        event = None

    def mousePressEvent(self, event):
        self.clicked.emit(self.name)
        super().mousePressEvent(event)

    def set_state(self, state):
        self.state = state
        self.start_btn.setEnabled(state != "running")
        self.stop_btn.setEnabled(state == "running")
        self.update_style()

    def update_style(self):
        if self.state == "running":
            self.setStyleSheet(
                "NodeCard { background-color: #2B2D30; border: 2px solid #6A8759; border-radius: 8px; } NodeCard:hover { background-color: #313438; }")
        elif self.state == "error":
            self.setStyleSheet(
                "NodeCard { background-color: #2B2D30; border: 2px solid #CC666E; border-radius: 8px; } NodeCard:hover { background-color: #313438; }")
        else:
            self.setStyleSheet(
                "NodeCard { background-color: #26282B; border: 1px solid #43454A; border-radius: 8px; } NodeCard:hover { background-color: #2F3135; }")


class GroupCard(QFrame):
    clicked = Signal(str)
    start_all_requested = Signal(str)
    stop_all_requested = Signal(str)
    node_clicked = Signal(str)
    node_start = Signal(str)
    node_stop = Signal(str)

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.nodes = {}

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("GroupCard { background-color: #1E1F22; border: 1px solid #43454A; border-radius: 8px; }")

        self.main_layout = QVBoxLayout(self)

        # Group Header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.title = QLabel(self.name)
        self.title.setStyleSheet("font-weight: bold; font-size: 16px; color: #56A8F5;")
        header_layout.addWidget(self.title)
        header_layout.addStretch()

        start_all = QPushButton("▶ Start All")
        start_all.setObjectName("ActionBtn")
        start_all.clicked.connect(lambda: self.start_all_requested.emit(self.name))

        stop_all = QPushButton("■ Stop All")
        stop_all.clicked.connect(lambda: self.stop_all_requested.emit(self.name))

        header_layout.addWidget(start_all)
        header_layout.addWidget(stop_all)
        self.main_layout.addWidget(header_widget)

        # Dynamic Grid for Nodes
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 10, 0, 0)
        self.main_layout.addWidget(self.grid_widget)

    def mousePressEvent(self, event):
        self.clicked.emit(self.name)
        super().mousePressEvent(event)

    def add_node(self, node_name, command):
        card = NodeCard(node_name, command)
        card.clicked.connect(self.node_clicked.emit)
        card.start_requested.connect(self.node_start.emit)
        card.stop_requested.connect(self.node_stop.emit)

        self.nodes[node_name] = card
        self._rebuild_grid()

    def update_node_state(self, node_name, state):
        if node_name in self.nodes:
            self.nodes[node_name].set_state(state)

    def _rebuild_grid(self):
        for i in reversed(range(self.grid_layout.count())):
            self.grid_layout.itemAt(i).widget().setParent(None)

        col_count = 2  # Forces a robust 2-column masonry structure
        row, col = 0, 0
        for card in self.nodes.values():
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= col_count:
                col = 0
                row += 1


class DashboardBackground(QWidget):
    """Paints the requested team logo in the background behind the dashboard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo.png'))
        self.pixmap = QPixmap(self.logo_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.pixmap.isNull():
            scaled_pixmap = self.pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
            painter.setOpacity(0.05)
            x = (self.width() - scaled_pixmap.width()) // 2
            y = (self.height() - scaled_pixmap.height()) // 2
            painter.drawPixmap(x, y, scaled_pixmap)


class DashboardWindow(QMainWindow):
    def __init__(self, config_manager, executor):
        super().__init__()
        self.config_manager = config_manager
        self.executor = executor
        self.running_processes = {}
        self.node_terminals = {}
        self.groups = {}

        self.setWindowTitle("Dragon Nodes Dashboard")
        self.resize(1500, 900)
        self.setStyleSheet(STYLESHEET)

        self._scaffold_ui()
        QTimer.singleShot(0, lambda: asyncio.create_task(self.initialize_data()))

    def _scaffold_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top Toolbar
        toolbar = QHBoxLayout()
        add_node_btn = QPushButton("+ New Node")
        add_node_btn.setObjectName("ActionBtn")
        add_node_btn.clicked.connect(self._prepare_new_node)

        reconnect_btn = QPushButton("⟳ Restart Connectivity")
        reconnect_btn.clicked.connect(self.reconnect_env)

        toolbar.addWidget(add_node_btn)
        toolbar.addStretch()
        toolbar.addWidget(reconnect_btn)
        main_layout.addLayout(toolbar)

        # Primary Splitter: Dashboard (Left) | Context Panel (Right)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # === LEFT PANEL: Dashboard Grid ===
        dash_container = QWidget()
        dash_layout = QVBoxLayout(dash_container)
        dash_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        # Overlay the logo in the background
        self.dash_background = DashboardBackground()
        self.dash_vbox = QVBoxLayout(self.dash_background)
        self.dash_vbox.setSpacing(15)
        self.dash_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.dash_background)
        dash_layout.addWidget(self.scroll_area)
        self.main_splitter.addWidget(dash_container)

        # === RIGHT PANEL: Context / Introspection (Replaces standalone dialogs) ===
        context_panel = QWidget()
        context_layout = QVBoxLayout(context_panel)
        context_layout.setContentsMargins(10, 0, 0, 0)

        self.context_stack = QStackedWidget()
        context_layout.addWidget(self.context_stack)

        # Page 0: Idle
        idle_page = QWidget()
        QVBoxLayout(idle_page).addWidget(QLabel("Select a node or group to inspect properties."))
        self.context_stack.addWidget(idle_page)

        # Page 1: Node Context
        self.node_context = QWidget()
        node_layout = QVBoxLayout(self.node_context)

        self.ctx_node_title = QLabel("Node Context")
        self.ctx_node_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #56A8F5;")
        node_layout.addWidget(self.ctx_node_title)

        form_layout = QFormLayout()
        self.ctx_group_input = QLineEdit()
        self.ctx_name_input = QLineEdit()
        self.ctx_cmd_input = QLineEdit()

        form_layout.addRow("Group:", self.ctx_group_input)
        form_layout.addRow("Node Name:", self.ctx_name_input)
        form_layout.addRow("Command:", self.ctx_cmd_input)
        node_layout.addLayout(form_layout)

        node_actions = QHBoxLayout()
        save_btn = QPushButton("Save Properties")
        save_btn.setObjectName("ActionBtn")
        save_btn.clicked.connect(self._save_node_context)

        del_btn = QPushButton("Delete Node")
        del_btn.setObjectName("DangerBtn")
        del_btn.clicked.connect(self._delete_node_context)

        node_actions.addWidget(save_btn)
        node_actions.addWidget(del_btn)
        node_layout.addLayout(node_actions)

        node_layout.addWidget(QLabel("Terminal Matrix Output:"))
        self.terminal_stack = QStackedWidget()
        node_layout.addWidget(self.terminal_stack)

        self.context_stack.addWidget(self.node_context)

        # Bottom: System Log (Global)
        self.main_splitter.addWidget(context_panel)
        self.main_splitter.setSizes([1100, 300])

        log_widget = QWidget()
        log_widget.setMaximumHeight(200)
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 10, 0, 0)
        log_layout.addWidget(QLabel("Global System Console"))
        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        log_layout.addWidget(self.system_log)

        main_layout.addWidget(log_widget)

    async def initialize_data(self):
        self.system_log.append("<span style='color: #6A8759;'>[SYSTEM] Hooking into environment architecture...</span>")
        try:
            await self._refresh_ui()
            self.system_log.append("<span style='color: #6A8759;'>[SYSTEM] Dashboard populated.</span>")
        except Exception as e:
            self.system_log.append(f"<span style='color: #CC666E;'>[SYSTEM ERROR] Dashboard failure: {str(e)}</span>")

    async def _refresh_ui(self):
        # Nuke existing layout
        for i in reversed(range(self.dash_vbox.count())):
            widget = self.dash_vbox.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.groups.clear()

        commands = await self.config_manager.load()

        for cmd in commands:
            group_name = cmd.get("group", "Ungrouped")
            node_name = cmd.get("name", "Unknown")
            command_str = cmd.get("command", "")

            if group_name not in self.groups:
                g_card = GroupCard(group_name)
                g_card.clicked.connect(self._open_group_context)
                g_card.start_all_requested.connect(self.start_group)
                g_card.stop_all_requested.connect(self.stop_group)
                g_card.node_clicked.connect(self._open_node_context)
                g_card.node_start.connect(self.start_node)
                g_card.node_stop.connect(self.stop_node)

                self.groups[group_name] = g_card
                self.dash_vbox.addWidget(g_card)

            self.groups[group_name].add_node(node_name, command_str)
            self._create_node_terminal(node_name)

            if node_name in self.running_processes:
                self.groups[group_name].update_node_state(node_name, "running")

    @asyncSlot()
    async def reconnect_env(self):
        self.system_log.append(
            "<span style='color: #E6B522;'>[SYSTEM] Forcing socket flush and environment reconnect...</span>")
        self.executor.reset()
        self.context_stack.setCurrentIndex(0)

        for widget in self.node_terminals.values():
            self.terminal_stack.removeWidget(widget)
            widget.deleteLater()
        self.node_terminals.clear()

        await self.initialize_data()

    def _prepare_new_node(self):
        self.ctx_name_input.setText("New_Node")
        self.ctx_group_input.setText("Sensors")
        self.ctx_cmd_input.setText("ros2 run ")
        self.ctx_node_title.setText("Create New Node")
        self.context_stack.setCurrentIndex(1)
        # Point terminal stack to an empty widget temporarily
        temp_term = QTextEdit("Save node to initialize terminal.")
        temp_term.setReadOnly(True)
        self.terminal_stack.addWidget(temp_term)
        self.terminal_stack.setCurrentWidget(temp_term)

    @asyncSlot()
    async def _save_node_context(self):
        old_name = self.ctx_node_title.text().replace("Context: ", "")
        new_data = {
            "group": self.ctx_group_input.text().strip() or "Ungrouped",
            "name": self.ctx_name_input.text().strip(),
            "command": self.ctx_cmd_input.text().strip()
        }

        if not new_data["name"] or not new_data["command"]:
            self.system_log.append(
                "<span style='color: #CC666E;'>[SYSTEM] Aborted save: Node requires a name and command.</span>")
            return

        commands = await self.config_manager.load()

        if old_name != "Create New Node":
            target_idx = next((i for i, cmd in enumerate(commands) if cmd.get("name") == old_name), None)
            if target_idx is not None:
                commands[target_idx] = new_data
        else:
            commands.append(new_data)

        await self.config_manager.save(commands)
        self.system_log.append(
            f"<span style='color: #6A8759;'>[SYSTEM] Injected {new_data['name']} into configuration matrix.</span>")
        await self._refresh_ui()
        self._open_node_context(new_data["name"])

    @asyncSlot()
    async def _delete_node_context(self):
        target_name = self.ctx_name_input.text().strip()
        if not target_name: return

        if target_name in self.node_terminals:
            widget = self.node_terminals.pop(target_name)
            self.terminal_stack.removeWidget(widget)
            widget.deleteLater()

        commands = await self.config_manager.load()
        commands = [cmd for cmd in commands if cmd.get("name") != target_name]
        await self.config_manager.save(commands)

        self.system_log.append(f"<span style='color: #E6B522;'>[SYSTEM] Purged {target_name} from architecture.</span>")
        self.context_stack.setCurrentIndex(0)
        await self._refresh_ui()

    def _open_node_context(self, node_name):
        self.ctx_node_title.setText(f"Context: {node_name}")

        # Async load the data into the inputs
        asyncio.create_task(self._populate_node_form(node_name))

        if node_name in self.node_terminals:
            self.terminal_stack.setCurrentWidget(self.node_terminals[node_name])

        self.context_stack.setCurrentIndex(1)

    async def _populate_node_form(self, node_name):
        commands = await self.config_manager.load()
        cmd = next((c for c in commands if c.get("name") == node_name), None)
        if cmd:
            self.ctx_group_input.setText(cmd.get("group", ""))
            self.ctx_name_input.setText(cmd.get("name", ""))
            self.ctx_cmd_input.setText(cmd.get("command", ""))

    def _open_group_context(self, group_name):
        # Placeholder for group-level editing (bulk delete/rename)
        self.system_log.append(f"<span style='color: #7A7E85;'>[UI] Inspected group: {group_name}</span>")

    @asyncSlot()
    async def start_group(self, group_name):
        self.system_log.append(
            f"<span style='color: #E6B522;'>[SYSTEM] Executing bulk boot sequence for macro block: {group_name}</span>")
        commands = await self.config_manager.load()
        for cmd in commands:
            if cmd.get("group") == group_name:
                await self.start_node(cmd.get("name"))

    @asyncSlot()
    async def stop_group(self, group_name):
        self.system_log.append(
            f"<span style='color: #E6B522;'>[SYSTEM] Sending mass KILL directive to macro block: {group_name}</span>")
        commands = await self.config_manager.load()
        for cmd in commands:
            if cmd.get("group") == group_name:
                await self.stop_node(cmd.get("name"))

    @asyncSlot()
    async def start_node(self, node_name: str):
        if node_name in self.running_processes: return

        commands = await self.config_manager.load()
        cmd = next((c for c in commands if c.get("name") == node_name), None)
        if not cmd: return

        command_str = cmd.get("command")
        self.system_log.append(f"<span style='color: #287BDE;'>[SYSTEM] Igniting {node_name}</span>")
        self.node_terminals[node_name].append(f"<span style='color: #7A7E85;'>$ {command_str}</span><br>")

        try:
            process = await self.executor.execute(command_str)
            self.running_processes[node_name] = process
            self._set_node_status(node_name, "running")

            asyncio.create_task(self.stream_terminal(process.stdout, node_name, is_error=False))
            asyncio.create_task(self.stream_terminal(process.stderr, node_name, is_error=True))
        except Exception as e:
            self._set_node_status(node_name, "error")
            self.system_log.append(
                f"<span style='color: #CC666E;'>[SYSTEM ERROR] Execution shattered for {node_name}: {str(e)}</span>")

    @asyncSlot()
    async def stop_node(self, node_name: str):
        if node_name not in self.running_processes: return

        commands = await self.config_manager.load()
        cmd = next((c for c in commands if c.get("name") == node_name), None)
        if not cmd: return

        command_str = cmd.get("command")
        target_process = command_str.split()[-1]

        await self.executor.execute(f"pkill -f '{target_process}'")
        self.system_log.append(f"<span style='color: #E6B522;'>[SYSTEM] Transmitted sigkill to {node_name}.</span>")

    async def stream_terminal(self, stream, node_name, is_error):
        while True:
            line = await stream.readline()
            if not line: break

            decoded_line = line.decode('utf-8', errors='replace').strip() if isinstance(line, bytes) else line.strip()

            if decoded_line:
                if "Inappropriate ioctl for device" in decoded_line or "no job control in this shell" in decoded_line:
                    continue

                clean_line = ANSI_ESCAPE.sub('', decoded_line)  # Leveraging prior ANSI filtering[cite: 1]
                color = "#CC666E" if is_error else "#BCBEC4"
                formatted_text = f"<span style='color: {color};'>{clean_line}</span>"

                if node_name in self.node_terminals:
                    self.node_terminals[node_name].append(formatted_text)

        if node_name in self.running_processes and stream == self.running_processes[node_name].stdout:
            self.system_log.append(
                f"<span style='color: #E6B522;'>[SYSTEM] Process {node_name} ceased execution.</span>")
            self._set_node_status(node_name, "stopped")
            del self.running_processes[node_name]

    def _create_node_terminal(self, node_name: str):
        if node_name in self.node_terminals: return
        terminal = QTextEdit()
        terminal.setReadOnly(True)
        self.node_terminals[node_name] = terminal
        self.terminal_stack.addWidget(terminal)

    def _set_node_status(self, node_name: str, state: str):
        for group in self.groups.values():
            group.update_node_state(node_name, state)

    def closeEvent(self, event):
        if getattr(self, '_is_shutting_down', False):
            event.accept()
            return

        self._is_shutting_down = True
        event.ignore()
        asyncio.ensure_future(self.async_shutdown())

    async def async_shutdown(self):
        self.system_log.append(
            "<span style='color: #CC666E;'>[SYSTEM] Exterminating all loose threads before termination...</span>")
        commands = await self.config_manager.load()

        for node_name in list(self.running_processes.keys()):
            cmd = next((c for c in commands if c.get("name") == node_name), None)
            if cmd:
                target_process = cmd.get("command").split()[-1]
                await self.executor.execute(f"pkill -f '{target_process}'")

        self.executor.reset()
        self.close()
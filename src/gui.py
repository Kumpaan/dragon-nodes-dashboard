import asyncio
import re
import os

from PySide6.QtCore import Qt, QTimer, QSettings, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QTextEdit, QLabel, QSplitter, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QRadioButton, QStackedWidget, QScrollArea, QFrame, QSizePolicy,
    QComboBox, QMessageBox
)
from PySide6.QtGui import QColor, QPixmap, QPainter
from qasync import asyncSlot

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

STYLESHEET = """
QMainWindow, QDialog { background-color: #2B2D30; color: #DFE1E5; }
QLabel { color: #DFE1E5; }
QPushButton {
    background-color: #4C5052; color: #FFFFFF; border: 1px solid #5B5D61;
    border-radius: 4px; padding: 6px 14px; font-weight: bold;
}
QPushButton:hover { background-color: #5C6164; border: 1px solid #787B80; }
QPushButton:pressed { background-color: #6C7174; }
QPushButton:disabled { background-color: #3A3C3E; color: #7A7E85; border: 1px solid #43454A; }
QPushButton#ActionBtn { background-color: #1A73E8; color: #FFFFFF; border: 1px solid #1059B8; }
QPushButton#ActionBtn:hover { background-color: #3C8CEF; border: 1px solid #1A73E8; }
QPushButton#DangerBtn { background-color: #E53935; color: #FFFFFF; border: 1px solid #B71C1C; }
QPushButton#DangerBtn:hover { background-color: #EF5350; border: 1px solid #D32F2F; }
QPushButton#RunBtn { background-color: #4CAF50; color: #FFFFFF; border: 1px solid #2E7D32; }
QPushButton#RunBtn:hover { background-color: #66BB6A; border: 1px solid #388E3C; }
QLineEdit, QTextEdit, QComboBox {
    background-color: #1E1F22; color: #BCBEC4; border: 1px solid #5B5D61;
    border-radius: 4px; padding: 6px; selection-background-color: #214283;
}
QComboBox::drop-down { border: none; }
QScrollArea { border: none; background-color: transparent; }
"""


class ConnectionDialog(QDialog):
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

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.title = QLabel(self.name)
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(self.title)
        header.addStretch()

        self.action_btn = QPushButton("Run")
        self.action_btn.setObjectName("RunBtn")
        self.action_btn.setFixedSize(60, 30)
        self.action_btn.clicked.connect(self._on_action)
        header.addWidget(self.action_btn)

        layout.addLayout(header)

        # Rigorous truncation to prevent layout shattering
        display_cmd = (self.command[:55] + '...') if len(self.command) > 55 else self.command
        cmd_lbl = QLabel(display_cmd)
        cmd_lbl.setStyleSheet("color: #7A7E85; font-size: 11px;")
        layout.addWidget(cmd_lbl)

        self.update_style()

    def _on_action(self, event):
        if self.state == "running":
            self.stop_requested.emit(self.name)
        else:
            self.start_requested.emit(self.name)
        event = None

    def mousePressEvent(self, event):
        self.clicked.emit(self.name)
        event.accept()

    def set_state(self, state):
        self.state = state
        self.update_style()

    def update_style(self):
        if self.state == "running":
            self.action_btn.setText("Stop")
            self.action_btn.setObjectName("DangerBtn")
            # Enforcing the pervasive green tint for operational nodes
            self.setStyleSheet(
                "NodeCard { background-color: #2A3B2C; border: 1px solid #4CAF50; border-radius: 8px; } NodeCard:hover { background-color: #324734; }")
        elif self.state == "error":
            self.action_btn.setText("Run")
            self.action_btn.setObjectName("RunBtn")
            self.setStyleSheet(
                "NodeCard { background-color: #2B2D30; border: 2px solid #E53935; border-radius: 8px; } NodeCard:hover { background-color: #313438; }")
        else:
            self.action_btn.setText("Run")
            self.action_btn.setObjectName("RunBtn")
            self.setStyleSheet(
                "NodeCard { background-color: #26282B; border: 1px solid #5B5D61; border-radius: 8px; } NodeCard:hover { background-color: #2F3135; }")

        self.action_btn.style().unpolish(self.action_btn)
        self.action_btn.style().polish(self.action_btn)


class GroupCard(QFrame):
    clicked = Signal(str)
    start_all_requested = Signal(str)
    stop_all_requested = Signal(str)
    new_node_requested = Signal(str)
    node_clicked = Signal(str)
    node_start = Signal(str)
    node_stop = Signal(str)

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.nodes = {}

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("GroupCard { background-color: #1E1F22; border: 1px solid #5B5D61; border-radius: 8px; }")

        self.main_layout = QVBoxLayout(self)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.title = QLabel(self.name)
        self.title.setStyleSheet("font-weight: bold; font-size: 16px; color: #56A8F5;")
        header_layout.addWidget(self.title)
        header_layout.addStretch()

        new_node_btn = QPushButton("+ New Node")
        new_node_btn.clicked.connect(lambda: self.new_node_requested.emit(self.name))

        start_all = QPushButton("Run All")
        start_all.setObjectName("RunBtn")
        start_all.clicked.connect(lambda: self.start_all_requested.emit(self.name))

        self.stop_all_btn = QPushButton("Stop All")
        self.stop_all_btn.setObjectName("DangerBtn")
        self.stop_all_btn.setEnabled(False)
        self.stop_all_btn.clicked.connect(lambda: self.stop_all_requested.emit(self.name))

        header_layout.addWidget(new_node_btn)
        header_layout.addWidget(start_all)
        header_layout.addWidget(self.stop_all_btn)
        self.main_layout.addWidget(header_widget)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 10, 0, 0)
        self.main_layout.addWidget(self.grid_widget)

    def mousePressEvent(self, event):
        self.clicked.emit(self.name)
        event.accept()

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

        # Evaluate operational pool to toggle the killswitch
        any_running = any(n.state == "running" for n in self.nodes.values())
        self.stop_all_btn.setEnabled(any_running)

    def _rebuild_grid(self):
        for i in reversed(range(self.grid_layout.count())):
            self.grid_layout.itemAt(i).widget().setParent(None)

        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)

        col_count = 2
        row, col = 0, 0
        for card in self.nodes.values():
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= col_count:
                col = 0
                row += 1


class DashboardBackground(QWidget):
    background_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo.png'))
        self.pixmap = QPixmap(self.logo_path)

    def mousePressEvent(self, event):
        self.background_clicked.emit()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.pixmap.isNull():
            # Amplified watermark scale
            scaled_pixmap = self.pixmap.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio,
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
        self.current_editing_node = None

        self.setWindowTitle("TU Brno Racing - Driverless Command Center")
        self.resize(1500, 900)
        self.setStyleSheet(STYLESHEET)

        self._scaffold_ui()
        QTimer.singleShot(0, lambda: asyncio.create_task(self.initialize_data()))

    def _scaffold_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        toolbar = QHBoxLayout()
        add_group_btn = QPushButton("+ New Group")
        add_group_btn.setObjectName("ActionBtn")
        add_group_btn.clicked.connect(self._prepare_new_group)

        reconnect_btn = QPushButton("⟳ Restart Connectivity")
        reconnect_btn.clicked.connect(self.reconnect_env)

        toolbar.addWidget(add_group_btn)
        toolbar.addStretch()
        toolbar.addWidget(reconnect_btn)
        main_layout.addLayout(toolbar)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # === LEFT PANEL: Dashboard ===
        dash_container = QWidget()
        dash_layout = QVBoxLayout(dash_container)
        dash_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.dash_background = DashboardBackground()
        self.dash_background.background_clicked.connect(lambda: self.context_stack.setCurrentIndex(0))

        self.dash_vbox = QVBoxLayout(self.dash_background)
        self.dash_vbox.setSpacing(15)
        self.dash_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.dash_background)
        dash_layout.addWidget(self.scroll_area)
        self.main_splitter.addWidget(dash_container)

        # === RIGHT PANEL: Adjustable Context & Console ===
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)

        context_container = QWidget()
        context_layout = QVBoxLayout(context_container)
        context_layout.setContentsMargins(10, 0, 0, 0)

        self.context_stack = QStackedWidget()
        context_layout.addWidget(self.context_stack)

        # 0: Idle Page
        idle_page = QWidget()
        QVBoxLayout(idle_page).addWidget(QLabel("Select a node or group to inspect properties."))
        self.context_stack.addWidget(idle_page)

        # 1: Node View Page (Read-only metadata + Matrix)
        self.node_view_page = QWidget()
        view_layout = QVBoxLayout(self.node_view_page)

        self.ctx_view_title = QLabel("Node Name")
        self.ctx_view_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #56A8F5;")
        self.ctx_view_group = QLabel("Group: Unknown")
        self.ctx_view_group.setStyleSheet("color: #BCBEC4; margin-bottom: 10px;")

        view_actions = QHBoxLayout()
        edit_btn = QPushButton("✎ Edit Node Properties")
        edit_btn.clicked.connect(self._transition_to_node_edit)
        view_actions.addWidget(edit_btn)
        view_actions.addStretch()

        view_layout.addWidget(self.ctx_view_title)
        view_layout.addWidget(self.ctx_view_group)
        view_layout.addLayout(view_actions)

        view_layout.addWidget(QLabel("Terminal Matrix Output:"))
        self.terminal_stack = QStackedWidget()
        view_layout.addWidget(self.terminal_stack)
        self.context_stack.addWidget(self.node_view_page)

        # 2: Node Edit Page (Form constraints, devoid of Matrix)
        self.node_edit_page = QWidget()
        edit_layout = QVBoxLayout(self.node_edit_page)

        edit_header = QLabel("Edit Node Architecture")
        edit_header.setStyleSheet("font-size: 18px; font-weight: bold; color: #E6B522;")
        edit_layout.addWidget(edit_header)

        form_layout = QFormLayout()
        self.ctx_group_input = QComboBox()
        self.ctx_name_input = QLineEdit()
        self.ctx_cmd_input = QTextEdit()
        self.ctx_cmd_input.setAcceptRichText(False)
        self.ctx_cmd_input.setMinimumHeight(100)
        self.ctx_cmd_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)

        form_layout.addRow("Assigned Group:", self.ctx_group_input)
        form_layout.addRow("Node Identifier:", self.ctx_name_input)
        form_layout.addRow("Execution Payload:", self.ctx_cmd_input)
        edit_layout.addLayout(form_layout)

        node_actions = QHBoxLayout()
        save_btn = QPushButton("Commit Changes")
        save_btn.setObjectName("ActionBtn")
        save_btn.clicked.connect(self._save_node_context)

        del_btn = QPushButton("Obliterate Node")
        del_btn.setObjectName("DangerBtn")
        del_btn.clicked.connect(self._delete_node_context)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(lambda: self.context_stack.setCurrentIndex(
            1) if self.current_editing_node else self.context_stack.setCurrentIndex(0))

        node_actions.addWidget(save_btn)
        node_actions.addWidget(del_btn)
        node_actions.addStretch()
        node_actions.addWidget(cancel_btn)
        edit_layout.addLayout(node_actions)
        self.context_stack.addWidget(self.node_edit_page)

        # 3: Group Context Page
        self.group_context = QWidget()
        group_layout = QVBoxLayout(self.group_context)

        self.ctx_group_title = QLabel("Group Context")
        self.ctx_group_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #56A8F5;")
        group_layout.addWidget(self.ctx_group_title)

        grp_form_layout = QFormLayout()
        self.ctx_group_name_input = QLineEdit()
        grp_form_layout.addRow("Group Name:", self.ctx_group_name_input)
        group_layout.addLayout(grp_form_layout)

        group_actions = QHBoxLayout()
        save_grp_btn = QPushButton("Save Group")
        save_grp_btn.setObjectName("ActionBtn")
        save_grp_btn.clicked.connect(self._save_group_context)

        del_grp_btn = QPushButton("Delete Group & Nodes")
        del_grp_btn.setObjectName("DangerBtn")
        del_grp_btn.clicked.connect(self._delete_group_context)

        group_actions.addWidget(save_grp_btn)
        group_actions.addWidget(del_grp_btn)
        group_layout.addLayout(group_actions)
        group_layout.addStretch()
        self.context_stack.addWidget(self.group_context)

        self.right_splitter.addWidget(context_container)

        # Global System Console explicitly placed below the context in the splitter
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(10, 10, 0, 0)
        log_layout.addWidget(QLabel("Global System Console"))
        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        log_layout.addWidget(self.system_log)

        self.right_splitter.addWidget(log_widget)

        # Configure initial splitter proportions
        self.right_splitter.setSizes([600, 200])
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setSizes([800, 600])

    async def initialize_data(self):
        self.system_log.append("<span style='color: #4CAF50;'>[SYSTEM] Hooking into environment architecture...</span>")
        try:
            await self._refresh_ui()
            self.system_log.append("<span style='color: #4CAF50;'>[SYSTEM] Dashboard populated.</span>")
        except Exception as e:
            self.system_log.append(f"<span style='color: #E53935;'>[SYSTEM ERROR] Dashboard failure: {str(e)}</span>")

    def _create_group_card(self, group_name):
        g_card = GroupCard(group_name)
        g_card.clicked.connect(self._open_group_context)
        g_card.start_all_requested.connect(self.start_group)
        g_card.stop_all_requested.connect(self.stop_group)
        g_card.new_node_requested.connect(self._prepare_new_node)
        g_card.node_clicked.connect(self._open_node_view)
        g_card.node_start.connect(self.start_node)
        g_card.node_stop.connect(self.stop_node)

        self.groups[group_name] = g_card
        self.dash_vbox.addWidget(g_card)

    async def _refresh_ui(self):
        for i in reversed(range(self.dash_vbox.count())):
            widget = self.dash_vbox.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.groups.clear()

        self._create_group_card("Ungrouped")

        commands = await self.config_manager.load()
        for cmd in commands:
            group_name = cmd.get("group", "Ungrouped")
            node_name = cmd.get("name", "Unknown")
            command_str = cmd.get("command", "")

            if group_name not in self.groups:
                self._create_group_card(group_name)

            self.groups[group_name].add_node(node_name, command_str)
            self._create_node_terminal(node_name)

            if node_name in self.running_processes:
                self.groups[group_name].update_node_state(node_name, "running")

        self._update_group_dropdown()

    def _update_group_dropdown(self):
        self.ctx_group_input.clear()
        self.ctx_group_input.addItems(list(self.groups.keys()))

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

    def _prepare_new_group(self):
        base_name = "New_Macro_Group"
        new_name = base_name
        counter = 1
        while new_name in self.groups:
            new_name = f"{base_name}_{counter}"
            counter += 1

        # Instantly fabricate the visual card on the grid
        self._create_group_card(new_name)
        self._update_group_dropdown()

        # Immediately shift focus to the properties panel for renaming
        self._open_group_context(new_name)
        self.system_log.append(
            f"<span style='color: #4CAF50;'>[SYSTEM] Instantiated empty macro block: {new_name}</span>")

    @asyncSlot()
    async def _save_group_context(self):
        old_name = self.ctx_group_title.text().replace("Context: ", "")
        new_name = self.ctx_group_name_input.text().strip()

        if not new_name:
            self.system_log.append(
                "<span style='color: #E53935;'>[SYSTEM] Aborted save: Group necessitates explicit nomenclature.</span>")
            return

        if old_name != new_name:
            # Dynamically rename the visual card in the UI layer
            if old_name in self.groups:
                group_card = self.groups.pop(old_name)
                group_card.name = new_name
                group_card.title.setText(new_name)
                self.groups[new_name] = group_card

            # Propagate the rename to all underlying nodes within the persistent configuration
            commands = await self.config_manager.load()
            for cmd in commands:
                if cmd.get("group") == old_name:
                    cmd["group"] = new_name
            await self.config_manager.save(commands)
            self._update_group_dropdown()

        self.system_log.append(
            f"<span style='color: #4CAF50;'>[SYSTEM] Persisted group entity modification: {new_name}</span>")
        self._open_group_context(new_name)

    @asyncSlot()
    async def _delete_group_context(self):
        target_group = self.ctx_group_name_input.text().strip()
        if target_group == "Ungrouped":
            QMessageBox.warning(self, "Invalid Operation", "The intrinsic 'Ungrouped' sector cannot be eradicated.")
            return

        reply = QMessageBox.question(self, 'Confirm Eradication',
                                     f"Are you absolutely certain you wish to obliterate the '{target_group}' group AND all constituent nodes?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No: return

        commands = await self.config_manager.load()
        commands = [cmd for cmd in commands if cmd.get("group") != target_group]
        await self.config_manager.save(commands)

        self.system_log.append(
            f"<span style='color: #E6B522;'>[SYSTEM] Obliterated group '{target_group}' and its payload.</span>")
        self.context_stack.setCurrentIndex(0)
        await self._refresh_ui()

    def _prepare_new_node(self, target_group="Ungrouped"):
        self.current_editing_node = None
        self.ctx_name_input.setText("New_Node")
        self.ctx_group_input.setCurrentText(target_group)
        self.ctx_cmd_input.setText("ros2 run ")
        self.context_stack.setCurrentIndex(2)

        temp_term = QTextEdit("Save node configuration to initialize terminal matrix.")
        temp_term.setReadOnly(True)
        self.terminal_stack.addWidget(temp_term)
        self.terminal_stack.setCurrentWidget(temp_term)

    def _open_node_view(self, node_name):
        self.current_editing_node = node_name
        self.ctx_view_title.setText(node_name)

        asyncio.create_task(self._populate_node_view_metadata(node_name))

        if node_name in self.node_terminals:
            self.terminal_stack.setCurrentWidget(self.node_terminals[node_name])

        self.context_stack.setCurrentIndex(1)

    async def _populate_node_view_metadata(self, node_name):
        commands = await self.config_manager.load()
        cmd = next((c for c in commands if c.get("name") == node_name), None)
        if cmd:
            self.ctx_view_group.setText(f"Group: {cmd.get('group', 'Ungrouped')}")

    def _transition_to_node_edit(self):
        if not self.current_editing_node: return

        asyncio.create_task(self._populate_node_edit_form(self.current_editing_node))
        self.context_stack.setCurrentIndex(2)

    async def _populate_node_edit_form(self, node_name):
        commands = await self.config_manager.load()
        cmd = next((c for c in commands if c.get("name") == node_name), None)
        if cmd:
            self.ctx_group_input.setCurrentText(cmd.get("group", "Ungrouped"))
            self.ctx_name_input.setText(cmd.get("name", ""))
            self.ctx_cmd_input.setText(cmd.get("command", ""))

    @asyncSlot()
    async def _save_node_context(self):
        new_data = {
            "group": self.ctx_group_input.currentText().strip() or "Ungrouped",
            "name": self.ctx_name_input.text().strip(),
            "command": self.ctx_cmd_input.toPlainText().strip()
        }

        if not new_data["name"] or not new_data["command"]:
            self.system_log.append(
                "<span style='color: #E53935;'>[SYSTEM] Aborted save: Node requires unambiguous name and command syntax.</span>")
            return

        commands = await self.config_manager.load()

        if self.current_editing_node:
            target_idx = next((i for i, cmd in enumerate(commands) if cmd.get("name") == self.current_editing_node),
                              None)
            if target_idx is not None:
                commands[target_idx] = new_data
        else:
            commands.append(new_data)

        await self.config_manager.save(commands)
        self.system_log.append(
            f"<span style='color: #4CAF50;'>[SYSTEM] Injected {new_data['name']} into configuration matrix.</span>")
        await self._refresh_ui()
        self._open_node_view(new_data["name"])

    @asyncSlot()
    async def _delete_node_context(self):
        target_name = self.ctx_name_input.text().strip()
        if not target_name: return

        reply = QMessageBox.question(self, 'Confirm Demolition',
                                     f"Are you sure you want to completely dismantle '{target_name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No: return

        if target_name in self.node_terminals:
            widget = self.node_terminals.pop(target_name)
            self.terminal_stack.removeWidget(widget)
            widget.deleteLater()

        commands = await self.config_manager.load()
        commands = [cmd for cmd in commands if cmd.get("name") != target_name]
        await self.config_manager.save(commands)

        self.system_log.append(f"<span style='color: #E6B522;'>[SYSTEM] Purged {target_name} from architecture.</span>")
        self.context_stack.setCurrentIndex(0)
        self.current_editing_node = None
        await self._refresh_ui()

    def _open_group_context(self, group_name):
        self.ctx_group_title.setText(f"Context: {group_name}")
        self.ctx_group_name_input.setText(group_name)
        self.context_stack.setCurrentIndex(3)

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
        self.system_log.append(f"<span style='color: #1A73E8;'>[SYSTEM] Igniting {node_name}</span>")
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
                f"<span style='color: #E53935;'>[SYSTEM ERROR] Execution shattered for {node_name}: {str(e)}</span>")

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

                clean_line = ANSI_ESCAPE.sub('', decoded_line)

                # Intercept ROS 2 idiosyncrasies where standard info spills into stderr
                color = "#BCBEC4"  # Default terminal grey
                if "[ERROR]" in clean_line or "[FATAL]" in clean_line:
                    color = "#E53935"
                elif "[WARN]" in clean_line:
                    color = "#E6B522"
                elif "[INFO]" in clean_line or "[DEBUG]" in clean_line:
                    color = "#BCBEC4"
                elif is_error:
                    # Fallback: Unformatted raw tracebacks cascading through stderr
                    color = "#E53935"

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
            "<span style='color: #E53935;'>[SYSTEM] Exterminating all loose threads before termination...</span>")
        commands = await self.config_manager.load()

        for node_name in list(self.running_processes.keys()):
            cmd = next((c for c in commands if c.get("name") == node_name), None)
            if cmd:
                target_process = cmd.get("command").split()[-1]
                await self.executor.execute(f"pkill -f '{target_process}'")

        self.executor.reset()
        self.close()
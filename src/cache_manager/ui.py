import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QAction, QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from cache_manager.deleter import delete_cache_files, format_bytes
from cache_manager.scanner import Node, scan
from cache_manager.size_worker import start_size_thread
from cache_manager.store import MetadataStore, load_config, save_config

ROLE_PATH = Qt.UserRole + 1
ROLE_KIND = Qt.UserRole + 2
ROLE_SIZE = Qt.UserRole + 3
ROLE_WEDGE_INFO = Qt.UserRole + 4

def _fmt_value(v):
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


KIND_ORDER = {
    "root": 0, "category": 1, "hip": 2, "solver": 3,
    "version": 4, "wedge": 5, "folder": 6,
}
COLUMNS = ["Name", "Tags", "Size", "Info"]


class CacheManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Houdini Cache Manager")
        self.resize(1280, 780)

        self.config = load_config()
        self.metadata = MetadataStore()
        self._size_thread = None
        self._size_worker = None
        self._path_to_item = {}

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # --- Toolbar ---
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        self.root_label = QLabel()
        tb.addWidget(self.root_label)
        tb.addSeparator()

        act_change_root = QAction("Change Root…", self)
        act_change_root.triggered.connect(self._change_root)
        tb.addAction(act_change_root)

        act_refresh = QAction("Refresh", self)
        act_refresh.triggered.connect(self.refresh)
        tb.addAction(act_refresh)

        tb.addSeparator()
        self.chk_hide_empty = QCheckBox("Hide empty folders")
        self.chk_hide_empty.setChecked(False)
        self.chk_hide_empty.stateChanged.connect(self._apply_filters)
        tb.addWidget(self.chk_hide_empty)

        # --- Tree ---
        self.tree = QTreeView()
        self.tree.setSelectionMode(QTreeView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(
            "QTreeView { background-color: #1e1e1e;"
            " alternate-background-color: #2b2b2b; }"
        )
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.tree.setModel(self.model)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._priority_threads = []

        # --- Right panel ---
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(8, 8, 8, 8)

        self.sel_label = QLabel("<i>No selection</i>")
        self.sel_label.setWordWrap(True)
        rlay.addWidget(self.sel_label)

        # Tag buttons
        tag_box = QWidget()
        tlay = QHBoxLayout(tag_box)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.addWidget(QLabel("Tags:"))
        self.tag_buttons = {}
        for tag in self.config.get("available_tags", []):
            btn = QPushButton(tag)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, t=tag: self._toggle_tag(t))
            self.tag_buttons[tag] = btn
            tlay.addWidget(btn)
        tlay.addStretch()
        rlay.addWidget(tag_box)

        # Wedge info
        self.info_view = QPlainTextEdit()
        self.info_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.info_view.setFont(mono)
        rlay.addWidget(self.info_view, 1)

        # Delete
        self.btn_delete = QPushButton("Delete Cache Files (selected)")
        self.btn_delete.clicked.connect(self._delete_selected)
        rlay.addWidget(self.btn_delete)

        # --- Splitter ---
        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.setCentralWidget(split)

        # --- Status bar ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)

    # -------------------------------------------------------------- Refresh
    def refresh(self):
        self._cancel_size_thread()

        root_path = self.config.get("cache_root", "")
        self.root_label.setText(f"  Root: <b>{root_path}</b>  ")
        self.model.removeRows(0, self.model.rowCount())
        self._path_to_item.clear()

        if not Path(root_path).exists():
            QMessageBox.warning(
                self, "Cache root not found",
                f"Configured cache_root does not exist:\n{root_path}")
            return

        tree = scan(root_path)
        root_item = self._make_row(tree)
        self.model.invisibleRootItem().appendRow(root_item)
        self._populate_children(root_item[0], tree)
        self.tree.expandToDepth(1)
        for i, w in enumerate([420, 180, 100, 400]):
            self.tree.setColumnWidth(i, w)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)

        self._apply_filters()
        self._start_size_computation()
        self.status.showMessage(f"Loaded {len(self._path_to_item)} folders.", 4000)

    def _make_row(self, node: Node):
        name_item = QStandardItem(node.name)
        name_item.setEditable(False)
        kind_prefix = {
            "root": "📁", "category": "📁", "hip": "🎬",
            "solver": "⚙", "version": "v", "wedge": "🔹", "folder": "📁",
        }.get(node.kind, "")
        name_item.setText(f"{kind_prefix} {node.name}  [{node.kind}]")
        name_item.setData(node.path, ROLE_PATH)
        name_item.setData(node.kind, ROLE_KIND)
        name_item.setData(node.wedge_info, ROLE_WEDGE_INFO)

        tags_item = QStandardItem(", ".join(self.metadata.get_tags(node.path)))
        tags_item.setEditable(False)

        size_item = QStandardItem("…")
        size_item.setEditable(False)
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        info_text = ""
        if node.kind == "wedge" and node.wedge_info:
            overrides = node.wedge_info.get("overrides") or {}
            if overrides:
                info_text = "   ".join(
                    f"{k} = {_fmt_value(v)}" for k, v in overrides.items()
                )
            else:
                info_text = node.wedge_info.get("wedge_label", "")
        info_item = QStandardItem(info_text)
        info_item.setEditable(False)
        info_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_font = QFont()
        info_font.setPointSize(info_font.pointSize() + 1)
        info_item.setFont(info_font)

        self._path_to_item[node.path] = (name_item, tags_item, size_item, info_item)
        self._apply_row_styling(node.path)
        return [name_item, tags_item, size_item, info_item]

    def _populate_children(self, parent_item: QStandardItem, node: Node):
        children = sorted(
            node.children,
            key=lambda c: (KIND_ORDER.get(c.kind, 99), c.name.lower()),
        )
        for child in children:
            row = self._make_row(child)
            parent_item.appendRow(row)
            if child.children:
                self._populate_children(row[0], child)

    def _apply_row_styling(self, path: str):
        items = self._path_to_item.get(path)
        if not items:
            return
        tags = self.metadata.get_tags(path)
        protected = any(t in self.config.get("protected_tags", []) for t in tags)
        color = None
        if protected:
            color = QColor(70, 140, 70)
        elif "trash" in tags:
            color = QColor(160, 60, 60)
        elif "final" in tags:
            color = QColor(167, 205, 250)
        for it in items:
            if color:
                it.setForeground(color)
            else:
                it.setData(None, Qt.ForegroundRole)
        items[1].setText(", ".join(tags))

    # ------------------------------------------------------------ Filtering
    def _apply_filters(self):
        hide_empty = self.chk_hide_empty.isChecked()
        if not hide_empty:
            for path, items in self._path_to_item.items():
                idx = self.model.indexFromItem(items[0])
                self.tree.setRowHidden(idx.row(), idx.parent(), False)
            return
        for path, items in self._path_to_item.items():
            size = items[0].data(ROLE_SIZE)
            if size is not None and size == 0:
                idx = self.model.indexFromItem(items[0])
                self.tree.setRowHidden(idx.row(), idx.parent(), True)

    # ---------------------------------------------------------- Size thread
    def _start_size_computation(self):
        root = self.config.get("cache_root", "")
        if not root or not Path(root).exists():
            return
        self._size_thread, self._size_worker = start_size_thread(
            root, self._on_size_ready, self._on_size_done,
        )
        self.status.showMessage("Computing sizes in background…")

    def _cancel_size_thread(self):
        if self._size_worker:
            try:
                self._size_worker.cancel()
            except RuntimeError:
                pass
        self._size_worker = None
        self._size_thread = None

    def _on_size_ready(self, path: str, size: int):
        items = self._path_to_item.get(path)
        if not items:
            return
        items[0].setData(size, ROLE_SIZE)
        items[2].setText(format_bytes(size))

    def _on_size_done(self):
        self.status.showMessage("Sizes computed.", 4000)
        if self.chk_hide_empty.isChecked():
            self._apply_filters()

    # -------------------------------------------------------------- Actions
    def _on_tree_context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        if not idx.isValid():
            return
        # Make sure the right-clicked row is in the selection so
        # "Compute size" works on all currently-selected paths.
        sel_model = self.tree.selectionModel()
        if not sel_model.isSelected(idx):
            sel_model.select(
                idx,
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
            )

        paths = self._selected_paths()
        menu = QMenu(self.tree)
        act = QAction(
            f"Compute size ({len(paths)} item{'s' if len(paths) != 1 else ''})",
            menu,
        )
        act.triggered.connect(lambda: self._compute_size_for(paths))
        menu.addAction(act)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _compute_size_for(self, paths: list):
        if not paths:
            return
        for root_path in paths:
            items = self._path_to_item.get(root_path)
            if not items:
                continue
            for p in self._collect_subtree_paths(items[0]):
                sub = self._path_to_item.get(p)
                if sub:
                    sub[2].setText("computing…")
            thread, _w = start_size_thread(
                root_path,
                self._on_size_ready,
                on_done=lambda r=root_path: self.status.showMessage(
                    f"Size computed: {r}", 4000),
            )
            self._priority_threads.append(thread)
        self.status.showMessage(
            f"Computing size for {len(paths)} subtree(s)…")

    def _collect_subtree_paths(self, name_item: QStandardItem) -> list:
        out = [name_item.data(ROLE_PATH)]
        for row in range(name_item.rowCount()):
            child = name_item.child(row, 0)
            if child is not None:
                out.extend(self._collect_subtree_paths(child))
        return out

    def _change_root(self):
        current = self.config.get("cache_root", "")
        chosen = QFileDialog.getExistingDirectory(self, "Choose cache root", current)
        if chosen:
            self.config["cache_root"] = chosen.replace("\\", "/")
            save_config(self.config)
            self.refresh()

    def _selected_paths(self) -> list:
        idxs = self.tree.selectionModel().selectedRows(0)
        paths = []
        for idx in idxs:
            item = self.model.itemFromIndex(idx)
            p = item.data(ROLE_PATH)
            if p:
                paths.append(p)
        return paths

    def _on_selection(self, *_):
        paths = self._selected_paths()
        if not paths:
            self.sel_label.setText("<i>No selection</i>")
            self.info_view.clear()
            for b in self.tag_buttons.values():
                b.setChecked(False)
                b.setEnabled(False)
            return

        for b in self.tag_buttons.values():
            b.setEnabled(True)

        if len(paths) == 1:
            p = paths[0]
            items = self._path_to_item.get(p)
            kind = items[0].data(ROLE_KIND) if items else ""
            size = items[0].data(ROLE_SIZE) if items else None
            size_txt = format_bytes(size) if isinstance(size, int) else "computing…"
            self.sel_label.setText(
                f"<b>{Path(p).name}</b> &nbsp; "
                f"<span style='color:#888'>[{kind}]</span><br>"
                f"<small>{p}</small><br>"
                f"Size: <b>{size_txt}</b>"
            )
            wedge_info = items[0].data(ROLE_WEDGE_INFO) if items else None
            if wedge_info:
                self.info_view.setPlainText(json.dumps(wedge_info, indent=2))
            else:
                self.info_view.setPlainText("")
            tags = set(self.metadata.get_tags(p))
        else:
            self.sel_label.setText(f"<b>{len(paths)} items selected</b>")
            self.info_view.setPlainText("\n".join(paths))
            common = None
            for p in paths:
                t = set(self.metadata.get_tags(p))
                common = t if common is None else common & t
            tags = common or set()

        for name, btn in self.tag_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(name in tags)
            btn.blockSignals(False)

    def _toggle_tag(self, tag: str):
        for p in self._selected_paths():
            tags = set(self.metadata.get_tags(p))
            if tag in tags:
                tags.discard(tag)
            else:
                tags.add(tag)
            self.metadata.set_tags(p, list(tags))
            self._apply_row_styling(p)
        self._on_selection()

    def _delete_selected(self):
        paths = self._selected_paths()
        if not paths:
            return
        protected_tags = self.config.get("protected_tags", [])

        def is_protected(path: str) -> bool:
            return self.metadata.has_protected_tag(path, protected_tags)

        blocked = [p for p in paths if is_protected(p)]
        if blocked:
            names = "\n".join(f" - {Path(p).name}" for p in blocked[:10])
            QMessageBox.warning(
                self, "Protected",
                "Some selected items are protected by 'keep' and "
                f"won't be touched:\n{names}")

        reply = QMessageBox.question(
            self, "Delete cache files",
            f"Permanently delete cache files under {len(paths)} item(s)?\n"
            f"Folders, tags, and *.json descriptors are preserved.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        total_files = 0
        total_bytes = 0
        errors = []
        preserve = self.config.get("preserve_extensions", [".json"])
        for p in paths:
            stats = delete_cache_files(p, preserve, is_protected)
            total_files += stats["deleted_files"]
            total_bytes += stats["freed_bytes"]
            errors.extend(stats["errors"])

        msg = f"Deleted {total_files} files. Freed {format_bytes(total_bytes)}."
        if errors:
            msg += f"\n{len(errors)} errors (see details)."
            box = QMessageBox(self)
            box.setWindowTitle("Delete complete")
            box.setText(msg)
            box.setDetailedText("\n".join(f"{p}: {m}" for p, m in errors[:50]))
            box.exec()
        else:
            QMessageBox.information(self, "Delete complete", msg)

        self.status.showMessage(msg, 6000)
        self.refresh()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = CacheManagerWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

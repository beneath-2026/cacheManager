import os
import sys
from PySide6.QtCore import QObject, QThread, Signal

# Deep wedge trees stay well under default recursion limits, but be generous.
sys.setrecursionlimit(10000)


class SizeWorker(QObject):
    """Walks a single root once with os.scandir, emitting a total size for
    every folder on the way back up. Because each directory listing already
    carries stat data, file sizes cost no extra round-trip. Parent totals are
    aggregated from child totals — no directory is ever walked twice."""

    sizeReady = Signal(str, object)  # normalized path, total bytes (incl. descendants)
    finished = Signal()

    def __init__(self, root: str):
        super().__init__()
        self._root = root
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self._walk(self._root)
        finally:
            self.finished.emit()

    def _walk(self, path: str) -> int:
        if self._cancel:
            return 0
        total = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if self._cancel:
                        return 0
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            total += self._walk(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
        if not self._cancel:
            norm = path.replace("\\", "/")
            self.sizeReady.emit(norm, total)
        return total


def start_size_thread(root: str, on_size, on_done=None):
    thread = QThread()
    worker = SizeWorker(root)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.sizeReady.connect(on_size)
    worker.finished.connect(thread.quit)
    if on_done:
        worker.finished.connect(on_done)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker

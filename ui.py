"""ui.py - UI interface for sync_module.

`Systray app solution <https://evileg.com/en/post/68/>`_

----------------
COPYRIGHT NOTICE
----------------
Copyright (C) 2021 Samuel Wirth

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import logging
import time
import traceback
from typing import Callable

import PyQt5
import sys

from PyQt5.QtWidgets import QFileDialog, QAction, QMenu, qApp, QSystemTrayIcon, QStyle, QApplication
from savemgr import ManagerSession
from PyQt5 import QtWidgets, uic, QtCore  # noqa
from PyQt5.QtCore import QRunnable, pyqtSlot, QThreadPool, QThread, QObject, pyqtSignal


class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread.

    Available signal data types:
        - finished: None
        - error: Tuple (exctype, value, traceback.format_exc()) - An exception.
        - result: Any, Object - The data returned from the Worker thread.

    The above defined signals are all :class:`PyQt5.QtCore.pyqtSignal` objects.
    """

    progress = pyqtSignal(int, int)
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)


class Worker(QRunnable):
    """Worker thread"""

    def __init__(self, fn, *args, **kwargs):
        """
        :param Callable fn: The function to run on this thread.
        :param args: Arguments to pass to the function
        :param kwargs: Keywords arguments to pass to the function
        """

        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        """Initialize runner function; pass args and kwargs."""
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:  # noqa
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.signals.finished.emit()  # Done


class MonitoredWorker(Worker):
    """Passes callabck function to worker function under given kwarg"""

    def __init__(self, kwarg_name, fn, *args, **kwargs):
        """

        :param kwarg_name: The name of a kwarg for the callback function in 'fn'
        :param Callable fn: The function to run on this thread.
        :param args: Arguments to pass to the function
        :param kwargs: Keywords arguments to pass to the function
        """

        kwargs[kwarg_name] = self.callback_delegate
        super().__init__(fn, *args, **kwargs)

    def callback_delegate(self, n, i):
        self.signals.progress.emit(n, i)


class Custom(QtWidgets.QDialog):
    def __init__(self, parent):
        super(Custom, self).__init__(parent)
        self.app = parent.app
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        uic.loadUi('UI/custom.ui', self)

        self.accepted.connect(self.add_custom)

        self.show()

    def add_custom(self):
        pass


class AddGame(QtWidgets.QDialog):
    def __init__(self, parent):
        super(AddGame, self).__init__(parent)
        self.app = parent.app
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        uic.loadUi('UI/add_game.ui', self)

        self.add_button = self.findChild(QtWidgets.QToolButton, 'add_cloud_button')

        self.accepted.connect(self.enable_game)
        self.add_button.clicked.connect(self.new_game)

        self.game_name = ''
        self.show()

    def enable_game(self):
        pass

    def new_game(self):
        Custom(self)


class GameList(QtWidgets.QDialog):
    def __init__(self, parent):
        super(GameList, self).__init__(parent)
        self.app = parent
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        uic.loadUi('UI/game_list.ui', self)

        self.add_button = self.findChild(QtWidgets.QPushButton, 'add_button')
        self.disable_button = self.findChild(QtWidgets.QPushButton, 'disable_button')

        self.add_button.clicked.connect(self.show_cloud_saves)

        self.show()

    def show_cloud_saves(self):
        AddGame(self)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        """        QApplication.beep()
"""
        super(MainWindow, self).__init__()

        # region Load the UI
        uic.loadUi('UI/main.ui', self)
        self.verticalLayout.setContentsMargins(9, 9, 9, 9)
        self.verticalLayout.setSpacing(6)
        # endregion

        # region Get references to widgets in ui file
        self.sync_button = self.findChild(QtWidgets.QPushButton, 'sync_button')
        self.auto_checkbox = self.findChild(QtWidgets.QCheckBox, 'auto_option')
        self.sync_progress = self.findChild(QtWidgets.QProgressBar, 'sync_progress')
        self.list_button = self.findChild(QtWidgets.QPushButton, 'list_button')
        self.settings_button = self.findChild(QtWidgets.QPushButton, 'settings_button')
        # endregion

        # region Connect to slots
        self.sync_button.clicked.connect(self.consecutive_save_sync)
        self.list_button.clicked.connect(self.show_game_list)
        self.settings_button.clicked.connect(self.show_settings)  # TODO: Fill this in
        # endregion

        # region Module-defined widgets
        self.status_bar = QtWidgets.QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.tray_icon = QSystemTrayIcon(self)

        self.show_action = QAction("Show", self)
        self.quit_action = QAction("Exit", self)
        self.show_action.triggered.connect(self.show)
        self.quit_action.triggered.connect(qApp.quit)
        self.init_systray()
        # endregion

        # region Initialize API
        self.session = ManagerSession()
        self.settings = self.session.local_config  # Make this more readable.
        self.update_settings = self.session.update_local_config
        # endregion

        # region Threading
        self.thread_queue = []
        self.queue_progress = {}
        self.task_count = 0
        self.start_time = 0.0
        self.end_time = 0.0
        self.threadpool = QThreadPool()
        print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())
        # endregion

        self.show()

        # region Login to google
        worker = Worker(self.login)
        self.thread_starter(worker)

    def closeEvent(self, event):
        """Minimize to systray, forcing user to close from systray icon"""

        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "GDrive Game Sync",
            "Minimized to Tray",
            QSystemTrayIcon.Information,
            2000
        )

    def init_systray(self):
        """Create the systray icon"""

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        tray_menu = QMenu()
        tray_menu.addAction(self.show_action)
        tray_menu.addAction(self.quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def allow_usr_input(self, x):
        """Disable all widgets except for QStatusBar.

        This can be extended if needed.

        :param bool x: Boolean value. Allow or disallow user input.
        """

        self.quit_action.setEnabled(x)
        for i in self.findChildren(QtWidgets.QWidget):
            if not isinstance(i, QtWidgets.QStatusBar) or not isinstance(i, QtWidgets.QProgressBar):
                i.setEnabled(x)

    def report_progress(self, n, i):
        """Support thread_reporter callback for sync_module. Reports to the progress bar.

        Uniquely identifies each task by thread ID so progress values can be maintained across
        consecutive tasks.

        :param int n: The progress percent as an integer for the caller.
        :param int i: The current iteration of the consecutive sync calls.
        :param bool reset: Reset the progress bar.
        """

        if n != -1 and i != -1:
            progress_data = {str(i): n}
            self.queue_progress.update(progress_data)

            progress_value = 0

            for thread in self.queue_progress:
                progress_value += int(self.queue_progress[thread] / self.task_count)

            self.sync_progress.setValue(progress_value)
        else:
            self.sync_progress.setValue(0)
            self.queue_progress = {}
            self.task_count = 0

    @pyqtSlot()
    def sync_queue_delegate(self):
        """Continue worker thread execution until the queue is empty."""

        if self.thread_queue:
            worker = self.thread_queue.pop(0)
            self.thread_starter(worker)
        else:
            self.end_time = time.time()
            self.allow_usr_input(True)
            self.report_progress(-1, -1)
            QApplication.beep()
            logger.info("All games synced!")
            logger.info(f"All games took {self.end_time - self.start_time} seconds")  # TODO: debug

    def consecutive_save_sync(self):
        """Sync games saves with ManagerSession.sync, consecutively.

        Creates a queue of worker threads, each connecting to the sync_queue_delegate on completion.
        """

        self.allow_usr_input(False)
        self.start_time = time.time()
        logger.info("Syncing...")

        initial_worker = None
        for i, game in enumerate(self.settings['games']):
            worker = MonitoredWorker('progress_callback', self.session.sync, i)
            worker.signals.finished.connect(self.sync_queue_delegate)
            worker.signals.progress.connect(self.report_progress)

            if i == 0:
                initial_worker = worker
            else:
                self.thread_queue.append(worker)

        self.task_count = len(self.thread_queue) + 1
        self.threadpool.start(initial_worker)

    def login(self):
        self.quit_action.setEnabled(False)

        logger.info("Logging in...")
        self.session.authenticate()
        logger.info("Success authenticating!")

        self.quit_action.setEnabled(True)
        self.allow_usr_input(True)

    def thread_starter(self, worker):
        logger.debug(f"Starting worker thread with callable {worker.fn}. Args: {worker.args}, {worker.kwargs}")
        self.threadpool.start(worker)
        logger.debug(f"Worker started")

    def show_game_list(self):
        self.task_count = 10
        for _ in range(0, 10):
            worker = Worker(self.session.testmeth)
            self.thread_starter(worker)

        # GameList(self)

    def show_settings(self):
        pass


if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
    PyQt5.QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)

if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
    PyQt5.QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

logger = logging.getLogger(__name__)


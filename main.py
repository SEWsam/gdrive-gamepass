"""main.py: main entrypoint for UI module.

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

import sys
import logging
from PyQt5 import QtWidgets
from ui import MainWindow


class CustomLogRecord(logging.LogRecord):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.origin = f"{self.name}:{self.funcName}"


class StatusBarLogger(logging.Handler):
    def __init__(self, parent):
        super(StatusBarLogger, self).__init__()
        self.parent = parent

    def emit(self, record):
        msg = self.format(record)
        self.parent.status_bar.showMessage(msg)


logging.setLogRecordFactory(CustomLogRecord)
root_logger = logging.getLogger()
root_logger.setLevel('DEBUG')

pyqt_logger = logging.getLogger('PyQt5')
pyqt_logger.setLevel('ERROR')

log_file_handler = logging.FileHandler(filename='debug.log')
log_file_handler.setLevel('DEBUG')
log_file_format = logging.Formatter('%(asctime)s - %(origin)-40s - %(levelname)-8s - %(message)s')
log_file_handler.setFormatter(log_file_format)
root_logger.addHandler(log_file_handler)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()

    base_handler = StatusBarLogger(window)
    base_handler.setLevel(logging.INFO)
    base_format = logging.Formatter('%(message)s')
    base_handler.setFormatter(base_format)
    root_logger.addHandler(base_handler)

    app.exec_()

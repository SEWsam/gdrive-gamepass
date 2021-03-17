"""
Copyright (c) 2021 Samuel Wirth

Licensed under the MIT License. See LICENSE for more info.
"""

import os
import PyQt5
import sys

from PyQt5.QtWidgets import QFileDialog
import sync_module
from PyQt5 import QtWidgets, uic, QtCore
from PyQt5.QtCore import QRunnable


class Custom(QtWidgets.QDialog):
    def __init__(self, parent):
        super(Custom, self).__init__(parent)
        self.parent = parent
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        uic.loadUi('UI/custom.ui', self)

        self.accepted.connect(self.add_custom)

        self.show()

    def add_custom(self):
        pass


class AddGame(QtWidgets.QDialog):
    def __init__(self, parent):
        super(AddGame, self).__init__(parent)
        self.parent = parent
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
        self.parent = parent
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
        super(MainWindow, self).__init__()

        uic.loadUi('UI/main.ui', self)
        self.verticalLayout.setContentsMargins(9, 9, 9, 9)
        self.verticalLayout.setSpacing(6)

        self.game_list = self.findChild(QtWidgets.QPushButton, 'list_button')

        self.game_list.clicked.connect(self.show_game_list)

        self.show()

    def show_game_list(self):
        GameList(self)


app = QtWidgets.QApplication(sys.argv)
window = MainWindow()
app.exec_()

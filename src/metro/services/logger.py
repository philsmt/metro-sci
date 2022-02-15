
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import logging

import metro

QtCore = metro.QtCore
QtWidgets = metro.QtWidgets

# Configure level from which to show logged events: DEBUG, INFO, WARN, ERROR
level = logging.INFO


# The base handler is the basic handler for most loggers, which can be shown
# in the Metro main window. There should be only this one base handler, but
# other 'local' handlers can exist.
base_handler = None
# List of all non-local loggers created so far
loggers = []


def log(name, local=False):
    log = logging.getLogger(name)
    if local:
        return log

    global base_handler, loggers
    loggers.append(name)
    if base_handler is not None:
        base_handler.addLogger(name)
    return log


class QTextEditLogger(logging.Handler, QtCore.QObject):
    newEntry = metro.QSignal()
    appendEntry = metro.QSignal(str)

    def __init__(self, parent, logger=None, base=False,
                 format_str='%(asctime)s - %(name)s- '
                            '%(levelname)s - %(message)s'):
        super().__init__()
        QtCore.QObject.__init__(self)

        self.widget = QtWidgets.QPlainTextEdit(parent)
        self.widget.setReadOnly(True)
        self.appendEntry.connect(self.widget.appendPlainText)

        self.setFormatter(logging.Formatter(format_str))

        if logger is not None:
            self.addLogger(logger)

        if base:
            global base_handler, loggers
            base_handler = self
            self.addLogger(loggers)

    def emit(self, record):
        entry = self.format(record)
        self.appendEntry.emit(entry)
        self.newEntry.emit()

    def addLogger(self, logger):
        if type(logger) is list:
            for l in logger:
                logging.getLogger(l).addHandler(self)
        else:
            logging.getLogger(logger).addHandler(self)


class LogWindow(QtWidgets.QWidget):
    def __init__(self, parent=None, logger=None, base=False):
        super().__init__(parent)

        self.logTextBox = QTextEditLogger(self, logger, base)

        self.buttonClear = QtWidgets.QPushButton(self)
        self.buttonClear.setText('Clear log')
        self.buttonClear.setMaximumWidth(100)

        layout = QtWidgets.QVBoxLayout()
        self.resize(QtCore.QSize(500, 300))
        self.setMinimumWidth(250)
        layout.addWidget(self.logTextBox.widget)
        layout.addWidget(self.buttonClear)
        self.setLayout(layout)

        self.buttonClear.clicked.connect(self.clearLog)

    def addLogger(self, logger):
        self.logTextBox.addLogger(logger)

    def clearLog(self):
        self.logTextBox.widget.clear()

    def onNewEntry(self, slot):
        self.logTextBox.newEntry.connect(slot)


# Set the basic level of the root logger so all created loggers from now on
# inherit this level
logging.getLogger().setLevel(level)

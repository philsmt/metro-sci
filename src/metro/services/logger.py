
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import logging
from os.path import join

import metro

QtCore = metro.QtCore
QtWidgets = metro.QtWidgets
QtGui = metro.QtGui

# Configure level from which to show logged events: DEBUG, INFO, WARN, ERROR
level = logging.INFO


# The base handler is the basic handler for most loggers, which can be shown
# in the Metro main window. There should be only this one base handler, but
# other 'local' handlers can exist.
base_handler = None
# List of all non-local loggers created so far
loggers = []
txt_formatter = logging.Formatter('%(asctime)s [%(name)s] '
                                  '%(levelname)s:\n%(message)s')

# Create file handler to store the base log on the disk
logfile_path = join(metro.LOCAL_PATH, 'metro.log')
file_handler = logging.FileHandler(logfile_path)
file_handler.setLevel(level)
file_handler.setFormatter(txt_formatter)


def log(name, local=False):
    log = logging.getLogger(name)

    if local:
        return log

    log.addHandler(file_handler)

    global base_handler, loggers
    loggers.append(name)
    if base_handler is not None:
        base_handler.addLogger(name)

    return log


class QTextEditLogger(logging.Handler, QtCore.QObject):
    newEntry = metro.QSignal(int)
    appendEntry = metro.QSignal(str)

    def __init__(self, parent, logger=None, base=False,
                 format_str=None, html=False):
        super().__init__()
        QtCore.QObject.__init__(self)

        self.widget = QtWidgets.QPlainTextEdit(parent)
        self.widget.setReadOnly(True)

        if html:
            self.appendEntry.connect(self.widget.appendHtml)
        else:
            self.appendEntry.connect(self.widget.appendPlainText)

        if format_str is None:
            global txt_formatter
            self.setFormatter(txt_formatter)
        else:
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
        self.newEntry.emit(record.levelno)
        # scrollbar = self.widget.verticalScrollBar()
        # scrollbar.setValue(scrollbar.maximum())

    def addLogger(self, logger):
        if type(logger) is list:
            for l in logger:
                logging.getLogger(l).addHandler(self)
        else:
            logging.getLogger(logger).addHandler(self)


class LogWindow(QtWidgets.QWidget):
    def __init__(self, parent=None, logger=None, base=False):
        super().__init__(parent)

        self.logTextBox = QTextEditLogger(self, logger, base, html=True)
        self.logTextBox.setFormatter(HtmlFormatter())

        self.buttonClear = QtWidgets.QPushButton(self)
        self.buttonClear.setText('Clear log')
        self.buttonClear.setMaximumWidth(100)

        layout = QtWidgets.QVBoxLayout()
        self.resize(QtCore.QSize(600, 400))
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


class HtmlFormatter(logging.Formatter):
    FORMATS = {
        logging.DEBUG:
            ("%(asctime)s [%(name)s] %(levelname)-8s [%(filename)s:%(lineno)d]"
            " \n%(message)s",
            QtGui.QColor(30, 120, 30)),
        logging.INFO:
            ("%(asctime)s [%(name)s] %(levelname)-8s\n%(message)s",
            QtGui.QColor(40, 40, 200)),
        logging.WARNING:
            ('%(asctime)s [%(name)s] %(levelname)-8s\n%(message)s',
            QtGui.QColor(200, 100, 20)),
        logging.ERROR:
            ("%(asctime)s [%(name)s] %(levelname)-8s\n%(message)s",
            QtGui.QColor(200, 30, 30)),
        }

    FORMAT_STR = '<font color="{color}"><pre>{fmt}</pre></font>'

    def format(self, record):
        last_fmt = self._style._fmt
        opt = self.FORMATS.get(record.levelno)
        if opt:
            fmt, color = opt
            self._style._fmt = self.FORMAT_STR.format(
                color=QtGui.QColor(color).name(), fmt=fmt.replace("\n", "<br>"))
        res = logging.Formatter.format(self, record)
        self._style._fmt = last_fmt
        return res


# Set the basic level of the root logger so all created loggers from now on
# inherit this level
logging.getLogger().setLevel(level)

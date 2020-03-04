
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import math

import numpy
from PyQt5 import QtCore, QtGui

import metro


class Device(metro.WidgetDevice, metro.DisplayDevice):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(),
        'base': ('dec', 'bin', 'oct', 'hex')
    }

    descriptions = {
        '__main__': 'Displays the last channel value as a sorted list',
        'channel': 'The channel to be displayed.',
        'base': 'test'
    }

    def prepare(self, args, state):
        self.channel = args['channel']

        self.resize(325, 325)
        self.setStyleSheet('background-color: black;')
        self.setSizePolicy(metro.QtWidgets.QSizePolicy.Fixed,
                           metro.QtWidgets.QSizePolicy.Fixed)

        self.data = None

        if args['base'] == 'dec':
            self.base_func = lambda x, max_: str(int(x))
        elif args['base'] == 'bin':
            self.base_func = lambda x, max_: bin(int(x))[2:].zfill(max(
                8, math.ceil(math.log2(max_))
            ))
        elif args['base'] == 'oct':
            self.base_func = lambda x, max_: oct(int(x))[2:]
        elif args['base'] == 'hex':
            self.base_func = lambda x, max_: hex(int(x))[2:]

        self.channel.subscribe(self)

    def finalize(self):
        try:
            self.channel.unsubscribe(self)
        except AttributeError:
            pass

        super().finalize()

    @staticmethod
    def isChannelSupported(channel):
        return True

    def dataSet(self, d):
        pass

    def dataAdded(self, d):
        d = numpy.column_stack((numpy.arange(len(d)), d))
        d = d[numpy.greater(d[:, 1], 0)]

        if len(d) == 0:
            return

        self.data = d[d[:, 1].argsort()]
        self.repaint()

    def dataCleared(self):
        self.data = None
        self.repaint()

    def paintEvent(self, event):
        qp = QtGui.QPainter(self)

        width = self.width()
        height = self.height()

        qp.eraseRect(0, 0, width, height)

        qp.setPen(QtCore.Qt.white)

        if self.data is None:
            qp.drawText(25, 30, 'no data')
            return

        cur_y = 15

        max_index = self.data[:, 0].max()
        max_value = self.data[:, 1].max()

        for entry in self.data[::-1]:
            qp.drawText(20, cur_y, self.base_func(entry[0], max_index))
            qp.fillRect(80, cur_y-9, (entry[1]/max_value)*(width-100), 10,
                        QtCore.Qt.white)

            cur_y += 15

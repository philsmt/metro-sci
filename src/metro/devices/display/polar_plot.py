
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from PyQt5 import QtWidgets

import numpy

from matplotlib import rc as mpl_rc
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

import metro


class Device(metro.WidgetDevice, metro.DisplayDevice):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(),
        'flow': ('open', 'cyclic', 'extend'),
        'normalize': False,
        'radial_labels': True,
        'theta_start': 0,
        'theta_end': 2,
        'theta_direction': ('CW', 'CCW'),
        'theta_offset': 0.0,
    }

    descriptions = {
        '__main__': 'Diplays a one-dimensional signal in a polar projection',
        'channel': 'Channel to display',
        'flow': 'Describes how to project the data points on an arc. "Open" '
                'assumes that the points cover the range indicated by start '
                'and end without connection while "cyclic" assumes that the '
                'first and last points overlap. "Extend" will transform an '
                '"open" dataset into "cyclic" by adding another point at the '
                'end.',
        'normalize': 'Whether to always normalize the data to 1',
        'radial_labels': 'Whether to display labels on the radial axis',
        'theta_start': 'Start angle in units of pi.',
        'theta_end': 'End angle in units of pi.',
        'theta_direction': 'Direction of the theta axis',
        'theta_offset': 'Offset of the theta axis with respect to 0 on the '
                        'given as a radian in units of pi'
    }

    def prepare(self, args, state):
        self.channel = args['channel']
        self.flow = args['flow']
        self.normalize = args['normalize']
        self.radial_labels = args['radial_labels']
        self.theta_start = args['theta_start']
        self.theta_end = args['theta_end']
        self.theta_direction = -1 if args['theta_direction'] == 'CW' else 1
        self.theta_offset = (1.0 + args['theta_offset']) * 3.1415

        self.figure = Figure(figsize=(5, 4), dpi=100, facecolor='black')

        try:
            self.axes = self.figure.add_subplot(111, facecolor='black',
                                                polar=True)
        except AttributeError:
            # Backwards compatibility for older versions of matplotlib
            self.axes = self.figure.add_subplot(111, axisbg='black',
                                                polar=True)

        mpl_rc('grid', color='#969696')
        self.axes.xaxis.set_tick_params(color='#969696', labelcolor='#969696')
        self.axes.yaxis.set_tick_params(color='#969696', labelcolor='#969696')
        self.axes.spines['polar'].set_color('#969696')

        self.canvas = FigureCanvasQTAgg(self.figure)

        self.canvas.setParent(self)
        self.canvas.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                  QtWidgets.QSizePolicy.Expanding)
        self.canvas.updateGeometry()

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.x = None
        self.last_y_len = 0

        self.channel.subscribe(self)

        self.axes.set_theta_direction(self.theta_direction)
        self.axes.set_theta_offset(self.theta_offset)
        self.axes.set_yticklabels([])

    def finalize(self):
        self.channel.unsubscribe(self)

    def dataSet(self, d):
        pass

    def dataAdded(self, d):
        if len(d) != self.last_y_len or self.x is None:
            d_len = len(d)

            x_start = self.theta_start
            x_end = self.theta_end
            x_len = d_len

            if self.flow == 'open':
                x_end = (x_end - x_start) * ((d_len - 1) / d_len)
            elif self.flow == 'cyclic':
                pass
            elif self.flow == 'extend':
                x_len += 1

            self.x = numpy.linspace(x_start * 3.1415, x_end * 3.1415, x_len)
            self.last_y_len = d_len

        d_max = d.max()

        if d_max == 0.0:
            return

        if self.flow == 'extend':
            d = numpy.append(d, d[0])

        if self.normalize:
            self.axes.set_ylim([0, 1.1])
            d = d / d_max

        self.axes.cla()
        self.axes.plot(self.x, d, 'r.-', markersize=10)
        self.axes.set_theta_direction(self.theta_direction)
        self.axes.set_theta_offset(self.theta_offset)

        if not self.radial_labels:
            self.axes.set_yticklabels([])

        self.canvas.draw()

    def dataCleared(self):
        self.axes.cla()

    @classmethod
    def isChannelSupported(self, channel):
        return True


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from PyQt5 import QtWidgets

import numpy as np
import xarray as xr

from matplotlib import rc as mpl_rc
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

import metro

from .fast_plot import COLOR_STYLES
LINE_COLORS = [tuple((y/255 for y in x[0])) for x in COLOR_STYLES['default']]
MARKER_COLORS = [tuple((y/255 for y in x[1])) for x in COLOR_STYLES['default']]


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

        self.legend = None
        self.legend_entries = None

        self.channel.subscribe(self)

        self.axes.set_theta_direction(self.theta_direction)
        self.axes.set_theta_offset(self.theta_offset)
        self.axes.set_yticklabels([])

    def finalize(self):
        self.channel.unsubscribe(self)

    def dataSet(self, d):
        pass

    def dataAdded(self, d):
        if isinstance(d, xr.DataArray):
            self.x = d.coords[d.dims[-1]].data * (np.pi/180)

            if d.data.ndim > 1:
                legend_entries = d.coords[d.dims[0]].data
                legend_dirty = False

                if (legend_entries != self.legend_entries).any():
                    self.legend_entries = legend_entries
                    legend_dirty = True

            d = d.data

        elif len(d) != self.last_y_len or self.x is None:
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

            self.x = np.linspace(x_start * 3.1415, x_end * 3.1415, x_len)
            self.last_y_len = d_len

            if self.flow == 'extend':
                d = np.append(d, d[0])

        if self.normalize:
            self.axes.set_ylim([0, 1.1])
            d = d / d.max()

            if not np.isfinite(d).all():
                d[:] = 0.0

        self.axes.cla()
        plot_kwargs = dict(linewidth=1, ms=10)

        if d.ndim == 1:
            self.axes.plot(self.x, d, '.-',
                           c=LINE_COLORS[0],
                           mfc=MARKER_COLORS[0], mec=MARKER_COLORS[0],
                           **plot_kwargs)
        else:
            for i, row in enumerate(d):
                self.axes.plot(self.x, row, '.-',
                               c=LINE_COLORS[i],
                               mfc=MARKER_COLORS[i], mec=MARKER_COLORS[i],
                               label=legend_entries[i], **plot_kwargs)

            if legend_dirty:
                if self.legend is not None:
                    self.legend.remove()

                self.legend = self.figure.legend(
                    loc='upper left', facecolor='none',
                    labelcolor='white', edgecolor='white')

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

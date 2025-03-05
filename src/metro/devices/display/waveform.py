
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import collections

import numpy
import xarray as xr

import metro
from metro.devices.abstract import single_plot


class Device(single_plot.Device, metro.DisplayDevice):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(shape=0),
        'index': metro.IndexArgument(allow_scalar=True),
        'mode': ('trendline', 'scatter'),
        'wave_points': 40,
        'ma_points': 5,
        'ma_enabled': False,
        'bg_text': '',
    }

    descriptions = {
        '__main__': 'Displays a scalar sample over time.',
        'channel': 'Channel to be displayed.',
        'index': 'Index to the channel data',
        'mode': 'How to render waveform data',
        'wave_points': 'Number of samples to plot at a time for continuous '
                       'channels or if unknown for step channels.',
        'ma_points': 'Number of samples used for calculating the moving '
                     'average',
        'ma_enabled': 'Whether moving average is enabled by default.',
        'bg_text': 'Initial background text, chosen automatically if empty.'
    }

    def prepare(self, args, state):
        self.channel = args['channel']
        self.index = args['index']
        self.mode = args['mode']
        self.wave_points = args['wave_points']
        self.ma_points = args['ma_points']

        self.has_metropc_tags = hasattr(self.channel, '_metropc_tags') \
            and self.channel.freq == metro.AbstractChannel.STEP_SAMPLES

        if state is not None:
            self.raw_enabled = state[0]
            self.ma_enabled = state[1]
        else:
            self.raw_enabled = True
            self.ma_enabled = args['ma_enabled']

        self.y_label = ''
        self.x_data = None
        self.y_data = []
        self.ma_buffer = collections.deque(maxlen=self.ma_points)
        self.ma_data = []

        self.raw_curve = None
        self.ma_curve = None

        if args['bg_text']:
            bg_text = args['bg_text']
        else:
            bg_text = self.channel.name

            if args['index'] != metro.IndexArgument.fullIndex:
                bg_text += '/' + metro.IndexArgument._index2str(args['index'])

        super().prepare(args, state, bg_text)

        self.addSubscriptionMenu()

        menu = self.plot_widget.getPlotItem().getViewBox().menu
        menu.addSeparator()

        self.menuShowCurves = menu.addMenu('Show curves')
        self.menuShowCurves.triggered.connect(self.on_menuShowCurves_triggered)

        self.actionEnableRaw = self.menuShowCurves.addAction('Raw')
        self.actionEnableRaw.setCheckable(True)
        self.actionEnableRaw.setChecked(self.raw_enabled)

        self.actionEnableMA = self.menuShowCurves.addAction('Moving average')
        self.actionEnableMA.setCheckable(True)
        self.actionEnableMA.setChecked(self.ma_enabled)

        self.plot_item.enableAutoRange('x', False)
        self.plot_item.enableAutoRange('y', True)

        self.reset_xaxis_on_add = False

        self.measure_connect(prepared=self.measuringPrepared)

        self._updateCurves()

        # We configure first to your default values in case the channel
        # subscription adds data (some implementation may do) and then
        # reconfigure if necessary.
        self._configure()
        self.channel.subscribe(self)
        self._configure()

    def finalize(self):
        try:
            self.channel.unsubscribe(self)
        except AttributeError:
            pass

        super().finalize()

    def serialize(self):
        return self.raw_enabled, self.ma_enabled

    def sizeHint(self):
        return metro.QtCore.QSize(525, 225)

    def _configure(self):
        # This method has a rather awkward control flow, but I have yet
        # to find a better way without resorting to many more flags and
        # checks.
        # It basically will try to use a special configuration scheme if
        # the displayed channel is using STEP frequency and certain
        # conditions are met, such as being static or having a fixed set
        # of points. If this fails (as in did not return) we may fall
        # back to the same mechanism as for non-STEP channels)

        if self.has_metropc_tags:
            return

        if (self.channel is not None and
                self.channel.freq == self.channel.STEP_SAMPLES):
            meas = self.measure_getCurrent()

            if self.channel.isStatic():
                self.x_data = [int(x) for x in self.channel.step_values]
            elif meas is not None:
                self.x_data = meas.getPoints()

                if not self.x_data:
                    # meas.getPoints() will return an empty list if the
                    # point operator has no fixed set of points. But
                    # since we get a reference to the same structure as
                    # used by the measuring controller, it will fill up
                    # by itself. We just add a flag to correct the axis
                    # on each step.
                    self.reset_xaxis_on_add = True
                    return

            if self.x_data is not None:
                self.plot_item.setXRange(self.x_data[0], self.x_data[-1])
                self.displayed_points = len(self.x_data)
                return

        # We are only here if all of the above cases failed.

        self.x_data = numpy.arange(self.wave_points)+1
        self.plot_item.setXRange(1, self.wave_points)
        self.displayed_points = self.wave_points

    def _updateCurves(self):
        if self.raw_enabled and self.raw_curve is None:
            if self.mode == 'trendline':
                kwargs = dict(pen='y', symbol='s', symbolSize=5)
            elif self.mode == 'scatter':
                kwargs = dict(pen=None, symbol='o', symbolSize=4,
                              symbolBrush='#FADA5EA0')

            self.raw_curve = self.plot_item.plot(**kwargs)

        elif not self.raw_enabled and self.raw_curve is not None:
            self.plot_item.removeItem(self.raw_curve)
            self.raw_curve = None

        if self.ma_enabled and self.ma_curve is None:
            self.ma_curve = self.plot_item.plot(pen={'color': '#FFCC00A0',
                                                     'width': 5})

        elif not self.ma_enabled and self.ma_curve is not None:
            self.plot_item.removeItem(self.ma_curve)
            self.ma_curve = None

    @staticmethod
    def isChannelSupported(channel):
        return True

    @metro.QSlot()
    def measuringPrepared(self):
        self._configure()

    def dataSet(self, d):
        try:
            d = d[self.index]
        except TypeError:
            pass

        if d is None:
            self.dataCleared()
            return

        self.y_data = list(d)  # Make of copy

        self.ma_buffer.clear()
        self.ma_data.clear()

        for y in self.y_data:
            self.ma_buffer.append(y)
            self.ma_data.append(sum(self.ma_buffer) /
                                len(self.ma_buffer))

        if self.displayed_points > 0:
            self.raw_curve.setData(d[-self.displayed_points:])
        else:
            self.raw_curve.setData(d)

    def dataAdded(self, d):
        if d is None:
            return
        elif isinstance(d, xr.DataArray):
            y_label = d.attrs.get('ylabel', None) or ''
            if y_label != self.y_label:
                self.plot_item.setLabel('left', y_label)
                self.y_label = y_label

            d = float(d.data)

        try:
            d = d[self.index]
        except IndexError:
            pass
        except TypeError:
            pass

        if not numpy.isfinite(d):
            return

        try:
            self.y_data.append(d)
            self.ma_buffer.append(d)
        except TypeError:
            pass
        else:
            self.ma_data.append(sum(self.ma_buffer) / len(self.ma_buffer))

        if self.has_metropc_tags:
            self.x_data = self.channel._metropc_tags
            self.displayed_points = len(self.x_data)
            self.plot_item.setXRange(min(self.x_data), max(self.x_data))

        elif len(self.y_data) > len(self.x_data):
            # This happens for continuous channels that just filled the
            # chart, so we just extend our axis to the right.
            self.x_data += 1
            self.plot_item.setXRange(self.x_data[0], self.x_data[-1])

        elif self.reset_xaxis_on_add:
            # This flag is currently only set for STEP channels that do
            # not have a fixed point list.
            self.displayed_points = len(self.x_data)
            self.plot_item.setXRange(self.x_data[0], self.x_data[-1])

        if len(self.y_data) > 10*self.displayed_points:
            self.x_data = self.x_data[-2*self.displayed_points:]
            self.y_data = self.y_data[-2*self.displayed_points:]
            self.ma_data = self.ma_data[-2*self.displayed_points:]

        current_x = self.x_data[:min(self.displayed_points, len(self.y_data))]

        if self.raw_enabled:
            self.raw_curve.setData(current_x,
                                   self.y_data[-self.displayed_points:])

        if self.ma_enabled:
            self.ma_curve.setData(current_x,
                                  self.ma_data[-self.displayed_points:])

    def dataCleared(self):
        self.y_data.clear()
        self.ma_data.clear()

        if self.raw_enabled:
            self.raw_curve.setData(self.y_data)

        if self.ma_enabled:
            self.ma_curve.setData(self.ma_data)

    def subscriptionChanged(self, step_idx):
        if step_idx == metro.NumericChannel.CURRENT_STEP:
            self.displayed_points = self.wave_points
        else:
            self.displayed_points = -1

    # should be @metro.QSlot(metro.QtCore.QAction)
    def on_menuShowCurves_triggered(self, action):
        if action == self.actionEnableRaw:
            if self.raw_enabled == self.actionEnableRaw.isChecked():
                return

            self.raw_enabled = self.actionEnableRaw.isChecked()

        if action == self.actionEnableMA:
            if self.ma_enabled == self.actionEnableMA.isChecked():
                return

            self.ma_enabled = self.actionEnableMA.isChecked()

        self._updateCurves()
        self.dataAdded(None)

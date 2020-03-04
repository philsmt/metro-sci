
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import numpy

import metro
from metro.devices.abstract import single_plot


class Device(single_plot.Device, metro.DisplayDevice):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(shape=1)
    }

    descriptions = {
        '__main__': 'Displays histograms of 1d data sets sampled point by '
                    'point.',
        'channel': 'The channel to be displayed.'
    }

    def prepare(self, args, state):
        self.channel = args['channel']

        self.resize(525, 225)
        super().prepare(args, state, self.channel.name)

        self.addSubscriptionMenu()

        menu = self.plot_widget.getPlotItem().getViewBox().menu

        self.menuBinning = menu.addMenu('Binning')
        self.menuBinning.triggered.connect(self.on_menuBinning_triggered)
        self.groupBinning = metro.QtWidgets.QActionGroup(self.menuBinning)

        self.actionNoBinning = self.menuBinning.addAction('None')
        self.actionNoBinning.setData('__no_binning__')
        self.actionNoBinning.setCheckable(True)
        self.actionNoBinning.setChecked(True)
        self.groupBinning.addAction(self.actionNoBinning)

        self.actionDualBinning = self.menuBinning.addAction('2x')
        self.actionDualBinning.setData('__dual_binning__')
        self.actionDualBinning.setCheckable(True)
        self.groupBinning.addAction(self.actionDualBinning)

        self.actionQuadBinning = self.menuBinning.addAction('4x')
        self.actionQuadBinning.setData('__quad_binning__')
        self.actionQuadBinning.setCheckable(True)
        self.groupBinning.addAction(self.actionQuadBinning)

        self.actionCustomBinning = self.menuBinning.addAction('Custom...')
        self.actionCustomBinning.setData('__custom_binning__')
        self.actionCustomBinning.setCheckable(True)
        self.groupBinning.addAction(self.actionCustomBinning)

        self.dirty = False
        self.curve = self.plot_item.plot(pen='r')

        self.plot_item.enableAutoRange(x=False, y=True)
        self.plot_item.setMouseEnabled(x=True, y=False)

        if state is not None:
            self.x_range = state[0]
            bin_factor = state[1]

            if bin_factor == 2:
                self.actionDualBinning.setChecked(True)
            elif bin_factor == 4:
                self.actionQuadBinning.setChecked(True)
            elif bin_factor > 1:
                self.actionCustomBinning.setChecked(True)
        else:
            ch_range = self.channel.getRange()
            self.x_range = (ch_range
                            if ch_range[0] is not None
                            else (-600, 1000))

            bin_factor = 1

        self.plot_item.setXRange(self.x_range[0], self.x_range[1])
        self._setBinning(bin_factor)
        self.on_range_changed()

        self.draw_timer = metro.QTimer(self)
        self.draw_timer.setInterval(100)
        self.draw_timer.timeout.connect(self.on_draw_tick)

        self.measure_connect(prepared=self.draw_timer.start,
                             finalized=self.draw_timer.stop)

        self.range_timer = metro.QTimer(self)
        self.range_timer.setInterval(200)
        self.range_timer.setSingleShot(True)
        self.range_timer.timeout.connect(self.on_range_changed)
        self.plot_item.sigXRangeChanged.connect(self.on_plot_rangeChanged)

        meas = self.measure_getCurrent()

        if meas is not None:
            # If this device was created during a measurement, the
            # signal connections have not been made, so wire it up
            # by hand for the moment.

            self.draw_timer.start()
            meas.finalized.connect(self.draw_timer.stop)

        self.channel.listen(self)
        self.channel.subscribe(self)

    def finalize(self):
        try:
            self.channel.unlisten(self)
            self.channel.unsubscribe(self)
        except AttributeError:
            pass

        super().finalize()

    def serialize(self):
        return self.x_range, self.bin_factor

    def _setBinning(self, factor):
        self.bin_factor = factor

        if self.bin_factor > 1:
            self.bin_func = eval('lambda x: (x + {0})[::{1}]'.format(
                ' + '.join(['numpy.roll(x, {0})'.format(i)
                            for i in range(-1, -self.bin_factor, -1)]),
                self.bin_factor
            ))
        else:
            self.bin_func = lambda x: x

    @staticmethod
    def isChannelSupported(channel):
        if channel.shape != 1:
            raise ValueError('hist1d only supports 1d vector channels')

        return True

    def dataSet(self, d):
        if d is None:
            self.dataCleared()
            return

        d = d[d >= self.x[0]]
        d = d[d < self.x[-1]]

        bin_values = self.bin_func(numpy.bincount(d.astype(int) - self.x[0]))

        self.y[:] = 0
        self.y[:len(bin_values)] = bin_values

        self.curve.setData(self.x, self.y)

    def dataAdded(self, d):
        d = d[d >= self.x[0]]
        d = d[d < self.x[-1]]

        bin_values = self.bin_func(numpy.bincount(d.astype(int) - self.x[0]))

        self.y[:len(bin_values)] += bin_values

        self.dirty = True

    def dataCleared(self):
        self.y[:] = 0
        self.curve.setData([])

    @metro.QSlot()
    def on_draw_tick(self):
        if self.dirty:
            pass

        self.curve.setData(self.x, self.y)
        self.dirty = False

    def subscriptionChanged(self, step_idx):
        # Callback from abstract.single_plot
        pass

    @metro.QSlot(object, object)
    def on_plot_rangeChanged(self, viewbox, range_):
        self.x_range = range_
        self.range_timer.start()

    @metro.QSlot()
    def on_range_changed(self):
        self.x_range = (int(self.x_range[0]), int(self.x_range[1]))

        self.x = numpy.arange(self.x_range[0], self.x_range[1]+1,
                              self.bin_factor)
        self.y = numpy.zeros_like(self.x)
        self.dataSet(self.channel.getData())

    # Should be @metro.QSlot(metro.QtCore.QAction)
    def on_menuBinning_triggered(self, action):
        if action == self.actionNoBinning:
            new_factor = 1

        elif action == self.actionDualBinning:
            new_factor = 2

        elif action == self.actionQuadBinning:
            new_factor = 4

        elif action == self.actionCustomBinning:
            new_factor, success = metro.QtWidgets.QInputDialog.getInt(
                None, self.windowTitle(), 'Binning factor:',
                min=2, step=1, value=max(self.bin_factor, 2)
            )

            if not success:
                return

        else:
            return

        if new_factor != self.bin_factor:
            self._setBinning(new_factor)
            self.on_range_changed()


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import time

import metro

from metro.devices.abstract import async_operator


class Operator(async_operator.Operator):
    newRateData = metro.QSignal(int)
    newCountsData = metro.QSignal(int)

    def prepare(self, interval):
        self.timer = metro.QTimer(self)
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self.measuringTick)

    def _get(self):
        raise NotImplementedError('Operator._get')

    @metro.QSlot()
    def measuringStarted(self):
        self.step_counts = 0
        self.last_tick = 0

        self.timer.start()

    @metro.QSlot()
    def measuringTick(self):
        value = self._get()
        now = time.time()

        self.step_counts += value

        if self.last_tick > 0:
            elapsed = now - self.last_tick
            self.newRateData.emit(int(value / elapsed))

        self.last_tick = now

    @metro.QSlot()
    def measuringStopped(self):
        self.timer.stop()
        self.step_counts += self._get()

        self.newCountsData.emit(self.step_counts)


class Device(async_operator.WidgetDevice):
    def prepare(self, op_class, args, state):
        super().prepare(op_class, args, state)

        self.ch_rate = metro.NumericChannel(self, 'rate', shape=0,
                                            hint='waveform', freq='cont')

        self.ch_counts = metro.NumericChannel(self, 'counts', shape=0,
                                              hint='waveform', freq='step')

    def operatorReady(self, res):
        self.measure_connect(self.measuringStarted, self.measuringStopped)
        self.measure_connect(self.operator.measuringStarted,
                             self.operator.measuringStopped)

        self.operator.newRateData.connect(self.setRate)
        self.operator.newCountsData.connect(self.setCounts)

        self.displayStatus.setText('Standby')

    def finalize(self):
        super().finalize()

        self.ch_rate.close()
        self.ch_counts.close()

    @metro.QSlot()
    def measuringStarted(self):
        self.displayStatus.setText('Measuring')

    @metro.QSlot()
    def measuringStopped(self):
        self.displayStatus.setText('Standby')

    @metro.QSlot(int)
    def setRate(self, value):
        self.ch_rate.addData(value)
        self.displayRate.setText(str(value))

    @metro.QSlot(int)
    def setCounts(self, value):
        self.ch_counts.addData(value)
        self.displayCounts.setText(str(value))

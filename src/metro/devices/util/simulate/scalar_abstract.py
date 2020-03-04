
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import random

import metro
from metro.devices.abstract import async_operator


class Operator(async_operator.Operator):
    newData = metro.QSignal(float)

    def prepare(self, args):
        self.amplitude = args['amplitude']
        self.offset = args['offset']

        self.timer = metro.QTimer(self)
        self.timer.setInterval(args['interval'] * 1000)
        self.timer.timeout.connect(self.tick)

    def finalize(self):
        pass

    @metro.QSlot()
    def tick(self):
        r = self.amplitude * random.random() + self.offset
        self.newData.emit(r)


class Device(async_operator.WidgetDevice):
    arguments = {
        'amplitude': 100.0,
        'offset': 0.0,
        'interval': 3.0,
    }

    def prepare(self, args, state):
        self.channel = metro.NumericChannel(self, 'samples', shape=0,
                                            hint='waveform', freq='cont')

        super().prepare(Operator, args, state)

        self.total_samples = 0

        random.seed()

    def finalize(self):
        super().finalize()

        self.channel.close()

    def operatorReady(self, res):
        self.operator.newData.connect(self.newData)

        self.measure_connect(self.measuringStarted, self.measuringStopped)
        self.measure_connect(self.operator.timer.start,
                             self.operator.timer.stop)

    @metro.QSlot()
    def measuringStarted(self):
        self.displayStatus.setText('Measuring')

    @metro.QSlot()
    def measuringStopped(self):
        self.displayStatus.setText('Not measuring')

        self.total_samples = 0

    @metro.QSlot(float)
    def newData(self, r):
        self.channel.addData(r)

        self.total_samples += 1
        self.displaySamples.setText(str(self.total_samples))

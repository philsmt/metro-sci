
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import random

import numpy

import metro


class Device(metro.WidgetDevice):
    def prepare(self, args, state):
        self.ch_pos = metro.NumericChannel(self, 'pos', shape=2,
                                           hint='histogram', freq='cont')

        self.ch_time = metro.NumericChannel(self, 'time', shape=1,
                                            hint='histogram', freq='cont')

        self.ch_rate = metro.NumericChannel(self, 'rate', shape=0,
                                            hint='waveform', freq='cont')

        self.ch_counts = metro.NumericChannel(self, 'counts', shape=0,
                                              hint='waveform', freq='step')

        self.timer = metro.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

        self.measure_connect(prepared=self.measuringPrepared,
                             started=self.measuringStarted,
                             stopped=self.measuringStopped)
        self.measure_connect(self.timer.start, self.timer.stop)

        self.total_samples = 0
        self.last_sec_samples = 0
        self.iteration = 0

    def finalize(self):
        self.ch_pos.close()
        self.ch_time.close()
        self.ch_rate.close()
        self.ch_counts.close()

    @metro.QSlot()
    def measuringPrepared(self):
        points = self.measure_getCurrent().getPoints()

        # Set the offset per step to create a step-unique picture
        if len(points) > 1:
            self.cur_offset = -0.4
            self.offset_per_step = 0.8/(len(points)-1)
            self.amplitude = 0.04
        else:
            self.cur_offset = 0
            self.offset_per_step = 0
            self.amplitude = 0.1

    @metro.QSlot()
    def measuringStarted(self):
        self.displayStatus.setText('Measuring')

    @metro.QSlot()
    def measuringStopped(self):
        self.displayStatus.setText('Not measuring')

        self.ch_counts.addData(float(self.total_samples))
        self.total_samples = 0

        self.cur_offset += self.offset_per_step

    @metro.QSlot()
    def tick(self):
        n_samples = random.randint(500, 1500)

        self.ch_pos.addData(
            (self.amplitude * numpy.random.randn(n_samples, 2) +
             0.5 + self.cur_offset)
        )

        self.ch_time.addData(
            (1000 * (numpy.random.randn(n_samples) + 5)).astype(int)
        )

        self.total_samples += n_samples
        self.last_sec_samples += n_samples
        self.displaySamples.setText(str(self.total_samples))

        self.iteration += 1

        if self.iteration == 10:
            self.ch_rate.addData(float(self.last_sec_samples))
            self.last_sec_samples = 0
            self.iteration = 0

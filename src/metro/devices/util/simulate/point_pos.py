
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import numpy

import metro


class Device(metro.WidgetDevice):
    def prepare(self, args, state):
        self.ch_pos = metro.NumericChannel(self, 'pos', shape=2,
                                           hint='histogram', freq='cont')

        self.timer = metro.QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.on_tick)

        self.measure_connect(self.timer.start, self.timer.stop)

        n_samples = 1
        self.sample = numpy.ones((n_samples, 2)) * (0.2, 0.7)

    def finalize(self):
        self.ch_pos.close()

    @metro.QSlot()
    def on_tick(self):
        self.ch_pos.addData(self.sample.copy())

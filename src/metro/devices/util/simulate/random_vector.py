
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import random
import numpy

import metro


class Device(metro.CoreDevice):
    arguments = {
        'min_shape': 5,
        'max_shape': 50
    }

    def prepare(self, args, state):
        self.channel = metro.NumericChannel(
            self, 'test', shape=1, hint='indicator', freq='cont',
            buffering=False, transient=True
        )

        self.min_shape = args['min_shape']
        self.max_shape = args['max_shape']

        self.timer = metro.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.on_tick)

        self.measure_connect(started=self.timer.start, stopped=self.timer.stop)

    def finalize(self):
        self.channel.close()

    @metro.QSlot()
    def on_tick(self):
        self.channel.addData(numpy.random.rand(random.randint(
            self.min_shape, self.max_shape
        )))

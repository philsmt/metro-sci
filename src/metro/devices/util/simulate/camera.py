
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import numpy

import metro


class Device(metro.CoreDevice):
    arguments = {
        'rate': 10,
        'shape_x': 688,
        'shape_y': 512
    }

    def prepare(self, args, state):
        self.timerMeasure = metro.QTimer(self)
        self.timerMeasure.setInterval(1000 // args['rate'])
        self.timerMeasure.timeout.connect(self.on_tick)

        self.measure_connect(started=self.timerMeasure.start,
                             stopped=self.timerMeasure.stop)

        self.channel = metro.DatagramChannel(self, 'images', freq='cont',
                                             hint='indicator', compression=4)

        self.shape = (args['shape_x'], args['shape_y'])

    def finalize(self):
        self.channel.close()

    @metro.QSlot()
    def on_tick(self):
        self.channel.addData(numpy.random.randn(*self.shape))


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from random import random

import metro


class Device(metro.CoreDevice):
    def prepare(self, args, state):
        self.ch = metro.LogChannel(self, 'log', interval=5,
                                   fields=[('col0', 'f4'), ('col1', 'i4')])

        self.timer = metro.QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.on_timeout)
        self.timer.start()

    def finalize(self):
        self.timer.stop()

        self.ch.close()

    @metro.QSlot()
    def on_timeout(self):
        data = (random(), int(random()*1e6))
        self.ch.addData(*data)

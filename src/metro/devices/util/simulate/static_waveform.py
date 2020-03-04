
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import random

import metro


class Device(metro.CoreDevice):
    def prepare(self, args, state):
        self.channel = metro.NumericChannel(self, 'test', shape=0,
                                            hint='waveform', freq='cont')

        random.seed()

        for i in range(35):
            self.channel.addData(random.randint(1000, 1000000))

    def finalize(self):
        self.channel.close()

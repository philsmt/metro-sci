
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import numpy

import metro


class Device(metro.CoreDevice):
    arguments = {
        'channel': metro.ChannelArgument(shape=1)
    }

    def prepare(self, args, state):
        self.current_idx = 0
        self.y_shape = -1
        self.x = None
        self.mtx = None

        self.ch_out = metro.DatagramChannel(self, 'mtx', hint='indicator',
                                            freq='step', transient=True)
        self.ch_out.hintDisplayArgument('display.image.scale_to_fit', True)

        self.ch_in = args['channel']
        self.ch_in.subscribe(self)

        self.measure_connect(prepared=self.measuringPrepared)

    def finalize(self):
        self.ch_in.unsubscribe(self)
        self.ch_out.close()

    def measuringPrepared(self):
        meas = self.measure_getCurrent()

        self.x = meas.getPoints()

        if self.x is None:
            self.x = numpy.arange(100)

        self.current_idx = 0
        self.y_shape = -1

    def dataSet(self, data):
        pass

    def dataAdded(self, spec):
        if self.y_shape == -1:
            self.y_shape = len(spec)
            self.mtx = numpy.zeros((len(self.x), self.y_shape))
        else:
            if len(spec) != self.y_shape:
                print('Row mismatch, ignoring step')
                return

        self.mtx[self.current_idx, :] = spec

        if self.current_idx < len(self.x)-1:
            self.current_idx += 1
        else:
            self.current_idx = 0

        self.ch_out.addData(self.mtx)

    def dataCleared(self):
        pass

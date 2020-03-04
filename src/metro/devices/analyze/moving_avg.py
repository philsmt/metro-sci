
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import numpy

import metro


class Device(metro.CoreDevice):
    arguments = {
        'channel': metro.ChannelArgument(),
        'index': metro.IndexArgument(),
        'n_samples': 50,
    }

    def prepare(self, args, state):
        self.index = args['index']
        self.n_samples = args['n_samples']
        self.buf = None
        self.prev = None
        self.i = 0

        self.ch_in = args['channel']

        self.ch_out = metro.DatagramChannel(self, 'out',
                                            freq=self.ch_in.freq,
                                            hint=self.ch_in.hint,
                                            transient=True)
        self.ch_out.hintDisplayArgument('__default__', 'display.fast_plot')

        self.ch_in.subscribe(self)

        self.measure_connect(started=self.measuringStarted)

    def finalize(self):
        self.ch_in.unsubscribe(self)
        self.ch_out.close()

    def measuringStarted(self):
        self.dataCleared()

    def dataAdded(self, data):
        data = data[self.index]

        if self.buf is None or self.buf.shape[1] != data.shape[0]:
            self.buf = numpy.zeros((self.n_samples, data.shape[0]),
                                   dtype=data.dtype)
            self.prev = numpy.zeros_like((data.shape[0],), dtype=data.dtype)

        diff = data - self.prev
        self.buf[self.i] = diff
        self.prev = data.copy()
        self.i += 1

        if self.i == self.n_samples:
            self.i = 0

        self.ch_out.addData(self.buf.sum(axis=0))

    def dataCleared(self):
        if self.buf is not None:
            self.buf[:] = 0
            self.prev[:] = 0

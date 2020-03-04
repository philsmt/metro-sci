
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import numpy

import metro

from metro.devices.abstract import projection


def floatNonNegative(s):
    x = float(s)

    if x < 0.0:
        raise ValueError('only non-negative numbers allowed')

    return x


class Device(projection.Device):
    arguments = {
        'tag': 'time',
        'offset': 0.0,
        'lower_limit': 0.0,
        'upper_limit': 1000.0
    }
    arguments.update(projection.Device.arguments)

    descriptions = {
        '__main__': 'A simple projection device that limits a 1D channel of '
                    'samples to a fixed window after applying an offset.',
        'tag': 'Tag to use for the output channel'
    }

    def prepare(self, args, state):
        self.editOffset.setTypeCast(float)
        self.editLowerLimit.setTypeCast(floatNonNegative)
        self.editUpperLimit.setTypeCast(floatNonNegative)

        if state is not None:
            self.offset, self.lower, self.upper = state
        else:
            self.offset = args['offset']
            self.lower = args['lower_limit']
            self.upper = args['upper_limit']

        self.editOffset.setText(str(self.offset))
        self.editLowerLimit.setText(str(self.lower))
        self.editUpperLimit.setText(str(self.upper))

        super().prepare(args, None, args['tag'], 1)

    def serialize(self):
        return self.offset, self.lower, self.upper

    def _process(self, rows):
        times = rows[:, -1] + self.offset
        times = times[numpy.greater_equal(times, self.lower)]
        times = times[numpy.less_equal(times, self.upper)]

        return times

    def _update(self):
        self.ch_out.setRange(self.lower, self.upper)

        super()._update()

    @metro.QSlot(object)
    def on_editOffset_valueChanged(self, value):
        self.offset = value
        self._update()

    @metro.QSlot(object)
    def on_editLowerLimit_valueChanged(self, value):
        self.lower = value
        self._update()

    @metro.QSlot(object)
    def on_editUpperLimit_valueChanged(self, value):
        self.upper = value
        self._update()

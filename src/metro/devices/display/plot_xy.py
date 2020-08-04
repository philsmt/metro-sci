
# Copyright 2019 Philipp Schmidt <phil.smt@gmail.com>.
# All Rights Reserved.
#
# This file is part of the METRO measurement environment and may not be
# copied and/or distributed via any medium without the express
# permission of the author.

import numpy as np

import metro

from metro.devices.display import plot


class Device(plot.Device):
    def prepare(self, args, state):
        super().prepare(args, state)
        self.buffer = dict()

    def dataAdded(self, d):

        #  d = d[self.index, :]

        self.buffer[d[0, 0]] = d[0, 1]
        self.items = np.array(list(self.buffer.items()))
#        print(self.items)

        if len(self.items) <= 1:
            x = self.items[:, 0]
            y = self.items[:, 1]
        else:
            items = self.items[self.items[:, 0].argsort(axis=0)]
            x = items[:, 0]
            y = items[:, 1]

#        y = list()
#        for i in x:
#            y.append(self.buffer[i])

        self.curve.setData(x, y, autoDownsample=False, antialias=False)
        self._notifyFittingCallbacks(x, y)

    @staticmethod
    def isChannelSupported(channel):
        if isinstance(channel, metro.StreamChannel) and channel.shape != 2:
            raise ValueError('plot only supports StreamChannel in 2d')

        return True


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import numpy

import metro
from metro.devices.abstract import single_plot, fittable_plot


class Device(single_plot.Device, metro.DisplayDevice, fittable_plot.Device):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(),
        'steps': False,
        'index': metro.IndexArgument(allow_scalar=True),
        'bg_text': ''
    }

    descriptions = {
        '__main__': 'Displays the last channel value as y data of a plot',
        'channel': 'The channel to be displayed.',
        'steps': 'Plot as steps.',
        'index': 'Only display part of a channel',
        'bg_text': 'Initial background text, chosen automatically if empty.'
    }

    def prepare(self, args, state):
        self.channel = args['channel']
        self.index = args['index']

        if args['bg_text']:
            bg_text = args['bg_text']
        else:
            bg_text = self.channel.name

            if args['index'] != metro.IndexArgument.fullIndex:
                bg_text += '/' + metro.IndexArgument._index2str(args['index'])

        super().prepare(args, state, bg_text)

        self.plot_item.enableAutoRange('x', True)

        if args['steps']:
            self.curve = self.plot_item.plot([0], [], stepMode=True, pen='y')
            self.x_len_offset = 1
            self.x_val_offset = -0.5
        else:
            self.curve = self.plot_item.plot(
                pen=(180, 180, 255), symbol='s', symbolSize=3,
                symbolPen=(0, 0, 200)
            )
            self.x_len_offset = 0
            self.x_val_offset = 0
            self.plot_item.showGrid(x=True, y=False, alpha=0.4)

        self.channel.subscribe(self)

        self.fit_curves = {}

    def finalize(self):
        try:
            self.channel.unsubscribe(self)
        except AttributeError:
            pass

        super().finalize()

    def sizeHint(self):
        return metro.QtCore.QSize(525, 225)

    @staticmethod
    def isChannelSupported(channel):
        if isinstance(channel, metro.StreamChannel) and channel.shape != 1:
            raise ValueError('plot only supports StreamChannel in 1d')

        return True

    def dataSet(self, d):
        pass

    def dataAdded(self, d):
        d = d[self.index]

        x = numpy.arange(len(d) + self.x_len_offset) + self.x_val_offset

        self.curve.setData(x, d, autoDownsample=False, antialias=False)
        self._notifyFittingCallbacks(x, d)

    def dataCleared(self):
        self.curve.setData([])

    def addFittedCurve(self, tag, x, y):
        try:
            curve = self.fit_curves[tag]
        except KeyError:
            curve = self.plot_item.plot(pen={'color': 'y', 'width': 2})
            self.fit_curves[tag] = curve

        curve.setData(x, y)

    def removeFittedCurve(self, tag):
        try:
            curve = self.fit_curves[tag]
        except KeyError:
            pass
        else:
            self.plot_item.removeItem(curve)
            del self.fit_curves[tag]

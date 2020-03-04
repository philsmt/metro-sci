
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro


class Device(metro.WidgetDevice):
    arguments = {
        'interval': 1000.0
    }

    descriptions = {
        '__main__': 'My first device!',
        'interval': 'Time interval in ms at which samples are generated.'
    }

    def prepare(self, args, state):
        self.channel = metro.NumericChannel(self, 'value', freq='cont',
                                            shape=0, hint='waveform')

        self.timer = metro.QTimer(self)
        self.timer.setInterval(args['interval'])
        self.timer.timeout.connect(self.tick)

        self.measure_connect(self.timer.start, self.timer.stop)

        if state is not None:
            self.editValue.setValue(state)

    def finalize(self):
        self.channel.close()

    def serialize(self):
        return self.editValue.value()

    @metro.QSlot()
    def tick(self):
        value = self.editValue.value()

        self.channel.addData(value)

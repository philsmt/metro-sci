
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro


class Device(metro.WidgetDevice, metro.ScanOperator):
    ready = metro.QSignal()

    def prepare(self, args, state):
        self.measure_addOperator('scan', 'virtual', self)

    def prepareScan(self):
        return self.step, self.ready

    @metro.QSlot(float)
    def step(self, value):
        self.displayStep.setText(str(value))

        self.ready.emit()

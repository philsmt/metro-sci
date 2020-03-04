
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro


class Device(metro.WidgetDevice, metro.TriggerOperator, metro.LimitOperator):
    def prepare(self, args, state):
        self.measure_addOperator('scan', 'manual', self)
        self.measure_addOperator('trigger', 'manual', self)
        self.measure_addOperator('limit', 'manual', self)

    def finalize(self):
        self.measure_removeOperator('scan', 'manual')
        self.measure_removeOperator('trigger', 'manual')
        self.measure_removeOperator('limit', 'manual')

    def prepareScan(self):
        return self.activateScan, self.buttonScan.clicked

    def finalizeScan(self):
        self.buttonScan.setEnabled(False)

    def prepareTrigger(self):
        return self.activateTrigger, self.buttonTrigger.clicked

    def finalizeTrigger(self):
        self.buttonTrigger.setEnabled(False)

    def prepareLimit(self):
        return self.activateLimit, self.buttonLimit.clicked, None, 0

    def finalizeLimit(self):
        self.buttonLimit.setEnabled(False)

    @metro.QSlot()
    def activateScan(self):
        self.buttonScan.setEnabled(True)

    @metro.QSlot()
    def on_buttonScan_clicked(self):
        self.buttonScan.setEnabled(False)

    @metro.QSlot()
    def activateTrigger(self):
        self.buttonTrigger.setEnabled(True)

    @metro.QSlot()
    def on_buttonTrigger_clicked(self):
        self.buttonTrigger.setEnabled(False)

    @metro.QSlot()
    def activateLimit(self):
        self.buttonLimit.setEnabled(True)

    @metro.QSlot()
    def on_buttonLimit_clicked(self):
        self.buttonLimit.setEnabled(False)

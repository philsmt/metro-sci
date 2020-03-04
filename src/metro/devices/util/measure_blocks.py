
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro


class Device(metro.WidgetDevice):
    def prepare(self, args, tate):
        self._updateRefcounts()

    def _updateRefcounts(self):
        self.displayRunCount.setText(str(metro.RunBlock.refcount))
        self.displayStepCount.setText(str(metro.StepBlock.refcount))

    @metro.QSlot(str)
    def on_labelRunBlock_linkActivated(self, link):
        self._updateRefcounts()

    @metro.QSlot(str)
    def on_labelStepBlock_linkActivated(self, link):
        self._updateRefcounts()

    @metro.QSlot()
    def on_buttonRunAcquire_clicked(self):
        metro.RunBlock.acquire()
        self._updateRefcounts()

    @metro.QSlot()
    def on_buttonRunRelease_clicked(self):
        metro.RunBlock.release()
        self._updateRefcounts()

    @metro.QSlot()
    def on_buttonStepAcquire_clicked(self):
        metro.StepBlock.acquire()
        self._updateRefcounts()

    @metro.QSlot()
    def on_buttonStepRelease_clicked(self):
        metro.StepBlock.release()
        self._updateRefcounts()

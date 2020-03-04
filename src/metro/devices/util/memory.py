
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import gc

import metro


class Device(metro.WidgetDevice):
    def prepare(self, args, state):
        self.checkStats.toggled.connect(self.updateDebugMode)
        self.checkCollectable.toggled.connect(self.updateDebugMode)
        self.checkUncollectable.toggled.connect(self.updateDebugMode)
        self.checkSaveAll.toggled.connect(self.updateDebugMode)
        self.checkLeak.toggled.connect(self.updateDebugMode)

        if state is not None:
            gc.set_debug(state)

    def serialize(self):
        return gc.get_debug()

    @metro.QSlot(bool)
    def updateDebugMode(self, flag):
        mode = 0

        if self.checkStats.isChecked():
            mode |= gc.DEBUG_STATS

        if self.checkCollectable.isChecked():
            mode |= gc.DEBUG_COLLECTABLE

        if self.checkUncollectable.isChecked():
            mode |= gc.DEBUG_UNCOLLECTABLE

        if self.checkSaveAll.isChecked():
            mode |= gc.DEBUG_SAVEALL

        if self.checkLeak.isChecked():
            mode |= gc.DEBUG_LEAK

        gc.set_debug(mode)

        print('Set GC debug mode to', mode)

    @metro.QSlot()
    def on_buttonCollect_clicked(self):
        unreachable_objects = gc.collect()

        print('gc.collect() returned: ', unreachable_objects)

    @metro.QSlot()
    def on_buttonPrintDebug_clicked(self):
        print(gc.get_debug())

    @metro.QSlot()
    def on_buttonPrintCounts_clicked(self):
        print(gc.get_count())

    @metro.QSlot()
    def on_buttonPrintGarbage_clicked(self):
        print(gc.garbage)


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import os

from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5 import uic as QtUic

import metro
from metro import devices


class SaveProfileDialog(QtWidgets.QDialog):
    def __init__(self, profiles):
        super().__init__()

        QtUic.loadUi(metro.resource_filename(
            __name__, 'profiles_save.ui'), self)

        self.setWindowTitle(f'Save profile - {metro.WINDOW_TITLE}')

        for profile in profiles:
            self.editName.addItem(os.path.basename(profile)[:-5])

        self.editName.lineEdit().setText('')

        device_list = sorted(devices.getAll(), key=lambda x: x.getDeviceName())

        for device in device_list:
            device_item = QtWidgets.QListWidgetItem(device.getDeviceName(),
                                                    self.listDevices)
            self.listDevices.addItem(device_item)

            device_item.setSelected(True)

        channels_list = sorted(metro.getAllChannels(), key=lambda x: x.name)

        for channel in channels_list:
            if not (hasattr(channel, '_custom') or
                    hasattr(channel, '_replayed')):
                continue

            channel_item = QtWidgets.QListWidgetItem(channel.name,
                                                     self.listChannels)

            self.listChannels.addItem(channel_item)

            channel_item.setSelected(True)

    def getPath(self):
        return '{0}/{1}.json'.format(
            metro.PROFILE_PATH, self.editName.currentText())

    def saveAsProfile(self):
        profile = metro.app.saveProfile(
            self.getPath(),
            [item.text() for item in self.listDevices.selectedItems()],
            [item.text() for item in self.listChannels.selectedItems()],
            use_meas_params=self.checkMeasParams.isChecked(),
            use_ctrlw_geometry=self.checkControlWindowGeometry.isChecked(),
            use_devw_geometries=self.checkDeviceWindowGeometries.isChecked()
        )

        metro.app.last_used_profile = [self.editName.currentText(),
                                       self.getPath(), profile]

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        if not self.editName.currentText():
            QtWidgets.QMessageBox.critical(self, self.windowTitle(),
                                           'Please enter a profile name.')
            return

        if self.editName.currentText().startswith('_'):
            QtWidgets.QMessageBox.critical(self, self.windowTitle(),
                                           'Profiles may not begin with two '
                                           'underscores.')

        if os.path.isfile(self.getPath()):
            res = QtWidgets.QMessageBox.question(
                self, self.windowTitle(),
                'A profile with that name already exists. Overwrite?'
            )

            if res == QtWidgets.QMessageBox.No:
                return

        self.accept()

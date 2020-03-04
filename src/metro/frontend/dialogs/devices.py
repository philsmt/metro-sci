
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from PyQt5 import QtCore
from PyQt5 import QtWidgets

import metro
from metro.frontend import arguments


# Dialog for name and other arguments of new devices
class NewDeviceDialog(arguments.ConfigurationDialog):
    def __init__(self, name, device_class, initial_values):
        descriptions = device_class.descriptions

        additional_rows = []

        if '__main__' in descriptions:
            labelDesc = QtWidgets.QLabel(descriptions['__main__'])
            labelDesc.setWordWrap(True)

            additional_rows.append(labelDesc)

        self.editName = QtWidgets.QLineEdit(name)
        self.editName.selectAll()

        additional_rows.append((QtWidgets.QLabel('name'), self.editName))

        super().__init__(device_class.arguments, initial_values,
                         descriptions, additional_rows)

        # We save the initial to bypass the banned characters later
        self.default_name = name

        self.setWindowTitle(f'New device - {metro.WINDOW_TITLE}')

    def _validate(self):
        name = self.editName.text()

        if not name:
            metro.app.showError('The device name is malformed:',
                                'Empty string')
            return False

        if name != self.default_name and any(c in name for c in '!#$[]'):
            metro.app.showError('The device name is malformed:',
                                'The characters !, #, $, [ and ] are not '
                                'allowed.')
            return False

        return True

    def getName(self):
        return self.editName.text()


class DeviceArgumentsDialog(QtWidgets.QDialog):
    def __init__(self, device):
        super().__init__()

        self.setWindowTitle(f'Arguments of {device._name} - '
                            f'{metro.WINDOW_TITLE}')

        layout = QtWidgets.QGridLayout(self)
        layout.setHorizontalSpacing(20)
        layout.setVerticalSpacing(8)

        current_row = 0

        for key, value in device._args.items():
            layout.addWidget(QtWidgets.QLabel('<i>{0}</i>'.format(key)),
                             current_row, 0)
            layout.addWidget(QtWidgets.QLabel(str(value)), current_row, 1)

            current_row += 1

        self.buttonBox = QtWidgets.QDialogButtonBox(self)
        self.buttonBox.addButton(QtWidgets.QDialogButtonBox.Ok)

        self.buttonBox.accepted.connect(self.accept)

        layout.addWidget(self.buttonBox, current_row, 0, 1, 2,
                         QtCore.Qt.AlignRight)

        self.setLayout(layout)

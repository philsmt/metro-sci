
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from serial.tools.list_ports import comports

import metro


class SerialPortArgument(metro.ComboBoxArgument):
    def __init__(self, default=None):
        super().__init__()

        self.default = default

    def dialog_prepare(self, parent, value=None):
        if value is None:
            value = self.default

        return super().dialog_prepare(parent, [port[0] for port in comports()],
                                      True, value)

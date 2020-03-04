
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro
from metro.interfaces import serial_aux


class Device(metro.WidgetDevice):
    arguments = {
        'index': metro.IndexArgument('1:3'),
        'tupleA': (1, 2, 3),
        'listB': [4, 5, 6],
        'port': serial_aux.SerialPortArgument(),
        'device': metro.DeviceArgument(optional=True),
        'operator': metro.OperatorArgument('scan', optional=True),
        'channel': metro.ChannelArgument(optional=True)
    }

    def prepare(self, args, state):
        print(args)

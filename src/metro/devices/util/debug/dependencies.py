
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro


class Device(metro.CoreDevice):
    arguments = {
        'deviceA': metro.DeviceArgument(optional=False),
        'deviceB': metro.DeviceArgument(optional=True)
    }

    def prepare(self, args, state):
        print(args)

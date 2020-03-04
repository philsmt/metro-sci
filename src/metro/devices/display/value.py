
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro


class Device(metro.WidgetDevice, metro.DisplayDevice):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(),
        'func': ('str', 'repr', 'pprint')
    }

    descriptions = {
        '__main__': 'Displays the stringified value of the last sample set or '
                    'added to almost any channel.',
        'channel': 'The channel to be displayed.',
        'func': 'The function applied to the value to be displayed that '
                'generates the string representation.'
    }

    def prepare(self, args, state):
        self.labelDisplay = metro.QtWidgets.QLabel('<no value>')
        self.labelDisplay.setMinimumWidth(175)
        self.labelDisplay.setAlignment(metro.QtCore.Qt.AlignHCenter)
        self.labelDisplay.setSizePolicy(
            metro.QtWidgets.QSizePolicy.Expanding,
            metro.QtWidgets.QSizePolicy.Expanding
        )

        # main layout
        layout = metro.QtWidgets.QVBoxLayout()
        layout.addWidget(self.labelDisplay)
        self.setLayout(layout)

        if args['func'] == 'str':
            self.display_func = str
        elif args['func'] == 'repr':
            self.display_func = repr
        elif args['func'] == 'pprint':
            import pprint

            pretty_printer = pprint.PrettyPrinter(indent=4)
            self.display_func = pretty_printer.pformat

        self.channel = args['channel']
        self.channel.subscribe(self)

    def finalize(self):
        self.channel.unsubscribe(self)

    def dataSet(self, d):
        self.labelDisplay.setText(self.display_func(d[-1]))

    def dataAdded(self, d):
        self.labelDisplay.setText(self.display_func(d))

    def dataCleared(self):
        self.labelDisplay.setText('<cleared>')

    @staticmethod
    def isChannelSupported(channel):
        return True

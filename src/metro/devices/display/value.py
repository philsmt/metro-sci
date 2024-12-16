
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro


class Device(metro.WidgetDevice, metro.DisplayDevice):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(),
        'func': ('str', 'repr', 'pprint', 'ndshape'),
        'scaling': True
    }

    descriptions = {
        '__main__': 'Displays the stringified value of the last sample set or '
                    'added to almost any channel.',
        'channel': 'The channel to be displayed.',
        'func': 'The function applied to the value to be displayed that '
                'generates the string representation.',
        'scaling': 'Whether to scale font size to window width.'
    }

    def prepare(self, args, state):
        self.scaling = args['scaling']

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

            pretty_printer = pprint.PrettyPrinter(indent=4, sort_dicts=False)
            self.display_func = pretty_printer.pformat
        elif args['func'] == 'ndshape':
            self.display_func = lambda x: str(x.shape)

        self.channel = args['channel']
        self.channel.subscribe(self)

    def _set_text(self, text=None):
        if text is not None:
            self._current_text = text

        if self.scaling:
            font = self.labelDisplay.font()
            fm = self.labelDisplay.fontMetrics()
            label_width = self.labelDisplay.size().width()

            text_width = fm.horizontalAdvance(self._current_text)
            fraction = text_width / label_width

            if fraction < 0.8 or fraction > 1.0:
                font.setPointSize(int(font.pointSize() / fraction * 0.9))
                self.labelDisplay.setFont(font)

        self.labelDisplay.setText(self._current_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_text()

    def finalize(self):
        self.channel.unsubscribe(self)

    def dataSet(self, d):
        self._set_text(self.display_func(d[-1]))

    def dataAdded(self, d):
        self._set_text(self.display_func(d))

    def dataCleared(self):
        self._set_text('<cleared>')

    @staticmethod
    def isChannelSupported(channel):
        return True

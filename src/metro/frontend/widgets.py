
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from collections import OrderedDict

from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets

import metro


class LinksLabel(QtWidgets.QLabel):
    contextRequested = QtCore.pyqtSignal(str, QtCore.QPoint)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setWordWrap(True)
        self.setContextMenuPolicy(QtCore.Qt.NoContextMenu)

        self.links = OrderedDict()
        self.labels = {}
        self.active_link = None

        self.linkHovered.connect(self.on_linkHovered)

    def _update(self):
        self.setText(', '.join(self.links.values()))

    def __len__(self):
        return len(self.labels)

    def setLink(self, link, label):
        self.labels[link] = label
        self.formatLink(link)

    def getLabel(self, link):
        return self.labels[link]

    def formatLink(self, link, color='#0057AE',
                   bold=False, italic=False, underlined=True):

        css = ("color: {0}; "
               "font-weight: {1}; "
               "font-style: {2}; "
               "text-decoration: {3}").format(
            color,
            'bold' if bold else 'normal',
            'italic' if italic else 'normal',
            'underline' if underlined else 'none'
        )

        html = '<a href="{0}" style="{1}">{2}</a>'.format(link, css,
                                                          self.labels[link])

        self.links[link] = html
        self._update()

    def removeLink(self, link):
        del self.links[link]
        del self.labels[link]

        self._update()

    def clearLinks(self):
        self.links.clear()
        self.labels.clear()

        self._update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.RightButton and self.active_link:
            self.contextRequested.emit(self.active_link, event.globalPos())

    @QtCore.pyqtSlot(str)
    def on_linkHovered(self, link):
        self.active_link = link


class ChannelLinksLabel(LinksLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.channels = {}

        self.linkActivated.connect(self.on_linkActivated)
        self.contextRequested.connect(self.on_contextRequested)

    def setContextMenu(self, menu):
        self.menuContext = menu

    def addChannel(self, channel, label=None, entry_point=None, args={},
                   **kwargs):
        if label is None:
            label = channel.name

        self.setLink(label, label)

        if len(kwargs) > 0:
            self.formatLink(label, **kwargs)

        self.channels[label] = (channel.name, entry_point, args)

    def removeChannel(self, label):
        if isinstance(label, metro.AbstractChannel):
            labels = []

            channel = label
            for key, value in self.channels.items():
                if value[0] == channel.name:
                    labels.append(key)

            for label in labels:
                self.removeChannel(label)

        else:
            self.removeLink(label)
            del self.channels[label]

    @metro.QSlot(str)
    def on_linkActivated(self, link):
        try:
            entry = self.channels[link]
        except KeyError as e:
            metro.app.showError(
                'An error occured on creating a display device:',
                'No channel known with label {0}'.format(link), e
            )
        else:
            metro.app.createDisplayDevice(metro.getChannel(entry[0]),
                                          entry_point=entry[1],
                                          args=entry[2])

    @metro.QSlot(str, QtCore.QPoint)
    def on_contextRequested(self, link, menu_pos):
        try:
            self.menuContext
        except AttributeError:
            self.menuContext = ChannelLinkMenu()

        try:
            entry = self.channels[link]
        except KeyError as e:
            metro.app.showError(
                'An error occured on creating a channel context menu:',
                'No channel known with label {0}'.format(link), e
            )
        else:
            self.menuContext.buildForChannel(*entry)
            self.menuContext.popup(menu_pos)


class LabelableMenu(QtWidgets.QMenu):
    def setTitle(self, text):
        super().setTitle(text)

        if len(self.actions()) == 0:
            # We have to recreate this every time since on clear() it
            # will get destroyed apparently
            self.addLabel(text)

    def addLabel(self, text):
        label = QtWidgets.QLabel(text, self)
        label.setMargin(5)

        action = QtWidgets.QWidgetAction(self)
        action.setDefaultWidget(label)

        self.addAction(action)


class ChannelLinkMenu(LabelableMenu):
    # Has to be initialized externally, usually by the main controller
    menuDisplayBy = None

    def __init__(self, title=None, parent=None):
        super().__init__(title, parent)

        self.menuDisplayBy = QtWidgets.QMenu(self)

        self.triggered.connect(self.on_triggered)

    def buildForChannel(self, channel, entry_point=None, args={}):
        if isinstance(channel, str):
            # Compatibility with old API
            channel = metro.getChannel(channel)

        self.entry_point = entry_point
        self.args = args

        self.clear()
        self.setTitle(channel.name)

        self.addSeparator()

        self.addAction('Display...').setData('__default__')

        try:
            self.addMenu(ChannelLinkMenu.menuDisplayBy).setText(
                'Display by...'
            )
        except AttributeError:
            # Apparently the menu was never initialized
            pass

        if isinstance(channel, metro.StreamChannel):
            self.addAction('Display raw...').setData('__raw__')

        self.addSeparator()

        # If this is a custom channel...
        if hasattr(channel, '_custom'):
            edit_action = self.addAction('Edit...')
            edit_action.setData('__edit__')

            if channel.locked:
                edit_action.setEnabled(False)

            self.addSeparator()

        # ...or replayed
        elif hasattr(channel, '_replayed'):
            self.addAction('Close').setData('__close__')
            self.addSeparator()

        if isinstance(channel, metro.NumericChannel):
            self.addAction('Duplicate...').setData('__duplicate__')

        self.addAction(
            'Clear current step'
        ).setData('__clear__')
        self.addAction('Reset').setData('__reset__')

    # see note in controller regarding decorator on such slots
    def on_triggered(self, action):
        channel = metro.getChannel(self.title())
        name = action.data()

        if name is None:
            # Happens on the "header" label
            return

        elif name == '__raw__':
            metro.app.displayRawChannel(channel)

        elif name == '__edit__':
            metro.app.editCustomChannel(channel)

        elif name == '__close__':
            channel.close()

        elif name == '__duplicate__':
            value, success = metro.QtWidgets.QInputDialog.getText(
                None, f'Duplicate channel - {metro.WINDOW_TITLE}',
                'Please enter the a name for the duplicated channel:'
            )

            if not success:
                return

            try:
                new_chan = metro.NumericChannel(
                    '@'+value, hint=channel.hint, freq=channel.freq,
                    shape=channel.shape, static=True
                )
            except ValueError as e:
                metro.app.showError('An error occured on creating the '
                                    'channel.', str(e), details=e)
                return

            new_chan.copyDataFrom(channel)

        elif name == '__clear__':
            channel.clearData()

        elif name == '__reset__':
            res = QtWidgets.QMessageBox.warning(
                self, f'Reset channel - {metro.WINDOW_TITLE}',
                'Are you sure to reset this channel?\nThis operation puts the '
                'channel in the same state as immediately after creation. '
                'Performing this action during a measurement can lead to '
                'undefined behaviour.\n\nIf you were looking to just empty '
                'the current channel buffers, please use "Clear current step" '
                'instead.',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )

            if res == QtWidgets.QMessageBox.Yes:
                channel.reset()

        else:
            if name == '__default__':
                name = self.entry_point

            metro.app.createDisplayDevice(channel, name, show_dialog=True,
                                          args=self.args)


class PythonHighlighter(QtGui.QSyntaxHighlighter):
    """
    Syntax highlighter for the Python language.

    Heavily based on examples from wiki.python.org for PyQt4
    """

    # Helper function
    def _makeFormat(color_str, bold=False, italic=False):
        """
        Return a QTextCharFormat with the given attributes.
        """
        color = QtGui.QColor()
        color.setNamedColor(color_str)

        text_format = QtGui.QTextCharFormat()
        text_format.setForeground(color)

        if bold:
            text_format.setFontWeight(QtGui.QFont.Bold)
        if italic:
            text_format.setFontItalic(True)

        return text_format

    # Styles
    styles = {
        'keyword':  _makeFormat('blue'),
        'operator': _makeFormat('red'),
        'brace':    _makeFormat('darkGray'),
        'defclass': _makeFormat('black', bold=True),
        'string':   _makeFormat('magenta'),
        'string2':  _makeFormat('darkMagenta'),
        'comment':  _makeFormat('darkGreen', italic=True),
        'self':     _makeFormat('black', italic=True),
        'numbers':  _makeFormat('brown'),
    }

    # Python keywords
    keywords = [
        'and', 'assert', 'break', 'class', 'continue', 'def', 'del', 'elif',
        'else', 'except', 'exec', 'finally', 'for', 'from', 'global', 'if',
        'import', 'in', 'is', 'lambda', 'not', 'or', 'pass', 'print', 'raise',
        'return', 'try', 'while', 'yield', 'None', 'True', 'False'
    ]

    # Python operators
    operators = [
        '=',
        '==', '!=', '<', '<=', '>', '>=',  # Comparison
        '\+', '-', '\*', '/', '//', '\%', '\*\*',  # Arithmetic
        '\+=', '-=', '\*=', '/=', '\%=',  # In-place
        '\^', '\|', '\&', '\~', '>>', '<<',  # Bitwise
    ]

    # Python braces
    braces = [
        '\{', '\}', '\(', '\)', '\[', '\]',
    ]

    def __init__(self, document):
        super().__init__(document)

        # Multi-line strings (expression, flag, style)
        # FIXME: The triple-quotes in these two lines will mess up
        # the syntax highlighting from this point onward
        self.tri_single = (QtCore.QRegExp("'''"), 1, self.styles['string2'])
        self.tri_double = (QtCore.QRegExp('"""'), 2, self.styles['string2'])

        rules = []

        # Keyword, operator, and brace rules
        rules += [(r'\b%s\b' % w, 0, self.styles['keyword'])
                  for w in self.keywords]
        rules += [(r'%s' % o, 0, self.styles['operator'])
                  for o in self.operators]
        rules += [(r'%s' % b, 0, self.styles['brace'])
                  for b in self.braces]

        # All other rules
        rules += [
            # 'self'
            (r'\bself\b', 0, self.styles['self']),

            # Double-quoted string, possibly containing escape
            # sequences
            (r'"[^"\\]*(\\.[^"\\]*)*"', 0, self.styles['string']),
            # Single-quoted string, possibly containing escape
            # sequences
            (r"'[^'\\]*(\\.[^'\\]*)*'", 0, self.styles['string']),

            # 'def' followed by an identifier
            (r'\bdef\b\s*(\w+)', 1, self.styles['defclass']),
            # 'class' followed by an identifier
            (r'\bclass\b\s*(\w+)', 1, self.styles['defclass']),

            # From '#' until a newline
            (r'#[^\n]*', 0, self.styles['comment']),

            # Numeric literals
            (r'\b[+-]?[0-9]+[lL]?\b', 0, self.styles['numbers']),
            (r'\b[+-]?0[xX][0-9A-Fa-f]+[lL]?\b', 0, self.styles['numbers']),
            (r'\b[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\b', 0,
             self.styles['numbers']),
        ]

        # Build a QRegExp for each pattern
        self.rules = [(QtCore.QRegExp(pat), index, fmt)
                      for (pat, index, fmt) in rules]

    def highlightBlock(self, text):
        """Apply syntax highlighting to the given block of text.
        """
        # Do other syntax formatting
        for expression, nth, format in self.rules:
            index = expression.indexIn(text, 0)

            while index >= 0:
                # We actually want the index of the nth match
                index = expression.pos(nth)
                length = len(expression.cap(nth))
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

        self.setCurrentBlockState(0)

        # Do multi-line strings
        in_multiline = self.match_multiline(text, *self.tri_single)
        if not in_multiline:
            in_multiline = self.match_multiline(text, *self.tri_double)

    def match_multiline(self, text, delimiter, in_state, style):
        """
        Do highlighting of multi-line strings. ``delimiter`` should
        be a ``QRegExp`` for triple-single-quotes or triple-double-
        quotes, and ``in_state`` should be a unique integer to
        represent the corresponding state changes when inside those
        strings. Returns True if we're still inside a multi-line
        string when this function is finished.
        """
        # If inside triple-single quotes, start at 0
        if self.previousBlockState() == in_state:
            start = 0
            add = 0
        # Otherwise, look for the delimiter on this line
        else:
            start = delimiter.indexIn(text)
            # Move past this match
            add = delimiter.matchedLength()

        # As long as there's a delimiter match on this line...
        while start >= 0:
            # Look for the ending delimiter
            end = delimiter.indexIn(text, start + add)
            # Ending delimiter on this line?
            if end >= add:
                length = end - start + add + delimiter.matchedLength()
                self.setCurrentBlockState(0)
            # No; multi-line string
            else:
                self.setCurrentBlockState(in_state)
                length = len(text) - start + add
            # Apply formatting
            self.setFormat(start, length, style)
            # Look for the next match
            start = delimiter.indexIn(text, start + length)

        # Return True if still inside a multi-line string, False
        # otherwise
        if self.currentBlockState() == in_state:
            return True
        else:
            return False


class ParameterLineEdit(QtWidgets.QLineEdit):
    valueChanged = metro.QSignal(object)

    # Should raise ValueError on error
    @staticmethod
    def defaultFunction(x):
        return x

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._function = ParameterLineEdit.defaultFunction

        self.textEdited.connect(self._on_textEdited)
        self.returnPressed.connect(self._on_returnPressed)

    def _setWidgetModified(self, flag):
        font = self.font()
        font.setItalic(flag)
        self.setFont(font)

    def setTypeCast(self, func):
        self._function = func

    def setText(self, new_text):
        super().setText(new_text)
        self._setWidgetModified(False)

    @QtCore.pyqtSlot(str)
    def _on_textEdited(self, text):
        self._setWidgetModified(True)

    @QtCore.pyqtSlot()
    def _on_returnPressed(self):
        try:
            value = self._function(self.text())
        except ValueError:
            pass
        else:
            self._setWidgetModified(False)
            self.valueChanged.emit(value)


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import collections
import os.path
import types

from PyQt5 import QtCore
from PyQt5 import QtWidgets

import metro


class AbstractArgument(object):
    def serialize(self, value):
        return str(value)

    def restore(self, value):
        return value

    def dialog_prepare(self, parent, value=None):
        raise NotImplementedError('dialog_prepare')

    def dialog_finalize(self):
        raise NotImplementedError('dialog_finalize')

    def dialog_bypass(self):
        return None

    def dialog_validate(self):
        pass


class BuiltinArgument(AbstractArgument):
    def __init__(self, widget, get_func):
        self.widget = widget
        self.get_func = get_func

    def dialog_prepare(self, parent, value=None):
        return self.widget

    def dialog_finalize(self):
        value = self.get_func()
        self.widget = None

        return value


class ConstantArgument(AbstractArgument):
    def __init__(self, value):
        self.value = value

    def dialog_prepare(self, parent, value=None):
        self.widget = QtWidgets.QLabel(parent)
        self.widget.setText('<i>constant</i>')

        return self.widget

    def dialog_finalize(self):
        self.widget = None

        return self.value


class SequenceArgument(AbstractArgument):
    def __init__(self, seq):
        self.seq = seq

    def dialog_prepare(self, parent, value=None):
        self.widget = QtWidgets.QComboBox(parent)
        self.widget.setEditable(isinstance(self.seq, list))

        for v in self.seq:
            self.widget.addItem(str(v))

        if value is not self.seq:
            idx = self.widget.findText(value, QtCore.Qt.MatchExactly)

            if idx != -1:
                self.widget.setCurrentIndex(idx)

        return self.widget

    def dialog_finalize(self):
        if isinstance(self.seq, list):
            text = self.widget.currentText()

            if len(self.seq) == 0:
                res = text
            elif isinstance(self.seq[0], int):
                res = int(text)
            elif isinstance(self.seq[0], float):
                res = float(text)
            else:
                res = text
        else:
            res = self.seq[self.widget.currentIndex()]

        self.widget = None
        return res


class IndexArgument(AbstractArgument):
    fullIndex = slice(None, None, 1)

    def __init__(self, default='', allow_scalar=True):
        self.default = default
        self.allow_scalar = allow_scalar

    @staticmethod
    def _str2slice(in_str):
        parts = in_str.split(':')
        n_parts = len(parts)

        try:
            if n_parts == 2:
                start = int(parts[0]) if parts[0] else None
                stop = int(parts[1]) if parts[1] else None
                step = 1

            elif n_parts == 3:
                start = int(parts[0]) if parts[0] else None
                stop = int(parts[1]) if parts[1] else None
                step = int(parts[2]) if parts[2] else 1

            else:
                raise ValueError()

        except ValueError:
            raise ValueError('Malformed slice expression')

        return slice(start, stop, step)

    @staticmethod
    def _str2expr(in_str):
        try:
            return eval(in_str)
        except SyntaxError:
            raise ValueError('Malformed sequence expression')

    @staticmethod
    def _str2index(in_str, allow_scalar=True):
        in_str = in_str.strip()

        if not in_str:
            return IndexArgument.fullIndex
        elif ':' in in_str:
            return IndexArgument._str2slice(in_str)
        elif in_str[0] == '(' and in_str[-1] == ')':
            return IndexArgument._str2expr(in_str)
        elif in_str[0] == '[' and in_str[-1] == ']':
            return IndexArgument._str2expr(in_str)
        else:
            if allow_scalar:
                return IndexArgument._str2expr('{0}'.format(in_str))
            else:
                return slice(int(in_str), int(in_str)+1, 1)

    @staticmethod
    def _index2str(in_idx):
        if isinstance(in_idx, slice):
            if in_idx.start is None and in_idx.stop is None:
                return ''

            elif in_idx.step == 1:
                return '{0}:{1}'.format(
                    in_idx.start if in_idx.start is not None else '',
                    in_idx.stop if in_idx.stop is not None else '',
                )

            else:
                return '{0}:{1}:{2}'.format(
                    in_idx.start if in_idx.start is not None else '',
                    in_idx.stop if in_idx.stop is not None else '',
                    in_idx.step if in_idx.step is not None else ''
                )

        else:
            return str(in_idx)

    def serialize(self, value):
        return IndexArgument._index2str(value)

    def restore(self, value):
        return IndexArgument._str2index(value, self.allow_scalar)

    def dialog_prepare(self, parent, value=None):
        self.widget = QtWidgets.QLineEdit(parent)

        if value is None:
            value = self.default

        self.widget.setText(str(value))

        return self.widget

    def dialog_finalize(self):
        text = self.widget.text()
        self.widget = None

        return IndexArgument._str2index(text, self.allow_scalar)

    def dialog_validate(self):
        # May throw ValueError if malformed
        IndexArgument._str2index(self.widget.text(), self.allow_scalar)

    def dialog_bypass(self):
        return IndexArgument.fullIndex


class ComboBoxArgument(AbstractArgument):
    def dialog_prepare(self, parent, entries, editable=True, value=None):
        self.widget = QtWidgets.QComboBox(parent)
        self.widget.setEditable(editable)

        if isinstance(entries, dict):
            for name, value in entries.items():
                self.widget.addItem(name, value)
        else:
            for entry in entries:
                self.widget.addItem(entry, entry)

        if value is not None:
            idx = self.widget.findText(value, QtCore.Qt.MatchExactly)

            if idx != -1:
                self.widget.setCurrentIndex(idx)

        return self.widget

    def dialog_finalize(self):
        orig_text = self.widget.itemText(self.widget.currentIndex())

        if self.widget.currentText() == orig_text:
            text = self.widget.currentData()
        else:
            text = self.widget.currentText()

        self.widget.clear()
        self.widget = None

        return text


class DeviceArgument(ComboBoxArgument):
    def __init__(self, device_module='', optional=False):
        self.device_module = device_module
        self.optional = optional

    def serialize(self, value):
        return value._name

    def restore(self, value):
        if value is not None:
            return metro.getDevice(value)

    def dialog_prepare(self, parent, value=None):
        sel_names = []

        for dev in metro.getAllDevices():
            if dev >= self.device_module:
                sel_names.append(str(dev))

        if self.optional and len(sel_names) > 0:
            sel_names.insert(0, '')

        return super().dialog_prepare(parent, sel_names, False)

    def dialog_finalize(self):
        dev_name = super().dialog_finalize()

        try:
            d = metro.getDevice(dev_name)
        except KeyError:
            d = None

        return d

    def dialog_validate(self):
        if self.optional:
            return

        device_name = self.widget.currentText()

        if not device_name:
            raise ValueError('No device given for non-optional argument')

        try:
            metro.getDevice(device_name)
        except KeyError:
            raise ValueError('Could not find device "{0}"'.format(device_name))


class ChannelArgument(AbstractArgument):
    class Proxy(metro.AbstractChannel):
        defaultProperties = dict(
            mode=metro.AbstractChannel.DIRECT_MODE,
            hint=metro.AbstractChannel.UNKNOWN_HINT,
            freq=metro.AbstractChannel.CONTINUOUS_SAMPLES
        )

        def __init__(self, channel_name):
            self.channel_name = channel_name
            self.channel = None
            self.recorded_calls = []

            metro.channels.watch(self)

            # Do NOT call the constructor of AbstractChannel, as we
            # want to look like a channel, but not act like one.

        def __getattr__(self, key):
            if self.channel is not None:
                return getattr(self.channel, key)
            else:
                if key in self.defaultProperties:
                    return self.defaultProperties[key]

                raise AttributeError(key)

        def channelOpened(self, channel):
            if self.channel_name == channel.name:
                self.channel = channel

                for method, args, kwargs in self.recorded_calls:
                    getattr(self.channel, method)(*args, **kwargs)

                self.recorded_calls.clear()

        def channelClosed(self, channel_name):
            pass

        def close(self):
            if self.channel is not None:
                self.channel.close()
                self.channel = None

            self.recorded_calls.clear()

        def checked(func):
            method = func.__name__

            def wrap(self, *args, **kwargs):
                if self.channel is not None:
                    return getattr(self.channel, method)(*args, **kwargs)
                else:
                    return func(self, *args, **kwargs)

        def recorded(func):
            method = func.__name__

            def wrap(self, *args, **kwargs):
                if self.channel is None:
                    self.recorded_calls.append((method, args, kwargs))
                    return func(self, *args, **kwargs)
                else:
                    return getattr(self.channel, method)(*args, **kwargs)

            return wrap

        @checked
        def dependsOn(self):
            return False

        @checked
        def isStatic(self):
            return False

        @checked
        def reset(self):
            if self.channel is not None:
                self.channel.reset()

        @checked
        def getStepCount(self):
            return 0

        @checked
        def getSubscribedStep(self, obj):
            return 0

        @checked
        def hintDisplayArgument(self, *args, **kwargs):
            raise RuntimeError('read-only proxy')

        @checked
        def hintDisplayArguments(self, *args, **kwargs):
            raise RuntimeError('read-only proxy')

        @checked
        def setHeaderTag(self, *args, **kwargs):
            raise RuntimeError('read-only proxy')

        @checked
        def getData(self, step_index):
            return None

        @checked
        def setData(self, *args, **kwargs):
            raise RuntimeError('read-only proxy')

        @checked
        def addData(self, *args, **kwargs):
            raise RuntimeError('read-only proxy')

        @checked
        def clearData(self, *args, **kwargs):
            raise RuntimeError('read-only proxy')

        @recorded
        def listen(self, *args, **kwargs):
            pass

        @recorded
        def unlisten(self, *args, **kwargs):
            pass

        @recorded
        def subscribe(self, *args, **kwargs):
            pass

        @recorded
        def setSubscribedStep(self, *args, **kwargs):
            pass

        @recorded
        def unsubscribe(self, *args, **kwargs):
            pass

    def __init__(self, default=None, hint=None, freq=None, type_=None,
                 shape=None, optional=False, proxied=False):
        self.default = default.name if default is not None else ''

        self.hint = hint
        self.freq = freq
        self.type_ = type_
        self.shape = shape
        self.optional = optional
        self.proxied = proxied

    def serialize(self, value):
        if isinstance(value, ChannelArgument.Proxy):
            return value.channel_name
        else:
            return value.name

    def restore(self, value):
        if value is not None:
            try:
                obj = metro.getChannel(value)
            except KeyError as e:
                if self.proxied:
                    obj = ChannelArgument.Proxy(value)
                else:
                    raise e from None

            return obj

    def dialog_prepare(self, parent, value=None):
        self.widget = QtWidgets.QWidget(parent)

        self.editChannel = QtWidgets.QLineEdit(self.widget)

        if value is None:
            value = self.default
        elif isinstance(value, metro.AbstractChannel):
            value = value.name
        elif isinstance(value, str):
            pass
        else:
            raise ValueError('invalid type of value argument')

        self.editChannel.setText(value)

        self.buttonFindChannel = QtWidgets.QPushButton(self.widget)
        self.buttonFindChannel.setIcon(parent.style().standardIcon(
            QtWidgets.QStyle.SP_DirOpenIcon
        ))

        # Be careful, this is not a QObject and therefore may not have
        # methods as slots.
        self.buttonFindChannel.clicked.connect(QtCore.pyqtSlot()(
            lambda: self._editChannelArgument(self)
        ))

        self.layout = QtWidgets.QHBoxLayout(self.widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.editChannel)
        self.layout.addWidget(self.buttonFindChannel)

        self.widget.setLayout(self.layout)

        return self.widget

    @staticmethod
    def _editChannelArgument(self):
        new_channel = metro.app.findChannelByDialog(
            selected_channel=self.editChannel.text(), hint=self.hint,
            freq=self.freq, type_=self.type_, shape=self.shape
        )

        if new_channel is not None:
            self.editChannel.setText(new_channel.name)

    def dialog_finalize(self):
        try:
            ch = metro.getChannel(self.editChannel.text())
        except KeyError:
            ch = None

        self.editChannel = None
        self.buttonFindChannel = None
        self.layout = None
        self.widget = None

        return ch

    def dialog_validate(self):
        if self.optional:
            return

        channel_name = self.editChannel.text()

        if not channel_name:
            raise ValueError('No channel given')

        try:
            metro.getChannel(channel_name)
        except KeyError:
            raise ValueError('Could not find channel "{0}"'.format(
                channel_name
            ))


class OperatorArgument(ComboBoxArgument):
    def __init__(self, type_, optional=False):
        self.type_ = type_
        self.optional = optional

    def serialize(self, value):
        for name, obj in metro.getAllOperators(self.type_).items():
            if obj == value:
                op_name = name
                break

        # Will raise NameError if not existing
        return (self.type_, op_name)

    def restore(self, value):
        if value is not None:
            return metro.getOperator(*value)

    def dialog_prepare(self, parent, value=None):
        op_names = metro.getAllOperators(self.type_).keys()

        if self.optional and len(op_names) > 0:
            op_names = list(op_names)
            op_names.insert(0, '')

        return super().dialog_prepare(parent, op_names, False, value)

    def dialog_finalize(self):
        op_name = super().dialog_finalize()

        try:
            op = metro.getOperator(self.type_, op_name)
        except KeyError:
            op = None

        return op

    def dialog_validate(self):
        if not self.optional and not self.widget.currentText():
            raise ValueError('No operator given')


class FileArgument(AbstractArgument):
    def __init__(self, filter_='', root='./', optional=False):
        self.filter_ = filter_
        self.root = root
        self.optional = optional

    def dialog_prepare(self, parent, value=None):
        self.widget = QtWidgets.QWidget(parent)

        self.editPath = QtWidgets.QLineEdit(self.widget)
        self.editPath.setText(self.root)

        self.buttonBrowse = QtWidgets.QPushButton(self.widget)
        self.buttonBrowse.setIcon(parent.style().standardIcon(
            QtWidgets.QStyle.SP_DirOpenIcon
        ))

        # Be careful, this is not a QObject and therefore may not have
        # methods as slots.
        self.buttonBrowse.clicked.connect(QtCore.pyqtSlot()(
            lambda: self._browse(self)
        ))

        self.layout = QtWidgets.QHBoxLayout(self.widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.editPath)
        self.layout.addWidget(self.buttonBrowse)

        self.widget.setLayout(self.layout)

        return self.widget

    @staticmethod
    def _browse(self):
        last_dir = self.root

        if self.editPath.text():
            last_dir = os.path.dirname(self.editPath.text())

        new_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.widget, f'Select file - {metro.WINDOW_TITLE}',
            directory=last_dir, filter=self.filter_
        )

        if new_path:
            self.editPath.setText(new_path)

    def dialog_finalize(self):
        path = self.editPath.text()

        self.editPath = None
        self.buttonBrowse = None
        self.layout = None
        self.widget = None

        return path

    def dialog_validate(self):
        if not self.optional and not os.path.isfile(self.editPath.text()):
            raise ValueError('File not found')


class ConfigurationDialog(QtWidgets.QDialog):
    def __init__(self, arguments, initial_values={}, descriptions={},
                 additional_rows=[]):
        super().__init__()

        self.final_args = None

        layout = QtWidgets.QGridLayout(self)

        current_row = 0

        for row in additional_rows:
            if isinstance(row, tuple):
                layout.addWidget(row[0], current_row, 0)
                layout.addWidget(row[1], current_row, 1)
            else:
                layout.addWidget(row, current_row, 0, 1, 2)

            current_row += 1

        self.args_objs, current_row = ConfigurationDialog.buildLayout(
            self, layout, current_row, arguments, descriptions,
            initial_values
        )

        self.buttonBox = QtWidgets.QDialogButtonBox(self)
        self.buttonBox.addButton(QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.addButton(QtWidgets.QDialogButtonBox.Cancel)

        self.buttonBox.accepted.connect(self.on_buttonBox_accepted)
        self.buttonBox.rejected.connect(self.reject)

        layout.addWidget(self.buttonBox, current_row, 0, 1, 2,
                         QtCore.Qt.AlignRight)

        self.setLayout(layout)

    @staticmethod
    def buildLayout(parent, layout, current_row, arguments, descriptions,
                    initial_values={}, alignment_key=0, alignment_value=0):
        sorted_args = collections.OrderedDict(sorted(arguments.items()))
        args_objs = {}

        for name, value in sorted_args.items():
            layout.addWidget(QtWidgets.QLabel(name, parent), current_row, 0,
                             1, 1, QtCore.Qt.AlignmentFlag(alignment_key))

            try:
                initial_value = initial_values[name]
            except KeyError:
                initial_value = None

            if not isinstance(value, metro.AbstractArgument):
                if initial_value is None:
                    initial_value = value

                if value is None:
                    value = BuiltinArgument(QtWidgets.QLabel(parent),
                                            lambda: None)

                elif isinstance(value, bool):
                    # Always check for bool before int!
                    widget = QtWidgets.QCheckBox(parent)
                    widget.setChecked(initial_value)

                    value = BuiltinArgument(widget, widget.isChecked)

                elif isinstance(value, int):
                    widget = QtWidgets.QSpinBox(parent)
                    widget.setRange(-2**31, 2**31-1)
                    widget.setValue(initial_value)

                    value = BuiltinArgument(widget, widget.value)

                elif isinstance(value, float):
                    widget = QtWidgets.QLineEdit(parent)
                    widget.setText(str(initial_value))

                    value = BuiltinArgument(
                        widget, types.MethodType(
                            lambda self: float(self.text()), widget
                        )
                    )

                elif isinstance(value, str):
                    widget = QtWidgets.QLineEdit(parent)
                    widget.setText(initial_value)

                    value = BuiltinArgument(widget, widget.text)

                elif isinstance(value, list) or isinstance(value, tuple):
                    value = SequenceArgument(value)

                else:
                    value = ConstantArgument(value)

            args_objs[name] = value

            current_widget = value.dialog_prepare(parent, initial_value)
            layout.addWidget(current_widget, current_row, 1, 1, 1,
                             QtCore.Qt.AlignmentFlag(alignment_value))

            try:
                current_widget.setToolTip('<font>{0}</font>'.format(
                    descriptions[name]
                ))
            except KeyError:
                pass

            current_row += 1

        return args_objs, current_row

    def getArgs(self):
        if self.final_args is None:
            self.final_args = {}

            for name, arg in self.args_objs.items():
                self.final_args[name] = arg.dialog_finalize()

        return self.final_args

    def _validate(self):
        return True

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        for name, arg in self.args_objs.items():
            try:
                arg.dialog_validate()
            except AttributeError:
                pass
            except ValueError as e:
                metro.app.showError('The argument "{0}" is '
                                    'malformed:'.format(name), str(e))
                return

        if self._validate():
            self.accept()

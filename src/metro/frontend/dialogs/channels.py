
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import time
from importlib import resources

import numpy  # noqa
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5 import uic as QtUic

import metro
from metro.frontend import widgets


class EditNormalizedChannelDialog(QtWidgets.QDialog):
    def __init__(self, channel=None):
        super().__init__()

        self.channel = channel

        ui_source = resources.files(__name__).joinpath(
            'channels_edit_normalized.ui')
        with resources.as_file(ui_source) as ui_path:
            QtUic.loadUi(ui_path, self)

        self.buttonDiscard = self.buttonBox.button(
            QtWidgets.QDialogButtonBox.Discard
        )
        self.buttonDiscard.clicked.connect(self.on_buttonBox_discarded)

        if self.channel is not None:
            try:
                name_to_normalize = self.channel._custom_to_normalize
                names_normalize_by = self.channel._custom_normalize_by
            except AttributeError:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'Could not find custom '
                                    'channel properties of normalized '
                                    'channels.')
                self.reject()
                return

            if self.channel.locked:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'The channel is currently '
                                    'locked.')
                # We can go on after this, since there is another check
                # on accepting the dialog.

            own_name = self.channel.name

            self.editName.setText(self.channel.name[1:])
            self.editName.setReadOnly(True)
        else:
            self.buttonDiscard.setEnabled(False)

            own_name = ''
            name_to_normalize = ''
            names_normalize_by = []

            self.labelScriptedEdit.setText('')

        channels_list = [metro.getChannel(x) for x in
                         sorted(metro.queryChannels(hint='waveform'))]

        for channel in channels_list:
            if channel.name == own_name:
                continue

            channel_item = QtWidgets.QListWidgetItem(channel.name,
                                                     self.listToNormalize)

            self.listToNormalize.addItem(channel_item)

            if channel.name == name_to_normalize:
                channel_item.setSelected(True)

            channel_item = QtWidgets.QListWidgetItem(channel.name,
                                                     self.listNormalizeBy)

            self.listNormalizeBy.addItem(channel_item)

            if channel.name in names_normalize_by:
                channel_item.setSelected(True)

    @QtCore.pyqtSlot(str)
    def on_labelScriptedEdit_linkActivated(self, link):
        if self.channel is None:
            return

        res = QtWidgets.QMessageBox.warning(
            self, f'Edit as scripted channel - {metro.WINDOW_TITLE}',
            'This action will turn this channel into a scripted channel. It '
            'will not be possible to edit it as a normalized channel again. '
            'Are you sure you want to continue?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        normalize_by = [metro.getChannel(x) for x
                        in self.channel._custom_normalize_by]

        self.channel._custom_arg_variables = ['n'+str(i) for i
                                              in range(len(normalize_by))]
        self.channel._custom_arg_variables.insert(0, 'x')

        by_strs = ['n'+str(i) for i in range(len(normalize_by))]
        self.channel._custom_kernel_source = 'return x/({0})'.format(
            '*'.join(by_strs)
        )
        self.channel._custom_init_enabled = False
        self.channel._custom_init_source = ''
        self.channel._custom_init_object = None

        del self.channel._custom_to_normalize
        del self.channel._custom_normalize_by

        self.accept()
        metro.app.editCustomChannel(self.channel)

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        name = self.editName.text()

        if not name:
            metro.app.showError('An error occured with the entered data.',
                                'A channel name is required.')
            return

        to_normalize = metro.getChannel(
            self.listToNormalize.selectedItems()[0].text()
        )
        normalize_by = [metro.getChannel(item.text()) for item
                        in self.listNormalizeBy.selectedItems()]

        arg_channels = normalize_by.copy()
        arg_channels.insert(0, to_normalize)

        channel_freq = to_normalize.freq
        channel_shape = to_normalize.shape

        for ch in normalize_by:
            if ch.freq != channel_freq or ch.shape != channel_shape:
                metro.app.showError('An error occured with the entered data.',
                                    'The selected channels have different '
                                    'frequencies and/or shapes.')

        by_strs = ['n'+str(i) for i in range(len(normalize_by))]
        kernel_func = eval('lambda x,{0}: x/({1})'.format(','.join(by_strs),
                                                          '*'.join(by_strs)))

        if self.channel is not None:
            if self.channel.locked:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'The channel is currently '
                                    'locked.')
                return

            if self.channel.input_channels != arg_channels:
                self.channel.setDirect()
                self.channel.setComputing(kernel_func, arg_channels)
            else:
                self.chanel.kernel = kernel_func

            self.channel.setFrequency(channel_freq)
        else:
            try:
                channel = metro.NumericChannel('$'+name, hint='waveform',
                                               freq=channel_freq,
                                               shape=channel_shape)
            except ValueError as e:
                metro.app.showError('An error occured on creating the '
                                    'channel.', str(e))
                return

            channel._custom = True
            channel.setComputing(kernel_func, arg_channels)

            self.channel = channel

        self.channel._custom_to_normalize = to_normalize.name
        self.channel._custom_normalize_by = [x.name for x in normalize_by]

        self.accept()

    @QtCore.pyqtSlot()
    def on_buttonBox_discarded(self):
        if self.channel is None:
            return

        res = QtWidgets.QMessageBox.warning(
            self, f'Delete normalized channel - {metro.WINDOW_TITLE}',
            'Are you sure to delete this channel?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        self.channel.close()
        self.accept()


class EditStatisticsChannelDialog(QtWidgets.QDialog):
    kernel_sources = {
        'sum': 'numpy.sum(x, axis=0)',
        'mean': 'numpy.average(x, axis=0)',
        'median': 'numpy.median(x, axis=0)',
        'range': 'numpy.amax(x, axis=0) - numpy.amin(x, axis=0)',
        'variance': 'numpy.variance(x, axis=0)',
        'stdev': 'numpy.std(x, axis=0)'
    }

    kernel_descriptions = {
        'sum': 'The sum of all samples generated in one step',
        'mean': 'The mean of all samples generated in one step',
        'median': 'The median of all samples generated in one step',
        'range': 'The difference between the maximum and mimimum of all '
                 'samples generated in one step.',
        'variance': 'The squared deviation from the mean of all samples '
                    'generated in one step',
        'stdev': 'The square root of the variation'
    }

    def __init__(self, channel=None):
        super().__init__()

        self.channel = channel

        ui_source = resources.files(__name__).joinpath(
            'channels_edit_statistics.ui')
        with resources.as_file(ui_source) as ui_path:
            QtUic.loadUi(ui_path, self)

        self.buttonDiscard = self.buttonBox.button(
            QtWidgets.QDialogButtonBox.Discard
        )
        self.buttonDiscard.clicked.connect(self.on_buttonBox_discarded)

        if self.channel is not None:
            try:
                name_to_integrate = self.channel._custom_to_integrate
                func = self.channel._custom_func
            except AttributeError:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'Could not find custom '
                                    'channel properties of statistics '
                                    'channels.')
                self.reject()
                return

            if self.channel.locked:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'The channel is currently '
                                    'locked.')
                # We can go on after this, since there is another check
                # on accepting the dialog.

            own_name = self.channel.name

            self.editName.setText(self.channel.name[1:])
            self.editName.setReadOnly(True)

            self.selectFunc.setCurrentIndex(
                self.selectFunc.findText(func, QtCore.Qt.MatchExactly)
            )
        else:
            self.buttonDiscard.setEnabled(False)

            own_name = ''
            name_to_integrate = ''

            self.on_selectFunc_currentTextChanged('sum')

            self.labelScriptedEdit.setText('')

        channels_list = [metro.getChannel(x) for x in
                         sorted(metro.queryChannels(freq='continuous') +
                                metro.queryChannels(freq='scheduled'))]

        for channel in channels_list:
            if channel.name == own_name:
                continue

            channel_item = QtWidgets.QListWidgetItem(channel.name,
                                                     self.listToIntegrate)

            self.listToIntegrate.addItem(channel_item)

            if channel.name == name_to_integrate:
                channel_item.setSelected(True)

    @QtCore.pyqtSlot(str)
    def on_selectFunc_currentTextChanged(self, text):
        self.labelDesc.setText(
            '<b>{0}</b><br><br>Matrix-shaped channels are evaluated per '
            'column.'.format(self.kernel_descriptions[text])
        )

    @QtCore.pyqtSlot(str)
    def on_labelScriptedEdit_linkActivated(self, link):
        if self.channel is None:
            return

        res = QtWidgets.QMessageBox.warning(
            self, f'Edit as scripted channel - {metro.WINDOW_TITLE}',
            'This action will turn this channel into a scripted channel. It '
            'will not be possible to edit it as a statistics channel again. '
            'Are you sure you want to continue?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        self.channel._custom_arg_variables = ['x']
        self.channel._custom_kernel_source = 'return ' + self.kernel_sources[
            self.selectFunc.currentText()
        ]
        self.channel._custom_init_enabled = False
        self.channel._custom_init_source = ''
        self.channel._custom_init_object = None

        del self.channel._custom_to_integrate
        del self.channel._custom_func

        self.accept()
        metro.app.editCustomChannel(self.channel)

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        name = self.editName.text()

        if not name:
            metro.app.showError('An error occured with the entered data.',
                                'A channel name is required.')
            return

        to_integrate = metro.getChannel(
            self.listToIntegrate.selectedItems()[0].text()
        )

        kernel_func = eval(
            'lambda x: ' + self.kernel_sources[self.selectFunc.currentText()]
        )

        if self.channel is not None:
            if self.channel.locked:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'The channel is currently '
                                    'locked.')
                return

            if self.channel.input_channels != [to_integrate]:
                self.channel.setDirect()
                self.channel.setIntegrating(kernel_func, [to_integrate])
            else:
                self.channel.kernel = kernel_func
        else:
            try:
                channel = metro.NumericChannel('$'+name, hint='waveform',
                                               freq='step',
                                               shape=to_integrate.shape)
            except ValueError as e:
                metro.app.showError('An error occured on creating the '
                                    'channel.', str(e), details=e)
                return

            channel._custom = True
            channel.setIntegrating(kernel_func, [to_integrate])

            self.channel = channel

        self.channel._custom_to_integrate = to_integrate.name
        self.channel._custom_func = self.selectFunc.currentText()

        self.accept()

    @QtCore.pyqtSlot()
    def on_buttonBox_discarded(self):
        if self.channel is None:
            return

        res = QtWidgets.QMessageBox.warning(
            self, f'Delete scripted channel - {metro.WINDOW_TITLE}',
            'Are you sure to delete this channel?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        self.channel.close()
        self.accept()


class EditArgumentChannelDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        ui_source = resources.files(__name__).joinpath(
            'channels_edit_argument.ui')
        with resources.as_file(ui_source) as ui_path:
            QtUic.loadUi(ui_path, self)

        self.buttonFindChannel.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.SP_DirOpenIcon
        ))

        self.buttonDiscard = self.buttonBox.button(
            QtWidgets.QDialogButtonBox.Discard
        )
        self.buttonDiscard.clicked.connect(self.on_buttonBox_discarded)

    def getChannel(self):
        return metro.getChannel(self.editChannel.text())

    def getVariable(self):
        return self.editVariable.text()

    @QtCore.pyqtSlot()
    def exec_(self, channel_name='', variable_name='', own_name=''):
        self.editChannel.setText(channel_name)
        self.editVariable.setText(variable_name)

        self.own_name = own_name

        self.buttonDiscard.setEnabled(bool(channel_name))

        return super().exec_()

    @QtCore.pyqtSlot()
    def on_buttonFindChannel_clicked(self):
        ch = metro.app.findChannelByDialog(
            selected_channel=self.editChannel.text(),
            excluded_channels=[self.own_name]
        )

        if ch is not None:
            self.editChannel.setText(ch.name)

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        channel_name = self.editChannel.text()

        if not channel_name:
            metro.app.showError('An error occured with the entered data.',
                                'No channel specified.')
            return

        try:
            metro.getChannel(channel_name)
        except KeyError:
            metro.app.showError('An error occured with the entered data.',
                                'Could not find specified channel.')
            return

        variable_name = self.editVariable.text()

        if not variable_name:
            metro.app.showError('An error occured with the entered data.',
                                'No variable name specified.')
            return

        self.discard = False
        self.accept()

    # Do NOT use clicked(QAbstractButton) to catch this, since it
    # will trigger with the correct type and this again causes
    # pyqtgraph to not properly plot anything... there is some
    # crazy magic going on.
    @QtCore.pyqtSlot()
    def on_buttonBox_discarded(self):
        self.discard = True
        self.accept()


class EditScriptedChannelDialog(QtWidgets.QDialog):
    def __init__(self, channel=None):
        super().__init__()

        self.channel = channel

        self.kernel_object = None
        self.init_object = None

        ui_source = resources.files(__name__).joinpath(
            'channels_edit_scripted.ui')
        with resources.as_file(ui_source) as ui_path:
            QtUic.loadUi(ui_path, self)

        self.buttonDiscard = self.buttonBox.button(
            QtWidgets.QDialogButtonBox.Discard
        )
        self.buttonDiscard.clicked.connect(self.on_buttonBox_discarded)

        self.check_timer = QtCore.QTimer(self)
        self.check_timer.setSingleShot(True)
        self.check_timer.setInterval(250)
        self.check_timer.timeout.connect(self.on_check)

        self.editKernelCode.textChanged.connect(self.check_timer.start)
        self.editInitCode.textChanged.connect(self.check_timer.start)

        self.arg_dialog = EditArgumentChannelDialog(self)

        if self.channel is not None:
            try:
                self.arg_variables = self.channel._custom_arg_variables
            except AttributeError:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'Could not find custom '
                                    'channel properties of scripted channels.')
                self.reject()
                return

            if self.channel.locked:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'The channel is currently '
                                    'locked.')
                # We can go on after this, since there is another check
                # on accepting the dialog.

            self.editName.setText(self.channel.name[1:])
            self.editName.setReadOnly(True)

            if self.channel.mode == metro.AbstractChannel.COMPUTING_MODE:
                self.checkComputing.setChecked(True)
                self.mode_func = 'setComputing'
            elif self.channel.mode == metro.AbstractChannel.INTEGRATING_MODE:
                self.checkIntegrating.setChecked(True)
                self.mode_func = 'setIntegrating'
            else:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'The channel is neither '
                                    'in computing nor integrating mode.')
                self.reject()
                return

            self.checkBuffering.setChecked(self.channel.buffering)
            self.checkTransient.setChecked(self.channel.transient)
            self.selectHint.setCurrentIndex(self.channel.hint)
            self.selectFreq.setCurrentIndex(self.channel.freq)
            self.selectShape.setCurrentIndex(self.channel.shape)
            self.selectShape.setEnabled(False)

            # IMPORTANT: We need to make a copy here since we want to
            # modify it without confusing the channel itself.
            self.arg_channels = self.channel.input_channels.copy()

            self.editKernelCode.setPlainText(
                self.channel._custom_kernel_source
            )
            self.checkInitCode.setChecked(self.channel._custom_init_enabled)
            self.editInitCode.setPlainText(self.channel._custom_init_source)

            self._updateKernelDef()
        else:
            self.arg_variables = []
            self.arg_channels = []

            self.buttonDiscard.setEnabled(False)

            self.checkComputing.setChecked(True)
            self.mode_func = 'setComputing'

        self.non_integrating_freq = self.selectFreq.currentIndex()

        self.highlighter = widgets.PythonHighlighter(
            self.editKernelCode.document()
        )

        self.warning_str = None

    def _updateKernelDef(self):
        format_str = '<a href="#{0}">{0}</a>'

        self.labelKernelDef.setText('<b>def func({0}):'.format(', '.join(
            [format_str.format(key) for key in self.arg_variables]
        )))

        self.check_timer.start()

    @QtCore.pyqtSlot(bool)
    def on_checkComputing_toggled(self, flag):
        if flag:
            self.selectFreq.setEnabled(True)
            self.selectFreq.setCurrentIndex(self.non_integrating_freq)

            self.mode_func = 'setComputing'

            self.check_timer.start()

    @QtCore.pyqtSlot(bool)
    def on_checkIntegrating_toggled(self, flag):
        if flag:
            self.non_integrating_freq = self.selectFreq.currentIndex()

            self.selectFreq.setCurrentIndex(1)
            self.selectFreq.setEnabled(False)

            self.mode_func = 'setIntegrating'

            self.check_timer.start()

    @QtCore.pyqtSlot(bool)
    def on_checkBuffering_toggled(self, flag):
        self.check_timer.start()

    @QtCore.pyqtSlot(bool)
    def on_checkTransient_toggled(self, flag):
        self.check_timer.start()

    @QtCore.pyqtSlot(str)
    def on_labelKernelDef_linkActivated(self, text):
        try:
            arg_idx = self.arg_variables.index(text[1:])
        except Exception:
            return

        res = self.arg_dialog.exec_(self.arg_channels[arg_idx].name,
                                    self.arg_variables[arg_idx],
                                    self.editName.text())

        if res == QtWidgets.QDialog.Accepted:
            if self.arg_dialog.discard:
                del self.arg_variables[arg_idx]
                del self.arg_channels[arg_idx]
            else:
                self.arg_variables[arg_idx] = self.arg_dialog.getVariable()
                self.arg_channels[arg_idx] = self.arg_dialog.getChannel()

            self._updateKernelDef()

    @QtCore.pyqtSlot(str)
    def on_labelAddArgument_linkActivated(self, text):
        res = self.arg_dialog.exec_(own_name=self.editName.text())

        if res == QtWidgets.QDialog.Accepted:
            self.arg_variables.append(self.arg_dialog.getVariable())
            self.arg_channels.append(self.arg_dialog.getChannel())
            self._updateKernelDef()

    @QtCore.pyqtSlot(bool)
    def on_checkInitCode_toggled(self, flag):
        self.check_timer.start()

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        name = self.editName.text()

        if not name:
            metro.app.showError('An error occured with the entered data.',
                                'A channel name is required.')
            return

        linked_kernel = metro.app._linkScriptedChannelKernel(
            self.init_object, self.kernel_object
        )

        if self.channel is not None:
            # Let's recheck!
            if self.channel.locked:
                metro.app.showError('A conflicting channel parameter was '
                                    'encountered.', 'The channel is currently '
                                    'locked.')
                return

            if self.channel.input_channels != self.arg_channels:
                self.channel.setDirect()

                getattr(self.channel, self.mode_func)(linked_kernel,
                                                      self.arg_channels)
            else:
                self.channel.kernel = linked_kernel

            self.channel.setHint(self.selectHint.currentText())
            self.channel.setFrequency(self.selectFreq.currentText())
        else:
            try:
                channel = metro.NumericChannel(
                    '$'+name, hint=self.selectHint.currentText(),
                    freq=self.selectFreq.currentText(),
                    shape=self.selectShape.currentIndex(),
                    buffering=self.checkBuffering.isChecked(),
                    transient=self.checkTransient.isChecked()
                )
            except ValueError as e:
                metro.app.showError('An error occured on creating the ',
                                    'channel.', str(e))
                return

            channel._custom = True

            getattr(channel, self.mode_func)(linked_kernel, self.arg_channels)

            self.channel = channel

        self.channel._custom_arg_variables = self.arg_variables
        self.channel._custom_kernel_source = self.editKernelCode.toPlainText()
        self.channel._custom_init_enabled = self.checkInitCode.isChecked()
        self.channel._custom_init_source = self.editInitCode.toPlainText()
        self.channel._custom_init_object = self.init_object

        self.accept()

    @QtCore.pyqtSlot()
    def on_buttonBox_discarded(self):
        if self.channel is None:
            return

        res = QtWidgets.QMessageBox.warning(
            self, f'Delete scripted channel - {metro.WINDOW_TITLE}',
            'Are you sure to delete this channel?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        self.channel.close()
        self.accept()

    @QtCore.pyqtSlot()
    def on_check(self):
        ok_button = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        ok_button.setEnabled(False)

        kernel_code = self.editKernelCode.toPlainText()

        if self.checkInitCode.isChecked():
            init_code = self.editInitCode.toPlainText()
        else:
            init_code = ''

        self.labelCheckMessage.setText('')

        try:
            if kernel_code:
                self.kernel_object = compile(
                    metro.app._wrapScriptedChannelKernel(self.arg_variables,
                                                         kernel_code),
                    '<kernel>', 'exec'
                )

            if init_code:
                self.init_object = compile(init_code, '<init>', 'exec')
            else:
                self.init_object = None

        except SyntaxError as e:
            e_str = str(e)
            last_obrace = e_str.rfind('(')
            last_comma = e_str.rfind(',')

            error = e_str[:last_obrace-1]
            chunk = e_str[last_obrace+2:last_comma-1]
            line = int(e_str[last_comma+7:-1])

            if chunk == 'kernel':
                line -= 1

            self.labelCheckMessage.setStyleSheet('color: red;')
            self.labelCheckMessage.setText(
                '{0} on line {1}: <b>{2}</b>'.format(chunk, line, error)
            )

            return

        if kernel_code:
            ok_button.setEnabled(True)

        n_channels = len(self.arg_channels)

        if n_channels > 0:
            freq = self.arg_channels[0].freq
            hint = self.arg_channels[0].hint

            none_buffering = True
            all_transient = True

            for ch in self.arg_channels:
                try:
                    if ch.buffering:
                        none_buffering = False
                except AttributeError:
                    pass

                if not ch.transient:
                    all_transient = False

                if ch.freq != freq:
                    self.labelCheckMessage.setStyleSheet('color: olive')
                    self.labelCheckMessage.setText('mismatched frequencies in '
                                                   'argument channels')
                    return
                elif ch.hint != hint:
                    self.labelCheckMessage.setStyleSheet('color: olive')
                    self.labelCheckMessage.setText('mismatched hints in '
                                                   'argument channels')
                    return

            if none_buffering and self.checkBuffering.isChecked():
                self.labelCheckMessage.setStyleSheet('color: olive')
                self.labelCheckMessage.setText('all argument channels are '
                                               'not buffering yet this '
                                               'scripted one is')
                return

            if all_transient and not self.checkTransient.isChecked():
                self.labelCheckMessage.setStyleSheet('color: olive')
                self.labelCheckMessage.setText('all argument channels are '
                                               'transient yet this scripted '
                                               'one is not')
                return

            if self.checkIntegrating.isChecked():
                if freq == metro.AbstractChannel.STEP_SAMPLES:
                    self.labelCheckMessage.setStyleSheet('color: olive')
                    self.labelCheckMessage.setText('step based channels do '
                                                   'not support integration')
                    return


class SelectChannelDialog(QtWidgets.QDialog):
    def __init__(self, selected_channel, excluded_channels,
                 hint=None, freq=None, type_=None, shape=None):
        super().__init__()

        ui_source = resources.files(__name__).joinpath('channels_select.ui')
        with resources.as_file(ui_source) as ui_path:
            QtUic.loadUi(ui_path, self)

        channel_names = sorted(metro.queryChannels(hint, freq, type_, shape))

        for channel_name in channel_names:
            if channel_name in excluded_channels:
                continue

            channel_item = QtWidgets.QListWidgetItem(channel_name,
                                                     self.listChannels)
            self.listChannels.addItem(channel_item)

            if selected_channel == channel_name:
                channel_item.setSelected(True)

    def getSelectedChannel(self):
        try:
            return self.listChannels.selectedItems()[0].text()
        except IndexError:
            # In case nothing is selected
            return None

    @metro.QSlot()
    def on_buttonBox_accepted(self):
        if len(self.listChannels.selectedItems()) == 0:
            metro.app.showError('An error occured with the entered data:',
                                'No channel is selected.')
            return

        self.accept()


class DisplayChannelDialog(QtWidgets.QDialog):
    class NumericChannelDataModel(QtCore.QAbstractTableModel):
        def __init__(self, channel):
            super().__init__()

            self.channel = channel

            self.col_count = max(1, channel.shape)
            self.raw_data = None
            self.row_count = 0

        def setStep(self, step_idx):
            self.beginResetModel()

            try:
                self.raw_data = self.channel.getData(step_idx)
            except ValueError as e:
                metro.app.showError('An error occured when retrieving channel '
                                    'data', str(e), details=e)
                self.row_count = 0
                self.endResetModel()

            try:
                self.row_count = len(self.raw_data)
            except TypeError:
                # if None
                self.row_count = 0

            self.endResetModel()

        def rowCount(self, parent):
            return self.row_count

        def columnCount(self, parent):
            return self.col_count

        def data(self, index, role):
            if role != QtCore.Qt.DisplayRole:
                return

            if self.col_count == 1:
                return str(self.raw_data[index.row()])
            else:
                return str(self.raw_data[index.row(), index.column()])

    def __init__(self, channel):
        super().__init__(metro.app.main_window)

        self.channel = channel
        self.by_value_idx = None

        ui_source = resources.files(__name__).joinpath('channels_display.ui')
        with resources.as_file(ui_source) as ui_path:
            QtUic.loadUi(ui_path, self)

        self.setWindowTitle('{0} - Metro'.format(channel.name))

        self.displayMode.setText(channel.getModeString(channel.mode))
        self.displayHint.setText(channel.getHintString(channel.hint))
        self.displayFrequency.setText(channel.getFrequencyString(channel.freq))

        if channel.freq == metro.NumericChannel.CONTINUOUS_SAMPLES:
            if channel.step_values:
                self.editStepIndex.setMaximum(len(channel.step_values)-1)

                idx = 0
                for v in channel.step_values:
                    self.selectStepValue.addItem(str(v), idx)
                    idx += 1
            else:
                self.checkStepSpecific.setEnabled(False)
                self.editStepIndex.setEnabled(False)
                self.selectStepValue.setEnabled(False)
        else:
            self.checkStepAll.setChecked(True)

            self.checkStepCurrent.setEnabled(False)
            self.checkStepAll.setEnabled(False)
            self.checkStepSpecific.setEnabled(False)
            self.editStepIndex.setEnabled(False)
            self.selectStepValue.setEnabled(False)

        if isinstance(channel, metro.NumericChannel):
            self.current_step = metro.NumericChannel.CURRENT_STEP

            self.model = DisplayChannelDialog.NumericChannelDataModel(channel)
            self.model.setStep(self.current_step)

            self.tableData.setModel(self.model)

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        self.channel = None

        try:
            self.model.channel = None
            self.model = None
        except AttributeError:
            pass

        self.accept()
        self.close()

    @QtCore.pyqtSlot(bool)
    def on_checkStepCurrent_toggled(self, flag):
        if flag:
            self.current_step = metro.NumericChannel.CURRENT_STEP
            self.model.setStep(self.current_step)

            self.buttonClear.setEnabled(True)

    @QtCore.pyqtSlot(bool)
    def on_checkStepAll_toggled(self, flag):
        if not hasattr(self, 'model'):
            # This may happen when we set to 'all' for non-continuous
            # channels during creation.
            return
        pass

        if flag:
            self.current_step = metro.NumericChannel.ALL_STEPS
            self.model.setStep(self.current_step)

            self.buttonClear.setEnabled(False)

    @QtCore.pyqtSlot(bool)
    def on_checkStepSpecific_toggled(self, flag):
        if flag:
            self.current_step = self.editStepIndex.value()
            self.model.setStep(self.current_step)

            self.buttonClear.setEnabled(False)

    @QtCore.pyqtSlot(int)
    def on_editStepIndex_valueChanged(self, value):
        if self.checkStepSpecific.isChecked():
            if self.current_step == value:
                return

            self.current_step = value
            self.model.setStep(self.current_step)

            self.selectStepValue.setCurrentIndex(value)

    @QtCore.pyqtSlot(int)
    def on_selectStepValue_currentIndexChanged(self, idx):
        if self.checkStepSpecific.isChecked():
            if self.current_step == idx:
                return

            self.current_step = idx
            self.model.setStep(self.current_step)

            self.editStepIndex.setValue(idx)

    @QtCore.pyqtSlot()
    def on_buttonRefresh_clicked(self):
        self.model.setStep(self.current_step)

    @QtCore.pyqtSlot()
    def on_buttonClear_clicked(self):
        self.channel.clearData()  # Always for current step

    def dump(self, filename):
        with open(filename, 'wb') as fp:
            self.channel.dump(self.current_step, fp)

    @QtCore.pyqtSlot()
    def on_buttonDump_clicked(self):
        if self.current_step == metro.NumericChannel.ALL_STEPS:
            step_str = 'all'
        else:
            if self.current_step == metro.NumericChannel.CURRENT_STEP:
                # PRIVATE API
                # Should have proper public API?!
                step_idx = self.channel.current_index
            else:
                step_idx = self.current_step

            step_str = 'idx={0}'.format(step_idx)

        self.dump('./{0}_{1}_{2}.txt'.format(self.channel.name, step_str,
                                             time.strftime("%H%M%S_%d%m%Y")))

    @QtCore.pyqtSlot()
    def on_buttonDumpAs_clicked(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Dump {0} as...'.format(self.channel.name)
        )

        if filename:
            self.dump(filename)

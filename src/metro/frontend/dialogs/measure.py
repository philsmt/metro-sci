
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import math  # noqa

from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5 import uic as QtUic

import metro
from metro.services import measure
from metro.frontend import arguments


class ConfigMeasurementDialog(QtWidgets.QDialog):
    class OperatorItem(QtWidgets.QTreeWidgetItem):
        def __init__(self, op_key, builtins):
            super().__init__()

            self.op_key = op_key
            self.builtins = builtins

            self.menu = QtWidgets.QMenu()
            self.menu.triggered.connect(self.on_menu_triggered)

            self.configure(builtins[0])

        def serialize(self):
            return self.op_name, self.op_args

        def getOperator(self):
            if self.op_key == 'status' and self.op_name == 'Controller':
                return metro.app.main_window

            if self.op_name in self.builtins:
                op_class = getattr(measure, self.op_name)
                op_args = self.op_args.copy()

                internal_keys = []

                for key in self.op_args.keys():
                    if key.startswith('__') and key.endswith('__'):
                        internal_keys.append(key)

                for key in internal_keys:
                    del op_args[key]

                return op_class(**op_args)
            else:
                return metro.getOperator(self.op_key, self.op_name)

        def configure(self, op_name=None, initial_values={}, show_dialog=True):
            try:
                if '__quick_ctrl__' in self.op_args and show_dialog:
                    res = QtWidgets.QMessageBox.warning(
                        metro.app.main_window.dialogMeas,
                        'Configure operator - Metro',
                        'This operator has been configured by the controller '
                        'as part of its provided quick settings. A manual '
                        'change will turn these quick settings off. Continue?',
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                    )

                    if res != QtWidgets.QMessageBox.Yes:
                        return

                    metro.app.main_window.overrideQuickControl(self.op_name)
            except AttributeError:
                pass

            if op_name is None:
                op_name = self.op_name
                initial_values = self.op_args

            try:
                dialog_class = getattr(ConfigMeasurementDialog,
                                       op_name + 'Dialog')
            except AttributeError:
                self.op_args = initial_values
                item_str = '{0}: {1}'.format(self.op_key.capitalize(), op_name)
            else:
                diag = dialog_class(initial_values)

                if show_dialog:
                    diag.exec_()

                    if diag.result() != QtWidgets.QDialog.Accepted:
                        return

                    self.op_args = diag.getArgs()
                else:
                    # Assumed to be complete!
                    self.op_args = initial_values

                item_str = '{0}: {1} ({2})'.format(self.op_key.capitalize(),
                                                   op_name, diag.arg_string())

            self.op_name = op_name
            self.setText(0, item_str)

        def getMenu(self):
            self.menu.clear()

            for op_name in self.builtins:
                new_action = self.menu.addAction(op_name)
                new_action.setCheckable(True)

                if op_name == self.op_name:
                    new_action.setChecked(True)

            ops = metro.getAllOperators(self.op_key)

            if len(self.builtins) > 0 and len(ops) > 0:
                self.menu.addSeparator()

            for op_name in sorted(ops.keys()):
                new_action = self.menu.addAction(op_name)
                new_action.setCheckable(True)

                if op_name == self.op_name:
                    new_action.setChecked(True)

            return self.menu

        # should be QtCore.pyqtSlot(QtWidgets.QAction)
        def on_menu_triggered(self, action):
            new_name = action.text()

            if new_name == self.op_name:
                return

            # Check if this operator still exists
            try:
                metro.getOperator(self.op_key, new_name)
            except KeyError:
                if new_name not in self.builtins:
                    return

            self.configure(action.text())

    class ScansetItem(QtWidgets.QTreeWidgetItem):
        def __init__(self, point_item, scan_item):
            super().__init__(['New scan'])

            self.point_item = point_item
            self.addChild(point_item)

            self.scan_item = scan_item
            self.addChild(scan_item)

        def serialize(self):
            return self.point_item.serialize(), self.scan_item.serialize()

        def getOperators(self):
            return (self.point_item.getOperator(),
                    self.scan_item.getOperator())

        def configure(self, point_state, scan_state, show_dialog=False):
            self.point_item.configure(*point_state, show_dialog=show_dialog)
            self.scan_item.configure(*scan_state, show_dialog=show_dialog)

        def operatorText(self, idx):
            return '{0}/{1}\n{0}/{2}'.format(idx, self.child(0).text(0),
                                             self.child(1).text(0))

    class FixedPointsDialog(QtWidgets.QDialog):
        @staticmethod
        def _idn(x):
            return x

        def __init__(self, initial_values):
            super().__init__()

            QtUic.loadUi(metro.resource_filename(
                __name__, 'measure_fixedpoints.ui'), self)

            try:
                self.points = initial_values['points']
            except KeyError:
                self.points = []
            else:
                for k in initial_values['points']:
                    self.listPoints.addItem(str(k))

        def arg_string(self):
            n_points = len(self.points)

            if n_points == 1:
                return '1 point'
            else:
                return '{0} points'.format(n_points)

        def getArgs(self):
            return {'points': self.points}

        def _addValues(self, values):
            if self.checkApplyFunction.isChecked():
                try:
                    func = eval('lambda x: ' + self.editFunction.text())
                except SyntaxError as e:
                    metro.app.showException('An error occured when compiling '
                                            'the custom function:', e)
            else:
                func = self._idn

            if isinstance(values, float):
                self.listPoints.addItem(str(func(values)))
            else:
                for v in values:
                    self.listPoints.addItem(str(func(v)))

        @QtCore.pyqtSlot()
        def on_buttonSingleValue_clicked(self):
            try:
                value = float(self.editSingleValue.text())
            except ValueError as e:
                metro.app.showError('An error occured with the entered data:',
                                    'Unable to convert to floating point '
                                    'number.', details=e)
            else:
                self._addValues(value)

        @QtCore.pyqtSlot()
        def on_buttonSequence_clicked(self):
            try:
                seq_start = float(self.editSeqStart.text())
                seq_step = float(self.editSeqStep.text())
            except ValueError:
                metro.app.showError('An error occured with the entered data:',
                                    'Sequence start or step is not a number.')
                return

            seq_count = self.editSeqCount.value()

            self._addValues([seq_start + i * seq_step
                             for i in range(seq_count)])

        @QtCore.pyqtSlot()
        def on_buttonClear_clicked(self):
            for item in self.listPoints.selectedItems():
                self.listPoints.takeItem(self.listPoints.row(item))

        @QtCore.pyqtSlot()
        def on_buttonBox_accepted(self):
            if self.listPoints.count() == 0:
                metro.app.showError('An error occured with the entered data:',
                                    'The list of points is empty')
                return

            self.points = [float(self.listPoints.item(i).text()) for i
                           in range(self.listPoints.count())]

            self.accept()

    class DelayedScanDialog(arguments.ConfigurationDialog):
        def __init__(self, initial_values):
            super().__init__({'delay': 1000}, initial_values)

        def arg_string(self):
            return '{delay} ms'.format(**self.getArgs())

    class DelayedTriggerDialog(arguments.ConfigurationDialog):
        def __init__(self, initial_values):
            super().__init__({'delay': 1000}, initial_values)

        def arg_string(self):
            return '{delay} ms'.format(**self.getArgs())

    class TimeLimitDialog(arguments.ConfigurationDialog):
        def __init__(self, initial_values):
            super().__init__({'time': 60}, initial_values)

        def arg_string(self):
            return '{time} s'.format(**self.getArgs())

    class CountLimitDialog(arguments.ConfigurationDialog):
        def __init__(self, initial_values):
            super().__init__({
                'channel': metro.ChannelArgument(type_=metro.StreamChannel),
                'limit': 1000
            }, initial_values)

        def arg_string(self):
            return '{limit} on {channel}'.format(**self.getArgs())

    def __init__(self):
        super().__init__()

        self.quick_ctrl_n_scans = 0

        QtUic.loadUi(metro.resource_filename(
            __name__, 'measure_config.ui'), self)

        self.menuAddScanset = QtWidgets.QMenu(self)
        self.menuAddScanset.addAction(self.actionAddScanset)

        self.menuModifyScanset = QtWidgets.QMenu(self)
        self.menuModifyScanset.addAction(self.actionUpScanset)
        self.menuModifyScanset.addAction(self.actionDownScanset)
        self.menuModifyScanset.addSeparator()
        self.menuModifyScanset.addAction(self.actionRemoveScanset)
        self.selected_item_idx = 0

        self.menuAddMacro = QtWidgets.QMenu(self)
        self.menuAddMacro.addAction(self.actionAddMacro)

        self.menuModifyMacro = QtWidgets.QMenu(self)
        self.menuModifyMacro.addAction(self.actionUpdateMacro)
        self.menuModifyMacro.addAction(self.actionDeleteMacro)
        self.selected_macro_idx = 0

        self.trigger_item = ConfigMeasurementDialog.OperatorItem(
            'trigger', ['ImmediateTrigger', 'DelayedTrigger']
        )
        self.treeMeas.addTopLevelItem(self.trigger_item)

        self.limit_item = ConfigMeasurementDialog.OperatorItem(
            'limit', ['ManualLimit', 'TimeLimit', 'CountLimit']
        )
        self.treeMeas.addTopLevelItem(self.limit_item)

        self.status_item = ConfigMeasurementDialog.OperatorItem(
            'status', ['Controller', 'HiddenStatus']
        )
        self.treeMeas.addTopLevelItem(self.status_item)

        self.actionAddScanset.trigger()

    def _addScanset(self):
        point_item = ConfigMeasurementDialog.OperatorItem(
            'point', ['ExtendablePoints', 'InfinitePoints', 'FixedPoints']
        )
        scan_item = ConfigMeasurementDialog.OperatorItem(
            'scan', ['VirtualScan', 'DelayedScan']
        )

        scanset_item = ConfigMeasurementDialog.ScansetItem(point_item,
                                                           scan_item)
        self.treeMeas.addTopLevelItem(scanset_item)

        return scanset_item

    def _removeScanset(self, item_idx):
        scanset_item = self.treeMeas.topLevelItem(item_idx)

        scanset_item.takeChild(0)
        scanset_item.takeChild(0)
        self.treeMeas.takeTopLevelItem(item_idx)

    def _updateScansetNames(self):
        scanset_idx = 0

        for item_idx in range(3, self.treeMeas.topLevelItemCount()):
            self.treeMeas.topLevelItem(item_idx).setText(
                0, 'Scan set ' + str(scanset_idx)
            )
            scanset_idx += 1

    def showEvent(self, event):
        metro.app.main_window.prev_unnamed_macro = None
        metro.app.main_window.checkOperatorMacro.setChecked(False)
        metro.app.main_window.checkOperatorMacro.setEnabled(False)

    def hideEvent(self, event):
        metro.app.main_window.checkOperatorMacro.setEnabled(True)

    def serialize(self):
        state = self.saveMacro()
        state['macros'] = {}

        for macro_idx in range(self.listMacros.count()):
            item = self.listMacros.item(macro_idx)
            state['macros'][item.text()] = (item.data(QtCore.Qt.UserRole),
                                            item.data(QtCore.Qt.ToolTipRole))

        return state

    def restore(self, state):
        for name, macro_data in state['macros'].items():
            new_item = QtWidgets.QListWidgetItem(name)
            new_item.setData(QtCore.Qt.UserRole, macro_data[0])
            new_item.setData(QtCore.Qt.ToolTipRole, macro_data[1])
            self.listMacros.addItem(new_item)
            metro.app.main_window.selectOperatorMacro.addItem(name)

        self.loadMacro(state)

    def serializeScansets(self):
        state = []

        for item_idx in range(3, self.treeMeas.topLevelItemCount()):
            state.append(self.treeMeas.topLevelItem(item_idx).serialize())

        return state

    def configureScansets(self, state):
        for item_idx in range(3, self.treeMeas.topLevelItemCount()):
            self._removeScanset(item_idx)

        for scanset_state in state:
            scanset_item = self._addScanset()
            scanset_item.configure(*scanset_state)

        self._updateScansetNames()
        self.treeMeas.expandAll()

    def saveMacro(self, list_item=None):
        state = {
            'n_scans': self.editScanAmount.value(),
            'trigger': self.trigger_item.serialize(),
            'limit': self.limit_item.serialize(),
            'status': self.status_item.serialize(),
            'scansets': self.serializeScansets()
        }

        if list_item is not None:
            list_item.setData(QtCore.Qt.UserRole, self.saveMacro())
            list_item.setData(QtCore.Qt.ToolTipRole, '\n'.join(
                [self.treeMeas.topLevelItem(idx).text(0) for idx in range(3)] +
                [self.treeMeas.topLevelItem(idx).operatorText(idx-3)
                 for idx in range(3, self.treeMeas.topLevelItemCount())]
            ))

        return state

    def loadMacro(self, state):
        if isinstance(state, str):
            state = self.listMacros.findItems(
                state, QtCore.Qt.MatchExactly
            )[0].data(QtCore.Qt.UserRole)

        self.editScanAmount.setValue(state['n_scans'])

        self.trigger_item.configure(*state['trigger'], show_dialog=False)
        self.limit_item.configure(*state['limit'], show_dialog=False)
        self.status_item.configure(*state['status'], show_dialog=False)
        self.configureScansets(state['scansets'])

    def configureTimeLimit(self, time):
        self.limit_item.configure(
            'TimeLimit', {'time': time, '__quick_ctrl__': True}, False
        )

    def configureLinearScan(self, n_scans, points, scan_op):
        self.quick_ctrl_n_scans = n_scans
        self.editScanAmount.setValue(n_scans)

        if self.treeMeas.topLevelItemCount() > 4:
            for idx in range(4, self.treeMeas.topLevelItemCount()):
                self.treeMeas.takeTopLevelItem(idx)

        self.treeMeas.topLevelItem(3).configure(
            ('FixedPoints', {'points': points, '__quick_ctrl__': True}),
            (scan_op, {'__quick_ctrl__': True})
        )

    def getOperators(self):
        if self.treeMeas.topLevelItemCount() > 4:
            operators = []

            for item_idx in range(3, self.treeMeas.topLevelItemCount()):
                operators.append(
                    self.treeMeas.topLevelItem(item_idx).getOperators()
                )

            point_op = measure.ScansetProxy(operators)
            scan_op = point_op
        else:
            point_op, scan_op = self.treeMeas.topLevelItem(3).getOperators()

        trigger_op = self.trigger_item.getOperator()
        limit_op = self.limit_item.getOperator()
        status_op = self.status_item.getOperator()

        return point_op, scan_op, trigger_op, limit_op, status_op

    @QtCore.pyqtSlot(int)
    def on_editScanAmount_valueChanged(self, value):
        if self.quick_ctrl_n_scans > 0:
            if self.quick_ctrl_n_scans == value:
                return

            res = QtWidgets.QMessageBox.warning(
                self, 'Configure scan amount - Metro',
                'The scans have been configured by the controller as part of '
                'its provided quick settings. A manual change will turn these '
                'quick settings off. Continue?',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )

            if res != QtWidgets.QMessageBox.Yes:
                self.editScanAmount.setValue(self.quick_ctrl_n_scans)
            else:
                metro.app.main_window.overrideQuickControl('FixedPoints')

    # should be @QtCore.pyqtSlot(QtCore.QPoint)
    def on_treeMeas_customContextMenuRequested(self, pos):
        item = self.treeMeas.itemAt(pos)

        if item is not None:
            if isinstance(item, ConfigMeasurementDialog.OperatorItem):
                menu = item.getMenu()
            else:
                item_idx = self.treeMeas.indexOfTopLevelItem(item)
                scanset_idx = item_idx - 3
                scanset_count = self.treeMeas.topLevelItemCount() - 3

                self.actionUpScanset.setEnabled(scanset_idx > 0)
                self.actionDownScanset.setEnabled(
                    scanset_idx < scanset_count - 1
                )
                self.actionRemoveScanset.setEnabled(scanset_count > 1)

                self.selected_item_idx = item_idx
                menu = self.menuModifyScanset
        else:
            menu = self.menuAddScanset

        menu.popup(self.treeMeas.mapToGlobal(pos))

    # should be @QtCore.pyqtSlot(QtWidgets.QTreeWidgetItem)
    def on_treeMeas_itemActivated(self, item):
        if isinstance(item, ConfigMeasurementDialog.OperatorItem):
            item.configure()

    @QtCore.pyqtSlot(bool)
    def on_actionAddScanset_triggered(self, checked):
        try:
            scan_args = self.treeMeas.topLevelItem(3).scan_item.op_args

            if '__quick_ctrl__' in scan_args:
                res = QtWidgets.QMessageBox.warning(
                    self, 'Add new scan - Metro',
                    'The scans have been configured by the controller as part '
                    'of its provided quick settings. A manual change will '
                    'turn these quick settings off. Continue?',
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                )

                if res != QtWidgets.QMessageBox.Yes:
                    return

                metro.app.main_window.overrideQuickControl('FixedPoints')
        except AttributeError:
            pass
        except TypeError:
            pass

        self._addScanset()
        self._updateScansetNames()
        self.treeMeas.expandAll()

    @QtCore.pyqtSlot(bool)
    def on_actionUpScanset_triggered(self, checked):
        item_idx = self.selected_item_idx

        if item_idx == 3:
            return

        item = self.treeMeas.takeTopLevelItem(item_idx)
        self.treeMeas.insertTopLevelItem(item_idx - 1, item)

        self._updateScansetNames()
        self.treeMeas.expandAll()

    @QtCore.pyqtSlot(bool)
    def on_actionDownScanset_triggered(self, checked):
        item_idx = self.selected_item_idx

        if item_idx == self.treeMeas.topLevelItemCount() - 1:
            return

        item = self.treeMeas.takeTopLevelItem(item_idx)
        self.treeMeas.insertTopLevelItem(item_idx + 1, item)

        self._updateScansetNames()
        self.treeMeas.expandAll()

    @QtCore.pyqtSlot(bool)
    def on_actionRemoveScanset_triggered(self, checked):
        if self.treeMeas.topLevelItemCount() == 4:
            return

        self._removeScanset(self.selected_item_idx)
        self._updateScansetNames()

    # should be @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def on_listMacros_itemActivated(self, item):
        self.loadMacro(item.data(QtCore.Qt.UserRole))

    # should be @QtCore.pyqtSlot(QtCore.QPoint)
    def on_listMacros_customContextMenuRequested(self, pos):
        item = self.listMacros.itemAt(pos)

        if item is not None:
            self.selected_macro_idx = self.listMacros.row(item)
            menu = self.menuModifyMacro
        else:
            menu = self.menuAddMacro

        menu.popup(self.listMacros.mapToGlobal(pos))

    @QtCore.pyqtSlot(bool)
    def on_actionAddMacro_triggered(self, checked):
        value, success = QtWidgets.QInputDialog.getItem(
            self, 'Add macro - Metro', 'Please enter a name for this macro',
            [''] + [self.listMacros.item(idx).text()
                    for idx in range(self.listMacros.count())],
            editable=True
        )

        if not success:
            return

        try:
            item = self.listMacros.findItems(value, QtCore.Qt.MatchExactly)[0]
        except IndexError:
            item = QtWidgets.QListWidgetItem(value)
            self.listMacros.addItem(item)
            metro.app.main_window.selectOperatorMacro.addItem(value)
        else:
            res = QtWidgets.QMessageBox.warning(
                self, 'Add macro - Metro',
                'A macro with that name already exists, overwrite?',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )

            if res != QtWidgets.QMessageBox.Yes:
                return

        self.saveMacro(item)

    @QtCore.pyqtSlot(bool)
    def on_actionDeleteMacro_triggered(self, checked):
        res = QtWidgets.QMessageBox.warning(
            self, 'Delete  macro - Metro',
            'Are you sure to delete this macro?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        item = self.listMacros.takeItem(self.selected_macro_idx)

        idx = metro.app.main_window.selectOperatorMacro.findText(
            item.text(), QtCore.Qt.MatchExactly
        )
        metro.app.main_window.selectOperatorMacro.removeItem(idx)

    @QtCore.pyqtSlot(bool)
    def on_actionUpdateMacro_triggered(self, checked):
        res = QtWidgets.QMessageBox.warning(
            self, 'Update macro - Metro',
            'Are you sure to overwrite this macro with the current settings?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        self.saveMacro(self.listMacros.item(self.selected_item_idx))

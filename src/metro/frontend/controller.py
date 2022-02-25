
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import os
import time
from itertools import accumulate

from pkg_resources import iter_entry_points

import metro
from metro.services import channels, measure, profiles
from metro.frontend import dialogs, widgets

from metro.services import logger
log = logger.log(__name__)

QtCore = metro.QtCore
QtGui = metro.QtGui
QtWidgets = metro.QtWidgets
QtUic = metro.QtUic


# Format an amount of seconds to Xh Ymin Zs
def formatTime(seconds):
    if seconds > 3600:
        hours = int(seconds / 3600)
        seconds -= 3600 * hours

        minutes = int(seconds / 60)
        seconds -= 60 * minutes

        return '{0}h {1}min {2}s'.format(hours, minutes, seconds)

    elif seconds > 60:
        minutes = int(seconds / 60)
        seconds -= 60 * minutes

        return '{0}min {1}s'.format(minutes, seconds)

    else:
        return str(seconds) + 's'


def buildDirectEntryPointMenu(entry_point, menu):
    for entry_point in iter_entry_points(entry_point):
        menu.addAction(entry_point.name).setData(entry_point.name)


def buildRecursiveEntryPointMenu(entry_point, base_menu):
    submenus = {'': base_menu}

    entry_points = sorted(iter_entry_points(entry_point),
                          key=lambda x: x.name)

    for entry_point in entry_points:
        name = entry_point.name
        parent = name[:name.rfind('.')] if '.' in name else ''

        try:
            submenu = submenus[parent]
        except KeyError:
            parts = parent.split('.')
            submenu = base_menu

            for pparent in accumulate(parts, lambda x, y: f'{x}.{y}'):
                try:
                    submenu = submenus[pparent]
                except KeyError:
                    submenu = submenu.addMenu(pparent[pparent.rfind('.')+1:])
                    submenus[pparent] = submenu

        submenu.addAction(name[name.rfind('.')+1:]).setData(name)


def buildRecursiveDirectoryMenu(base_dir, base_menu, final_separator=True,
                                dirname_filter=lambda x: True,
                                filename_filter=lambda x: True,
                                extension_filter=lambda x: True):

    submenus = {base_dir: base_menu}

    hits = []

    for root, dirnames, filenames in os.walk(base_dir):
        if not dirname_filter(root):
            continue

        menu = submenus[root]

        for current_dirname in sorted(dirnames):
            if not dirname_filter(current_dirname):
                continue

            submenus[os.path.join(root, current_dirname)] = menu.addMenu(
                current_dirname
            )

        for current_filename in sorted(filenames):
            if not filename_filter(current_filename):
                continue

            name, ext = os.path.splitext(current_filename)

            if not extension_filter(ext):
                continue

            path = os.path.join(root, current_filename)

            menu.addAction(name).setData(path)
            hits.append(path)

    if len(hits) > 0 and final_separator:
        base_menu.addSeparator()

    return hits


class MainWindow(QtWidgets.QWidget, measure.StatusOperator, measure.Node,
                 measure.BlockListener):

    def __init__(self):
        super().__init__()

        self.device_names = []
        self.device_labels = {}
        self.known_profiles = None  # populated by _buildProfilesMenu

        self.control_overriden = False

        self.meas = None

        # Saves the measurement parameters overwritten by the quick
        # settings on the controller
        self.prev_limit = None
        self.prev_scancount = 0
        self.prev_scansets = None
        self.prev_unnamed_macro = None

        measure.RunBlock.listener = self

        self.dialogMeas = dialogs.ConfigMeasurementDialog()
        self.dialogBrowseStorage = None
        self.dialogConfigStorage = None

        QtUic.loadUi(metro.resource_filename(
            __name__, 'controller.ui'), self)

        self.setWindowTitle(f'Controller - {metro.WINDOW_TITLE}')

        def getStandardIcon(s):
            return self.style().standardIcon(
                getattr(QtWidgets.QStyle, 'SP_' + s)
            )

        self.buttonRun.setIcon(getStandardIcon('MediaPlay'))
        self.buttonStep.setIcon(getStandardIcon('MediaSeekForward'))
        self.buttonPause.setIcon(getStandardIcon('MediaPause'))
        self.buttonStop.setIcon(getStandardIcon('MediaStop'))

        self.shortcutScreenshot = QtWidgets.QShortcut(
            QtGui.QKeySequence('CTRL+SHIFT+S'), self,
            context=QtCore.Qt.ApplicationShortcut
        )
        self.shortcutScreenshot.activated.connect(
            self.on_shortcutScreenshot_activated
        )

        self.menuNewDevice = QtWidgets.QMenu()
        self.menuNewDevice.triggered.connect(self.on_menuNewDevice_triggered)
        self.buttonNewDevice.setMenu(self.menuNewDevice)

        self.menuNewChannel = QtWidgets.QMenu()
        self.menuNewChannel.triggered.connect(self.on_menuNewChannel_triggered)
        self.buttonNewChannel.setMenu(self.menuNewChannel)

        # Create the log window along with the log handler as the base handler
        self.logWindow = logger.LogWindow(base=True)
        self.logWindow.setWindowTitle(f'Log - {metro.WINDOW_TITLE}')
        self.logWindow.onNewEntry(self.newLogEntry)

        self.menuProfiles = QtWidgets.QMenu()
        self.menuProfiles.aboutToShow.connect(self.on_menuProfiles_aboutToShow)
        self.menuProfiles.triggered.connect(self.on_menuProfiles_triggered)
        self.buttonProfiles.setMenu(self.menuProfiles)

        self.menuDeviceLink = widgets.LabelableMenu()
        self.menuDeviceLink.triggered.connect(self.on_menuDeviceLink_triggered)

        self.menuChannelLink = widgets.ChannelLinkMenu()

        self._buildNewDeviceMenu()
        self._buildNewChannelMenu()
        self._buildProfilesMenu()

        self.labelDevicelessChannels.setContextMenu(self.menuChannelLink)
        self.labelDevicelessChannels.hide()

        metro.channels.watch(self)

        self.measuring_timer = QtCore.QTimer(self)
        self.measuring_timer.setInterval(1000)
        self.measuring_timer.timeout.connect(self.measurementTicked)

        self.step_duration_average = 0  # Average over all step duration
        self.last_step_begin = 0  # Begin of last step
        self.used_steps = 0  # How many steps have been used as average
        self.remaining_steps = 0  # How many steps are still remaining

        self.deviceOperatorsChanged()

        # Load storage settings
        self.storage_root = '.'
        self.storage_numbering = False
        self.storage_increase = 1
        self.storage_padding = 3
        self.storage_indicators = True

        self.storage_base = None

        try:
            storage = profiles.load(
                os.path.join(metro.LOCAL_PATH, 'standard_storage.json'))
        except FileNotFoundError:
            pass
        except ValueError:
            pass
        else:
            if 'indicators' not in storage:
                # Compatibility for older file formats
                storage['indicators'] = True
                storage['last_number'] = 0
                storage['last_name'] = ''
                self._updateStorageProfile()

            self.storage_root = storage['root']
            self.storage_numbering = storage['numbering']
            self.storage_increase = storage['increase']
            self.storage_padding = storage['padding']
            self.storage_indicators = storage['indicators']
            self.editStorageNumber.setValue(storage['last_number'])
            self.editStorageName.setText(storage['last_name'])

        # Update LogChannel storage root
        metro.LogChannel.storage_root = self.storage_root

        log.info("Main window constructed")

    # Build the "new device" menu by iterating over all metro.device
    # entry points.
    def _buildNewDeviceMenu(self):
        self.menuNewDevice.clear()

        buildRecursiveEntryPointMenu('metro.device',
                                     self.menuNewDevice)

        self.menuNewDevice.addAction(
            'Rescan devices'
        ).setData('__rescan__')

        if metro.experimental:
            self.menuNewDevice.addSeparator()

            self.menuNewDevice.addAction(
                'Window group...'
            ).setData('__group_by_window__')

            self.menuNewDevice.addAction(
                'Tab group...'
            ).setData('__group_by_tab__')

        # Also refresh the ChannelLinkMenu's menu
        if widgets.ChannelLinkMenu.menuDisplayBy is None:
            # We cannot construct it statically since the application
            # object won't live then.
            widgets.ChannelLinkMenu.menuDisplayBy = QtWidgets.QMenu()

        widgets.ChannelLinkMenu.menuDisplayBy.clear()

        buildDirectEntryPointMenu('metro.display_device',
                                  widgets.ChannelLinkMenu.menuDisplayBy)

        self.menuNewDevice.addSeparator()
        self.menuNewDevice.addAction(self.actionShowDisplayDevices)

    def _buildNewChannelMenu(self):
        self.menuNewChannel.clear()

        self.menuNewChannel.addAction(
            'Normalized channel...'
        ).setData('__normalized__')

        self.menuNewChannel.addAction(
            'Statistics channel...'
        ).setData('__statistics__')

        self.menuNewChannel.addAction(
            'Scripted channel...'
        ).setData('__scripted__')

        if metro.experimental:
            self.menuNewChannel.addSeparator()

            self.menuNewChannel.addAction(
                'Remote channel...'
            ).setData('__network__')

    def _buildProfilesMenu(self):
        self.menuProfiles.clear()

        self.known_profiles = buildRecursiveDirectoryMenu(
            metro.PROFILE_PATH, self.menuProfiles,
            filename_filter=lambda x: not x.startswith('_'),
            extension_filter=lambda x: x == '.json'
        )

        self.actionProfileSave = self.menuProfiles.addAction(
            'Save current configuration...'
        )

        self.actionProfileOverwrite = self.menuProfiles.addAction(
            'Overwrite last profile...',
        )

        self.actionProfileExternal = self.menuProfiles.addAction(
            'Choose external file...'
        )

        self.actionProfileRescan = self.menuProfiles.addAction(
            'Rescan profiles'
        )

        if metro.version_short is not None:
            self.menuProfiles.addSeparator()
            self.actionVersion = self.menuProfiles.addAction(
                'Version: {0}'.format(metro.version_short)
            )
            self.actionVersion.setEnabled(False)
            # TODO: Add clickable dialog with more version informations
            # and/or log output

    def _addUsedProfile(self, name):
        pass

    def _getTimeLimit(self):
        return (self.editTimeLimitMin.value() * 60 +
                self.editTimeLimitSec.value())

    def _updateInternalIndicators(self):
        ind = {'start': None, 'end': None, 'step': None, 'time': None}

        if self.checkTimeLimit.isChecked():
            ind['time'] = formatTime(self._getTimeLimit()).replace(' ', '')

        if self.checkLinearScan.isChecked():
            ind['start'] = self.editLinearScanStart.text()
            ind['end'] = self.editLinearScanEnd.text()
            ind['step'] = self.editLinearScanStep.text()

        for key, value in ind.items():
            metro.app.setIndicator(key, value)

    def _updateTimeEstimate(self):
        if self.meas is not None:
            # Do not change the label if we are in a measurement
            return

        if not self.checkLinearScan.isChecked():
            self.displayRemainingTime.setText('')
            return

        if not self.checkTimeLimit.isChecked():
            self.displayRemainingTime.setText('Unknown!')
            return

        n_scans = self.editLinearScanCount.value()
        time_per_step = self._getTimeLimit()

        try:
            scan_diff = (float(self.editLinearScanEnd.text()) -
                         float(self.editLinearScanStart.text()))
            scan_step = float(self.editLinearScanStep.text())

            if scan_diff/abs(scan_diff) != scan_step/abs(scan_step):
                raise ValueError('infinite number of steps')

            n_steps = 1 + round(scan_diff / scan_step, 5)

            if abs(n_steps - int(n_steps)) > 10**-6:
                raise ValueError('difference not divisible by step')

            n_steps = int(n_steps)
        except ValueError:
            # previously \u26A0
            self.displayRemainingTime.setText('Value!')
        except ZeroDivisionError:
            # previously \u221E
            self.displayRemainingTime.setText('Infinity!')
        else:
            self.displayRemainingTime.setText(
                formatTime(n_scans * n_steps * time_per_step)
            )

    def _updateTimeLimit(self):
        self.dialogMeas.configureTimeLimit(self._getTimeLimit())

    def _updateLinearScan(self):
        points = []

        try:
            scan_start = float(self.editLinearScanStart.text())
            scan_end = float(self.editLinearScanEnd.text())
            scan_step = float(self.editLinearScanStep.text())

            n_steps = 1 + round((scan_end - scan_start) / scan_step, 5)
        except ValueError:
            pass
        except ZeroDivisionError:
            pass
        else:
            for i in range(int(n_steps)):
                points.append(scan_start + i * scan_step)

        scan_op = self.selectLinearScanOperator.currentText()

        try:
            metro.getOperator('scan', scan_op)
        except KeyError:
            scan_op = 'VirtualScan'

        self.dialogMeas.configureLinearScan(self.editLinearScanCount.value(),
                                            points, scan_op)

    def _setStatusDisplay(self, text, color):
        self.displayState.setStyleSheet('background: {0}; '
                                        'color: white; '
                                        'font-weight: bold;'.format(color))
        self.displayState.setText(text)

    def _resetStepDurationGuess(self):
        self.step_duration_average = 0
        self.last_step_begin = 0
        self.used_steps = 0
        self.displayRemainingTime.setText('?')

    def _updateStorageProfile(self):
        profiles.save(
            os.path.join(metro.LOCAL_PATH, 'standard_storage.json'), {
            'root': self.storage_root,
            'numbering': self.storage_numbering,
            'increase': self.storage_increase,
            'padding': self.storage_padding,
            'indicators': self.storage_indicators,
            'last_number': self.editStorageNumber.value(),
            'last_name': self.editStorageName.text()
        })

    _meas_param_widget_names = [
        'checkTimeLimit', 'checkLinearScan',
        'editTimeLimitMin', 'editTimeLimitSec',
        'editLinearScanCount', 'selectLinearScanOperator',
        'editLinearScanStart', 'editLinearScanEnd', 'editLinearScanStep',
        'selectOperatorMacro'
    ]

    _meas_control_widget_names = _meas_param_widget_names + [
        'buttonRun', 'labelMoreMeasOptions'
    ]

    def overrideQuickControl(self, op_name):
        if op_name == 'TimeLimit':
            self.prev_limit = None
            self.checkTimeLimit.setChecked(False)
        else:
            self.prev_scancount = 0
            self.prev_scansets = None
            self.checkLinearScan.setChecked(False)

    def enableMeasurementParams(self, state):
        for widget_name in self._meas_param_widget_names:
            getattr(self, widget_name).setEnabled(state)

    def overrideMeasurementControl(self, actor):
        if self.control_overriden:
            raise RuntimeError('control already overriden')

        for widget_name in self._meas_control_widget_names:
            widget = getattr(self, widget_name)

            widget.setEnabled(False)
            widget.setToolTip('Overridden by ' + actor)

        if measure.RunBlock.listener == self:
            if isinstance(actor, measure.BlockListener):
                measure.RunBlock.listener = actor
            else:
                measure.RunBlock.listener = None

        self.control_overriden = True

    def releaseMeasurementControl(self):
        if not self.control_overriden:
            raise RuntimeError('control already released')

        for widget_name in self._meas_control_widget_names:
            widget = getattr(self, widget_name)

            widget.setEnabled(True)
            widget.setToolTip('')

        self.control_overriden = False

        measure.RunBlock.listener = self

    def getStorageBase(self):
        if self.checkStorage.isChecked():
            if self.storage_numbering:
                number_str = str(
                    self.editStorageNumber.value()
                ).zfill(self.storage_padding) + '_'
            else:
                number_str = ''

            storage_name = self.editStorageName.text()

            if self.storage_indicators:
                self._updateInternalIndicators()

                # We are not using str.format() here even though it
                # would be much faster. It is far too clunky for what we
                # use it for especially regarding special characters and
                # missing indicators.
                for key, value in metro.app.indicators.items():
                    storage_name = storage_name.replace('{' + key + '}',
                                                        value)

            storage_base = '{0}/{1}{2}_{3}'.format(
                self.storage_root, number_str, storage_name,
                time.strftime('%d%m%Y_%H%M%S')
            )
        else:
            storage_base = None

        return storage_base

    def dumpGeometry(self):
        geometry = self.geometry()

        return (geometry.left(), geometry.top(),
                geometry.width(), geometry.height())

    def restoreGeometry(self, state):
        self.setGeometry(QtCore.QRect(*state))

    def serializeMeasParams(self):
        return {
            'time_limit_checked': self.checkTimeLimit.isChecked(),
            'time_limit_min': self.editTimeLimitMin.value(),
            'time_limit_sec': self.editTimeLimitSec.value(),

            'linear_scan_checked': self.checkLinearScan.isChecked(),
            'linear_scan_count': self.editLinearScanCount.value(),
            'linear_scan_start': self.editLinearScanStart.text(),
            'linear_scan_op': self.selectLinearScanOperator.currentText(),
            'linear_scan_end': self.editLinearScanEnd.text(),
            'linear_scan_step': self.editLinearScanStep.text(),

            'full': self.dialogMeas.serialize()
        }

    def restoreMeasParams(self, state):
        self.checkTimeLimit.setChecked(state['time_limit_checked'])
        self.editTimeLimitMin.setValue(state['time_limit_min'])
        self.editTimeLimitSec.setValue(state['time_limit_sec'])

        self.checkLinearScan.setChecked(state['linear_scan_checked'])
        self.editLinearScanCount.setValue(state['linear_scan_count'])

        scan_operator_idx = self.selectLinearScanOperator.findText(
            state['linear_scan_op'], QtCore.Qt.MatchExactly
        )
        self.selectLinearScanOperator.setCurrentIndex(scan_operator_idx)

        self.editLinearScanStart.setText(state['linear_scan_start'])
        self.editLinearScanEnd.setText(state['linear_scan_end'])
        self.editLinearScanStep.setText(state['linear_scan_step'])

        if state['full'] is not None:
            # Special case for compatbility with older profiles
            self.dialogMeas.restore(state['full'])

    # Quit the complete app on closing the main window
    def closeEvent(self, event):
        if self.meas is not None:
            event.ignore()

            self.meas.abort()

            self.close_timer = QtCore.QTimer(self)
            self.close_timer.setInterval(750)
            self.close_timer.timeout.connect(self.quit)
            self.close_timer.start()
        else:
            self.quit()

    # Watch for maximize event to maximize all device windows
    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.WindowStateChange:
            was_minimized = (
                int(event.oldState()) == QtCore.Qt.WindowMinimized and
                int(self.windowState()) == QtCore.Qt.WindowNoState
            )

            if was_minimized:
                for d in metro.getAllDevices():
                    if d.isVisible():
                        d.maximize()

    def deviceCreated(self, device):
        if isinstance(device, metro.TransientDevice):
            return
        elif isinstance(device, metro.DisplayDevice) or \
                isinstance(device._parent, metro.DisplayDevice):
            layout = self.layoutDisplayDevices
            visible = self.actionShowDisplayDevices.isChecked()
        else:
            layout = self.layoutDevices
            visible = True

        device_name = device._name

        row_idx = layout.rowCount()

        device_label = widgets.LinksLabel()
        device_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        device_label.setSizePolicy(QtWidgets.QSizePolicy.Minimum,
                                   QtWidgets.QSizePolicy.Preferred)
        device_label.setLink(device_name, device_name)
        device_label.formatLink(device_name, bold=False, italic=True)
        device_label.linkActivated.connect(self.on_deviceLink_activated)
        device_label.contextRequested.connect(
            self.on_deviceLink_contextRequested
        )

        channels_label = widgets.ChannelLinksLabel()
        channels_label.setContextMenu(self.menuChannelLink)
        channels_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)
        channels_label.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                                     QtWidgets.QSizePolicy.Preferred)

        layout.addWidget(device_label, row_idx, 0)
        layout.addWidget(channels_label, row_idx, 1)

        device_label.setVisible(visible)
        channels_label.setVisible(visible)

        self.device_labels[device_name] = (device_label, channels_label)

        self.device_names.append(device._name)

    def deviceKilled(self, device):
        try:
            device_label, channels_label = self.device_labels[device._name]
        except KeyError:
            # This can happen for transient devices or display devices.
            return

        n_channels = len(channels_label)

        if isinstance(device, metro.DisplayDevice):
            layout = self.layoutDisplayDevices
        else:
            layout = self.layoutDevices

        layout.removeWidget(device_label)
        layout.removeWidget(channels_label)

        device_label.hide()
        channels_label.hide()

        self.device_names.remove(device._name)

        del self.device_labels[device._name]

        if n_channels > 0:
            print('WARNING: One or more channels still appeared to be opened '
                  'by device {0}. This may cause a memory '
                  'leak.'.format(device._name))

    def deviceShown(self, device):
        # Skip display devices
        if isinstance(device, metro.DisplayDevice):
            return

        device_name = device._name
        self.device_labels[device_name][0].formatLink(device_name,
                                                      bold=True, italic=False)

    def deviceHidden(self, device):
        # Skip display devices
        if isinstance(device, metro.DisplayDevice):
            return

        device_name = device._name
        self.device_labels[device_name][0].formatLink(device_name,
                                                      bold=False, italic=True)

    def deviceOperatorsChanged(self):
        prev_op = self.selectLinearScanOperator.currentText()

        self.selectLinearScanOperator.clear()
        self.selectLinearScanOperator.addItem('none')

        for name in sorted(list(metro.getAllOperators('scan').keys())):
            self.selectLinearScanOperator.addItem(name)

        idx = self.selectLinearScanOperator.findText(prev_op,
                                                     QtCore.Qt.MatchExactly)
        self.selectLinearScanOperator.setCurrentIndex(idx if idx != -1 else 0)

    # Callback from channels module (implemented as a normal Watcher)
    def channelOpened(self, channel):
        name = channel.name

        device = metro.findDeviceForChannel(name)

        if device is not None:
            try:
                channels_label = self.device_labels[device._name][1]
            except KeyError:
                pass
            else:
                needle_char = '$' if '$' in name else '#'
                act_name = name[name.rfind(needle_char)+1:]

                if act_name[0] == '-':
                    return

                channels_label.addChannel(channel, act_name)
        else:
            if self.labelDevicelessChannels.isHidden():
                self.labelDevicelessChannels.show()

            self.labelDevicelessChannels.addChannel(channel, name)

    # Callback from channels module (implemented as a normal Watcher)
    def channelClosed(self, channel):
        device = metro.findDeviceForChannel(channel.name)

        if device is not None:
            try:
                self.device_labels[device._name][1].removeChannel(channel)
            except KeyError:
                pass
        else:
            self.labelDevicelessChannels.removeChannel(channel)

            if len(self.labelDevicelessChannels) == 0:
                self.labelDevicelessChannels.hide()

    def prepareStatus(self, max_limit):
        self.barLimit.setMaximum(max_limit)
        self.barLimit.setFormat('%v/{0}'.format(max_limit))

        return self.updateStatus, self.barLimit.setValue

    @metro.QSlot()
    def quit(self):
        if self.meas is not None:
            return

        try:
            # segfault fix
            self.dialogConfigStorage.close()
            self.dialogConfigStorage = None
        except AttributeError:
            pass

        for dev_grp in metro.app.device_groups:
            dev_grp.close()

        metro.killAllDevices()

        log.info("Quitting Metro.")

        metro.app.processEvents()
        metro.app.quit()

        # Delay the leak check to allow all objects to be reclaimed.
        self.leakTimer = metro.QTimer(self)
        self.leakTimer.setInterval(1)
        self.leakTimer.setSingleShot(True)
        self.leakTimer.timeout.connect(self._leak_check)
        self.leakTimer.start()

    @metro.QSlot()
    def _leak_check(self):
        metro.checkForDeviceLeaks()

    @metro.QSlot(int)
    def updateStatus(self, code):
        if code == measure.StatusOperator.STANDBY:
            self._setStatusDisplay('Standby', 'Grey')

            self.measuring_timer.stop()

            # Return the maximum to 100 in case it was 0 to stop it from
            # "moving" all the time on some styles.
            if self.barLimit.maximum() == 0:
                self.barLimit.setMaximum(100)

            if not self.control_overriden:
                if self.storage_base is not None:
                    metro.app.screenshot(self.storage_base)

                    if self.storage_numbering:
                        self.editStorageNumber.setValue(
                            self.editStorageNumber.value() +
                            self.storage_increase
                        )
                        self._updateStorageProfile()

                # buttonRun is handled by RunBlock listener
                self.buttonStep.setEnabled(False)
                self.buttonPause.setChecked(False)
                self.buttonPause.setEnabled(False)
                self.buttonStop.setEnabled(False)

                self.meas = None

            # A StatusOperator should do this
            metro.app.current_meas = None

            self._updateTimeEstimate()

        elif code == measure.StatusOperator.PREPARING:
            self._setStatusDisplay('Blocked', 'Crimson')

            if not self.control_overriden:
                # buttonRun is handled by RunBlock listener
                self.buttonStep.setEnabled(True)
                self.buttonPause.setEnabled(True)
                self.buttonStop.setEnabled(True)

            n_points = len(metro.app.current_meas.getPoints())

            if n_points == 0:
                n_points == 1

            self.remaining_steps = n_points

            self.barSteps.setValue(0)
            self.barSteps.setMaximum(n_points)
            self.barSteps.setFormat('%v/{0}'.format(n_points))

        elif code == measure.StatusOperator.ENTERING_SCAN:
            self.barSteps.setValue(0)

        elif code == measure.StatusOperator.ENTERING_STEP:
            self._setStatusDisplay('Choosing point', 'DeepSkyBlue')

        elif code == measure.StatusOperator.CONFIGURING:
            max_step = self.barSteps.maximum()

            if self.barSteps.value() == max_step:
                # If we already at the maximum yet still advanced to
                # another step, we are working without a step limit and
                # just increase our counters by one
                self.remaining_steps += 1
                max_step += 1

                self.barSteps.setMaximum(max_step)
                self.barSteps.setFormat('%v/{0}'.format(max_step))

            self.barLimit.setValue(0)

            self._setStatusDisplay('Moving scan', 'DarkBlue')

        elif code == measure.StatusOperator.TRIGGER_ARMED:
            self._setStatusDisplay('Trigger armed', 'DarkGoldenRod')

        elif code == measure.StatusOperator.RUNNING:
            self._setStatusDisplay('Running', 'DarkGreen')

        elif code == measure.StatusOperator.LEAVING_STEP:
            self._setStatusDisplay('Blocked', 'Crimson')
            self.barSteps.setValue(self.barSteps.value() + 1)

            if self.storage_base is not None:
                if self.barSteps.value() == 1 and self.remaining_steps > 1:
                    metro.app.screenshot(self.storage_base)

        elif code == measure.StatusOperator.LEAVING_SCAN:
            self.barScans.setValue(self.barScans.value() + 1)

        elif code == measure.StatusOperator.FINALIZING:
            self._setStatusDisplay('Blocked', 'Crimson')

        elif code == measure.StatusOperator.PAUSED:
            self._setStatusDisplay('Paused', 'DarkViolet')

            if not self.control_overriden:
                self.buttonRun.setEnabled(True)  # special!
                self.buttonStep.setEnabled(False)
                self.buttonPause.setChecked(False)
                self.buttonPause.setEnabled(False)

            self._resetStepDurationGuess()

        else:
            self._setStatusDisplay('Unknown', 'Plum')

    def blockAcquired(self):
        self.buttonRun.setEnabled(False)

    def blockReleased(self):
        self.buttonRun.setEnabled(True)

    def connectToMeasurement(self, prepared, started, stopped, finalized):
        started.connect(self.measurementStarted)
        stopped.connect(self.measurementStopped)

    @metro.QSlot()
    def measurementStarted(self):
        now = time.monotonic()

        if self.last_step_begin > 0:
            self.used_steps += 1

            new_duration = now - self.last_step_begin

            old_average = self.step_duration_average
            self.step_duration_average = int(
                (1-1/self.used_steps) * old_average +
                (1/self.used_steps) * new_duration
            )

            remaining_total = formatTime(self.remaining_steps *
                                         self.step_duration_average)

            self.displayRemainingTime.setText('≈' + remaining_total)

        self.last_step_begin = now

    @metro.QSlot()
    def measurementTicked(self):
        elapsed = int(round(time.monotonic() - self.measuring_start, 0))

        self.displayElapsedTime.setText(formatTime(elapsed))

    @metro.QSlot()
    def measurementStopped(self):
        self.remaining_steps -= 1

    @metro.QSlot()
    def configMeasurementAccepted(self):
        pass

    @metro.QSlot()
    def configStorageAccepted(self):
        csd = self.dialogConfigStorage

        if csd.editDirectory.text() != self.storage_root:
            QtWidgets.QMessageBox.information(
                self, self.windowTitle(),
                'The change of the storage directory will not take effect for '
                'any currently opened LogChannels until the respective '
                'channels are recreated, e.g. by restarting the device or '
                'the complete application. This does not apply to measured '
                'data.'
            )

        self.storage_root = csd.editDirectory.text()
        self.storage_numbering = csd.checkNumbering.isChecked()
        self.storage_increase = csd.editNumberingIncrease.value()
        self.storage_padding = csd.editNumberingPadding.value()
        self.storage_indicators = csd.checkIndicators.isChecked()

        # Update LogChannel storage root
        metro.LogChannel.storage_root = self.storage_root

        self._updateStorageProfile()

    @metro.QSlot()
    def on_shortcutScreenshot_activated(self):
        root = self.storage_root if os.path.isdir(self.storage_root) else '.'

        metro.app.screenshot('{0}/screenshot_{1}'.format(
            root, time.strftime('%H%M%S_%d%m%Y')
        ))

    @metro.QSlot()
    def on_buttonRun_pressed(self):
        if self.meas is not None:
            # A measurement is running and was only paused!
            self.meas.resume()

            # Restore the button state
            self.buttonRun.setEnabled(False)
            self.buttonStep.setEnabled(True)
            self.buttonPause.setEnabled(True)
            self.buttonStop.setEnabled(True)
            return

        if self.checkLinearScan.isChecked():
            try:
                try:
                    scan_start = float(self.editLinearScanStart.text())
                    scan_end = float(self.editLinearScanEnd.text())
                    scan_step = float(self.editLinearScanStep.text())
                except ValueError:
                    raise ValueError('One or more scan parameters are '
                                     'nonreal.')

                if scan_step == 0.0:
                    raise ValueError('The scan parameters lead to an infinite '
                                     'number of points (step length is zero).')

                elif scan_start > scan_end and scan_step > 0:
                    raise ValueError('The scan parameters lead to an infinite '
                                     'number of points (first step is greater '
                                     'than last step with non-negative step '
                                     'difference)')

                elif scan_end > scan_start and scan_step < 0:
                    raise ValueError('The scan parameters lead to an infinite '
                                     'number of points (last step is greater '
                                     'than first step with non-positive step '
                                     'difference).')
            except Exception as e:
                metro.app.showError('An error occured while configuring '
                                    'the measurement:', str(e), details=e)
                return

        n_scans = self.dialogMeas.editScanAmount.value()
        point_op, scan_op, trigger_op, limit_op, status_op = \
            self.dialogMeas.getOperators()

        # Here we can expect the following properties to be properly
        # populated:
        # points, n_scan, scan_op trigger_op, limit_op

        self.barScans.setValue(0)
        self.barScans.setMaximum(n_scans)
        self.barScans.setFormat('%v/{0}'.format(n_scans))

        self.storage_base = self.getStorageBase()

        self._resetStepDurationGuess()

        cur_nodes = list(metro.getAllDevices())
        cur_nodes.append(self)

        cur_channels = [chan for chan
                        in channels.sortByDependency(channels.getAll())
                        if not chan.isStatic()]

        self.meas = measure.Measurement(
            cur_nodes, cur_channels, point_op, scan_op, trigger_op, limit_op,
            self, n_scans, self.storage_base
        )

        metro.app.current_meas = self.meas

        self.measuring_timer.start()
        self.measuring_start = time.monotonic()

        self.meas.run()

    @metro.QSlot()
    def on_buttonStep_pressed(self):
        self.meas.skipLimit()

    @metro.QSlot()
    def on_buttonPause_pressed(self):
        # Apparently this gets called before the state is changed, so we
        # have to invert it ourselves. Still we want to use this signal
        # because it is always the result of manual interaction.
        self.meas.setPauseFlag(not self.buttonPause.isChecked())

    @metro.QSlot()
    def on_buttonStop_pressed(self):
        if self.meas is None:
            return

        self.meas.abort()

        # Disable all buttons for the moment, they get enabled
        # explicitly later again in the StatusOperator.
        self.buttonRun.setEnabled(False)
        self.buttonStep.setEnabled(False)
        self.buttonPause.setEnabled(False)
        self.buttonStop.setEnabled(False)

    @metro.QSlot(bool)
    def on_checkTimeLimit_toggled(self, flag):
        if flag:
            self.prev_limit = self.dialogMeas.limit_item.serialize()
            self._updateTimeLimit()

            if self.checkOperatorMacro.isChecked():
                self.checkOperatorMacro.setChecked(False)
        else:
            if self.prev_limit is not None:
                self.dialogMeas.limit_item.configure(*self.prev_limit,
                                                     show_dialog=False)

        self._updateTimeEstimate()

    @metro.QSlot(int)
    def on_editTimeLimitMin_valueChanged(self, value):
        self._updateTimeEstimate()

        if self.checkTimeLimit.isChecked():
            self._updateTimeLimit()

    @metro.QSlot(int)
    def on_editTimeLimitSec_valueChanged(self, value):
        if value >= 60:
            excess_minutes = value // 60

            self.editTimeLimitMin.setValue(
                self.editTimeLimitMin.value() + excess_minutes
            )
            self.editTimeLimitSec.setValue(
                value - excess_minutes * 60
            )

        self._updateTimeEstimate()

        if self.checkTimeLimit.isChecked():
            self._updateTimeLimit()

    @metro.QSlot(bool)
    def on_checkLinearScan_toggled(self, flag):
        if flag:
            self.prev_scancount = self.dialogMeas.editScanAmount.value()
            self.prev_scansets = self.dialogMeas.serializeScansets()
            self._updateLinearScan()

            if self.checkOperatorMacro.isChecked():
                self.checkOperatorMacro.setChecked(False)
        else:
            if self.prev_scansets is not None:
                self.dialogMeas.editScanAmount.setValue(self.prev_scancount)
                self.dialogMeas.configureScansets(self.prev_scansets)

        self._updateTimeEstimate()

    @metro.QSlot(int)
    def on_editLinearScanCount_valueChanged(self, value):
        if self.checkLinearScan.isChecked():
            self._updateLinearScan()

        self._updateTimeEstimate()

    @metro.QSlot(str)
    def on_selectLinearScanOperator_currentTextChanged(self, text):
        if self.checkLinearScan.isChecked():
            self._updateLinearScan()

    @metro.QSlot(str)
    def on_editLinearScanStart_textChanged(self, text):
        if self.checkLinearScan.isChecked():
            self._updateLinearScan()

        self._updateTimeEstimate()

    @metro.QSlot(str)
    def on_editLinearScanEnd_textChanged(self, text):
        if self.checkLinearScan.isChecked():
            self._updateLinearScan()

        self._updateTimeEstimate()

    @metro.QSlot(str)
    def on_editLinearScanStep_textChanged(self, text):
        if self.checkLinearScan.isChecked():
            self._updateLinearScan()

        self._updateTimeEstimate()

    @metro.QSlot(bool)
    def on_checkOperatorMacro_toggled(self, flag):
        if flag:
            self.prev_unnamed_macro = self.dialogMeas.saveMacro()

            if self.selectOperatorMacro.count() > 0:
                self.dialogMeas.loadMacro(
                    self.selectOperatorMacro.currentText()
                )

            if self.checkLinearScan.isChecked():
                self.checkLinearScan.setChecked(False)

            if self.checkTimeLimit.isChecked():
                self.checkTimeLimit.setChecked(False)
        else:
            if self.prev_unnamed_macro is not None:
                self.dialogMeas.loadMacro(self.prev_unnamed_macro)

    @metro.QSlot(str)
    def on_selectOperatorMacro_currentTextChanged(self, text):
        if self.checkOperatorMacro.isChecked():
            self.dialogMeas.loadMacro(text)

    @metro.QSlot(str)
    def on_labelMoreMeasOptions_linkActivated(self, text):
        self.dialogMeas.show()

    @metro.QSlot(str)
    def on_labelStorageBrowse_linkActivated(self, text):
        if self.dialogBrowseStorage is None:
            self.dialogBrowseStorage = dialogs.BrowseStorageDialog()

        try:
            self.dialogBrowseStorage.setLocation(self.storage_root)
        except ValueError as e:
            metro.app.showError('An error occured on setting the storage '
                                'directory.', str(e))
        else:
            self.dialogBrowseStorage.show()

    @metro.QSlot(str)
    def on_labelStorageConfig_linkActivated(self, text):
        if self.dialogConfigStorage is None:
            self.dialogConfigStorage = dialogs.ConfigStorageDialog()
            self.dialogConfigStorage.accepted.connect(
                self.configStorageAccepted
            )

        csd = self.dialogConfigStorage

        csd.editDirectory.setText(self.storage_root)
        csd.checkNumbering.setChecked(self.storage_numbering)
        csd.editNumberingIncrease.setValue(self.storage_increase)
        csd.editNumberingPadding.setValue(self.storage_padding)
        csd.checkIndicators.setChecked(self.storage_indicators)
        self._updateInternalIndicators()

        csd.show()

    # Geeeeeeeez...
    # For some unknown reason pyqtgraph stops working properly when we
    # specify QtWidgets.QAction as the argument type for ANY slot. Yes,
    # it does not make any sense. And yes I have no clue why. And yes it
    # took me more than a day to figure it out. Using the superclass
    # also breaks on some builds of PyQt5, so we use no decorator.
    def on_menuNewDevice_triggered(self, action):
        name = action.data()

        if name == '__rescan__':
            self._buildNewDeviceMenu()

        elif name == '__external__':
            path, __ = QtWidgets.QFileDialog.getOpenFileName(
                self, 'Load new device from external script'
            )

            if not path or not os.path.isfile(path):
                return

            metro.app.createNewDevice(path)

        elif name == '__group_by_window__':
            text, confirmed = QtWidgets.QInputDialog.getText(
                None, self.windowTitle(), 'Name for new device group'
            )

            if not confirmed or not text:
                return

            window_group = metro.WindowGroupWidget(text)
            metro.app.addDeviceGroup(window_group)

        elif name == '__group_by_tab__':
            text, confirmed = QtWidgets.QInputDialog.getText(
                None, self.windowTitle(), 'Name for new device group'
            )

            if not confirmed or not text:
                return

            tab_group = metro.TabGroupWidget(text)
            metro.app.addDeviceGroup(tab_group)

        elif action == self.actionShowDisplayDevices:
            pass

        else:
            metro.app.createNewDevice(name)

    @metro.QSlot(bool)
    def on_actionShowDisplayDevices_toggled(self, flag):
        for idx in range(self.layoutDisplayDevices.count()):
            self.layoutDisplayDevices.itemAt(idx).widget().setVisible(flag)

    # @metro.QSlot(QtWidgets.QAction)
    def on_menuNewChannel_triggered(self, action):
        name = action.data()

        if name == '__normalized__':
            metro.app.editNormalizedChannel(None)
        elif name == '__statistics__':
            metro.app.editStatisticsChannel(None)
        elif name == '__scripted__':
            metro.app.editScriptedChannel(None)
        elif name == '__remote__':
            pass

    @metro.QSlot(int)
    def newLogEntry(self, levelno):
        # Colorize the button on new log entry if log is not currently shown
        if self.logWindow.isHidden():
            color = '#000000' # '#505050' darkgray
            css_str = 'color: {0}; font-weight: bold;'
            self.buttonLog.setStyleSheet(css_str.format(color))

    @metro.QSlot()
    def on_buttonLog_clicked(self):
        if self.logWindow.isHidden():
            self.logWindow.show()

            # Reverse to normal button design when clicked
            self.buttonLog.setStyleSheet('')
        else:
            self.logWindow.close()

    @metro.QSlot()
    def on_menuProfiles_aboutToShow(self):
        self.actionProfileOverwrite.setEnabled(
            metro.app.last_used_profile is not None
        )

    # @metro.QSlot(QtWidgets.QAction)
    def on_menuProfiles_triggered(self, action):
        if action == self.actionProfileSave:
            dialog = dialogs.SaveProfileDialog(self.known_profiles)
            dialog.exec_()

            if dialog.result() != QtWidgets.QDialog.Accepted:
                return

            dialog.saveAsProfile()
            self._buildProfilesMenu()

        elif action == self.actionProfileOverwrite:
            name, path, _ = metro.app.last_used_profile

            res = QtWidgets.QMessageBox.question(
                self, self.windowTitle(),
                'Overwrite the profile <b>{0}</b> with the complete current '
                'configuration?'.format(name)
            )

            if res == QtWidgets.QMessageBox.No:
                return

            metro.app.saveProfile(path)

        elif action == self.actionProfileExternal:
            path, __ = QtWidgets.QFileDialog.getOpenFileName(
                self, f'Load external profile - {metro.WINDOW_TITLE}'
            )

            if not path or not os.path.isfile(path):
                return

            metro.app.loadProfile(path)

        elif action == self.actionProfileRescan:
            self._buildProfilesMenu()

        else:
            metro.app.loadProfile(action.data())

    @metro.QSlot(str)
    def on_deviceLink_activated(self, device_name):
        device = metro.getDevice(device_name)

        if device.isHidden():
            device.show()
        else:
            device.hide()

    @metro.QSlot(str, QtCore.QPoint)
    def on_deviceLink_contextRequested(self, device_name, menu_pos):
        device = metro.getDevice(device_name)

        self.menuDeviceLink.clear()
        self.menuDeviceLink.setTitle(device_name)

        self.menuDeviceLink.addAction('Show arguments').setData('__args__')

        if not device.isChildDevice():
            self.menuDeviceLink.addSeparator()

            actionKill = self.menuDeviceLink.addAction('Kill')
            actionKill.setData('__kill__')

        self.menuDeviceLink.popup(menu_pos)

    # @metro.QSlot(QtWidgets.QAction)
    def on_menuDeviceLink_triggered(self, action):
        device = metro.getDevice(self.menuDeviceLink.title())
        action = action.data()

        if action == '__args__':
            dialog = dialogs.DeviceArgumentsDialog(device)
            dialog.exec_()

        elif action == '__kill__':
            device.kill()

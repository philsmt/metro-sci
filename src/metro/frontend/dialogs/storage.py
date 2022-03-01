
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import os
import json
import hashlib

import numpy
import h5py
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5 import uic as QtUic

import metro


class ReplayStreamChannelDialog(QtWidgets.QDialog):
    class MetroFileLoader(QtCore.QThread):
        def __init__(self, path, shape, body_offset):
            super().__init__()

            self.path = path
            self.shape = shape
            self.body_offset = body_offset

        def run(self):
            self.step_values = []
            self.chunks = []

            with open(self.path, 'r') as fp:
                # Find our first step marker if there is any
                for line in fp:
                    if line.startswith('# STEP'):
                        self.step_values.append(
                            line.rstrip()[line.find(':')+2:]
                        )
                    elif not line.startswith('#'):
                        break

                fp.seek(self.body_offset)

                step_idx = 0
                eos = False  # end-of-scan
                eof = False  # end-of-file

                def read_cells():
                    nonlocal fp, step_idx, eos, eof

                    for line in fp:
                        if line.startswith('# SCAN'):
                            eos = True
                            break
                        elif line.startswith('# STEP'):
                            step_value = line.rstrip()[line.find(':')+2:]

                            try:
                                self.step_values[step_idx+1] = step_value
                            except IndexError:
                                self.step_values.append(step_value)

                            break
                        elif line.startswith('#'):
                            # Skip any remaining markers
                            continue

                        cols = line.rstrip().split('\t')

                        for item in cols:
                            yield float(item)

                    if not line.startswith('#') or 'ABORTED' in line:
                        eof = True

                while not eof:
                    chunk = numpy.fromiter(read_cells(), dtype=float)

                    if step_idx == len(self.chunks):
                        self.chunks.append([])

                    self.chunks[step_idx].append(chunk)

                    if eos:
                        step_idx = 0
                        eos = False
                    else:
                        step_idx += 1

            self.data = []

            for i in range(len(self.chunks)):
                self.data.append(numpy.concatenate(self.chunks[i]))

            if self.shape > 1:
                for i in range(len(self.data)):
                    self.data[i] = [self.data[i].reshape((-1, self.shape))]

    def __init__(self, path):
        super().__init__()

        QtUic.loadUi(metro.resource_filename(
            __name__, 'storage_replay.ui'), self)

        self.path = path
        fp = open(path, 'r')

        headers = {'proj': [], 'display': {}}
        deprecated = True

        cur_offset = 0

        # First we read in the header
        for line in fp:
            if line.startswith('# Name'):
                headers['name'] = line[8:].strip()
                deprecated = False
            elif line.startswith('# Shape'):
                headers['shape'] = line[9:].strip()
                deprecated = False
            elif line.startswith('# Hint'):
                headers['hint'] = line[8:].strip()
                deprecated = False
            elif line.startswith('# Frequency'):
                headers['freq'] = line[13:].strip()
                deprecated = False
            elif line.startswith('# X-Proj'):
                headers['proj'].append(json.loads(line[(line.find(':')+1):]))
            elif line.startswith('# DISPLAY'):
                key = line[10:line.find(':')]
                value = line[line.find(':')+2:-1]

                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        pass

                headers['display'][key] = value

            if not line.startswith('#'):
                self.body_offset = cur_offset
                self.column_count = len(line.rstrip().split('\t'))
                break

            cur_offset += len(line)

        fp.close()

        try:
            self.body_offset
            self.column_count
        except AttributeError:
            metro.app.showError(
                'An error occured on attempting to read the file for replay:',
                'No data rows found.'
            )
            self.reject()

        if deprecated:
            metro.app.showError(
                'The replayed file does not specify all channel parameters.',
                'This usually means that the file in question was saved with '
                'an older version of Metro that did not embed the '
                'corresponding information. It is therefore not possible to '
                'interpret the data in this channel and the correct display '
                'device has to be chosen manually.'
            )

        if 'shape' not in headers:
            if self.column_count == 1:
                value, success = QtWidgets.QInputDialog.getItem(
                    self, 'Specify shape - Metro',
                    'The shape of this channel is not specified in the header '
                    'and it could not be detected automatically because it '
                    'contains only one column. Please specify whether it '
                    'should be treated as scalars or vectors.',
                    ['scalar', 'vector'], editable=False
                )

                if not success:
                    self.reject()

                headers['shape'] = 0 if value == 'scalar' else 1
            else:
                headers['shape'] = self.column_count

        if 'hint' not in headers:
            headers['hint'] = 'unknown'

        if 'freq' not in headers:
            headers['freq'] = 'continuous'

        if headers['proj']:
            i = 2
            for p in sorted(headers['proj'], key=lambda x: x[0]):
                checkbox = QtWidgets.QCheckBox(self)
                checkbox.setText('{0} ({1})'.format(p[0], p[1]))
                p.append(checkbox)

                self.layout().insertWidget(i, checkbox)
                i += 1
        else:
            self.labelDesc.hide()

        self.resize(self.sizeHint())

        self.path = path
        self.headers = headers

        self.progress_timer = QtCore.QTimer(self)
        self.progress_timer.setInterval(250)
        self.progress_timer.timeout.connect(self.on_progress_tick)
        self.progress_iterator = 0

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        name = self.editName.text()

        if not name:
            metro.app.showError('An error occured with the entered data.',
                                'A channel name is required.')
            return

        self.loader = ReplayStreamChannelDialog.MetroFileLoader(
            self.path, int(self.headers['shape']), self.body_offset
        )

        # TODO: Disable this button when loading starts

        self.loader.started.connect(self.progress_timer.start)
        self.loader.finished.connect(self.on_loader_finished)
        self.loader.start()

    @QtCore.pyqtSlot()
    def on_loader_finished(self):
        name = '@'+self.editName.text()

        try:
            chan = metro.NumericChannel(
                name, hint=self.headers['hint'], freq=self.headers['freq'],
                shape=int(self.headers['shape']), static=True
            )
        except ValueError as e:
            metro.app.showError('An occured on creating the channel', str(e))
            return

        chan.display_arguments = self.headers['display']

        if self.headers['freq'] == 'continuous':
            chan.data = self.loader.data
            chan.step_values = self.loader.step_values

        elif self.headers['freq'] == 'step':
            steps = self.loader.data[0].shape[0]

            chan.data = []
            for step_index in range(steps):
                chan.data.append([x[step_index] for x in self.loader.data])

            chan.step_values = [str(i) for i in range(len(chan.data))]

        elif self.headers['freq'] == 'scheduled':
            chan.data = self.loader.data

        chan._replayed = True
        chan._replayed_path = self.path

        for p in self.headers['proj']:
            if not p[3].isChecked():
                continue

            metro.createDevice(p[1], '{0}_{1}'.format(name, p[0]),
                               args={'channel': chan, 'count_rows': False},
                               state={'visible': False, 'custom': p[2]})

        self.progress_timer.stop()
        self.labelProgress.setText('Done!')

        self.accept()

    @QtCore.pyqtSlot()
    def on_progress_tick(self):
        self.labelProgress.setText(
            'Loading' + self.progress_iterator % 4 * '.'
        )

        self.progress_iterator += 1


class ReplayDatagramChannelDialog(QtWidgets.QDialog):
    class MetroFileLoader(QtCore.QThread):
        def __init__(self, path):
            super().__init__()

            self.path = path

        def run(self):
            self.step_values = []
            self.chunks = []
            self.display_arguments = {}

            with h5py.File(self.path, 'r') as h5f:
                self.freq = h5f.attrs['freq']
                self.hint = h5f.attrs['hint']

                for key, value in h5f.attrs.items():
                    if key.startswith('DISPLAY'):
                        if isinstance(value, numpy.bool_):
                            value = bool(value)
                        elif isinstance(value, numpy.int64):
                            value = int(value)

                        self.display_arguments[key[8:]] = value

                if self.freq == 'step':
                    self.step_values = [float(v) for v in h5f['0']]
                    self.data = [numpy.array(h5f['0'][val])
                                 for val in h5f['0']]
                else:
                    raise NotImplementedError('Continuous DatagramChannels '
                                              'unsupported')

    def __init__(self, path):
        super().__init__()

        QtUic.loadUi(metro.resource_filename(
            __name__, 'storage_replay.ui'), self)

        self.path = path

        self.labelDesc.hide()

        self.resize(self.sizeHint())

        self.path = path

        self.progress_timer = QtCore.QTimer(self)
        self.progress_timer.setInterval(250)
        self.progress_timer.timeout.connect(self.on_progress_tick)
        self.progress_iterator = 0

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        name = self.editName.text()

        if not name:
            metro.app.showError('An error occured with the entered data.',
                                'A channel name is required.')
            return

        self.loader = ReplayDatagramChannelDialog.MetroFileLoader(self.path)

        # TODO: Disable this button when loading starts

        self.loader.started.connect(self.progress_timer.start)
        self.loader.finished.connect(self.on_loader_finished)
        self.loader.start()

    @QtCore.pyqtSlot()
    def on_loader_finished(self):
        name = '@'+self.editName.text()

        try:
            chan = metro.DatagramChannel(
                name, hint=self.loader.hint, freq=self.loader.freq,
                static=True
            )
        except ValueError as e:
            metro.app.showError('An occured on creating the channel', str(e))
            return

        chan.display_arguments = self.loader.display_arguments

        if self.loader.freq == 'step':
            chan.last_datum = self.loader.data[-1]
            chan.step_values = self.loader.step_values

        else:
            raise NotImplementedError('Continuous DatagramChannel unsupported')

        chan._replayed = True
        chan._replayed_path = self.path

        self.progress_timer.stop()
        self.labelProgress.setText('Done!')

        self.accept()

    @QtCore.pyqtSlot()
    def on_progress_tick(self):
        self.labelProgress.setText(
            'Loading' + self.progress_iterator % 4 * '.'
        )

        self.progress_iterator += 1


class BrowseStorageDialog(QtWidgets.QDialog):
    class StorageFilesModel(QtCore.QAbstractTableModel):
        COLUMN_NAMES = ['Number', 'Name', 'Date', 'Time', '# Channels']

        def __init__(self):
            super().__init__()

            self.files = []

        def setLocation(self, root):
            self.root = root

            new_files = []

            # First we sort out the screenshot as markers
            for entry in os.listdir(root):
                if entry[-4:] != '.jpg':
                    continue

                filename = entry[:-4]

                parts = filename.split('_')

                if len(parts) < 3:
                    continue

                try:
                    int(parts[0])
                except ValueError:
                    number = ''
                    name_idx = 0
                else:
                    number = parts[0]
                    name_idx = 1

                time = parts[-1]
                date = parts[-2]

                # number, name, time, date, channel_count
                new_files.append([
                    number, '_'.join(parts[name_idx:-2]),
                    '{0}.{1}.{2}'.format(date[:2], date[2:4], date[4:]),
                    '{0}:{1}:{2}'.format(time[:2], time[2:4], time[4:]),
                    0, filename]
                )

            for entry in os.listdir(root):
                if entry[-4:] == '.jpg':
                    continue

                for details in new_files:
                    if entry.startswith(details[5]):
                        details.append(entry)
                        details[4] += 1

            self.beginResetModel()

            self.files = sorted(new_files, key=lambda x: x[0])

            self.endResetModel()

        def deleteFiles(self, rows):
            parent = QtCore.QModelIndex()

            for row in sorted(list(rows), reverse=True):
                details = self.files[row]

                excs = []

                try:
                    os.remove('{0}/{1}.jpg'.format(self.root, details[5]))
                except Exception as e:
                    excs.append(e)

                for i in range(6, len(details)):
                    try:
                        os.remove('{0}/{1}'.format(self.root, details[i]))
                    except Exception as e:
                        excs.append(e)

                if excs:
                    metro.app.showError('One or more error(s) occured while '
                                        'trying to remove files related to '
                                        'the selected measurement run.\n'
                                        '(Details apply only to the first '
                                        'exception thrown)',
                                        '\n'.join([str(e) for e in excs]),
                                        details=excs[0])

                self.beginRemoveRows(parent, row, row)
                del self.files[row]
                self.endRemoveRows()

        def rowCount(self, parent):
            return len(self.files)

        def columnCount(self, parent):
            return 5

        def headerData(self, section, orientation, role):
            if role == QtCore.Qt.DisplayRole:
                if orientation == QtCore.Qt.Horizontal:
                    return self.COLUMN_NAMES[section]
                else:
                    return section+1

        def flags(self, index):
            res = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

            if index.column() < 2:
                res |= QtCore.Qt.ItemIsEditable

            return res

        def data(self, index, role):
            if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.EditRole:
                return self.files[index.row()][index.column()]
            elif role == QtCore.Qt.ToolTipRole:
                if index.column() == 4:
                    details = self.files[index.row()]

                    channel_idx = len(details[5])+1
                    channel_names = [s[channel_idx:-4] for s in details[6:]]

                    return '\n'.join(sorted(channel_names))

        def setData(self, index, value, role):
            details = self.files[index.row()]

            details[index.column()] = value

            new_root = '{0}{1}_{2}_{3}'.format(
                details[0] + '_' if details[0] else '', details[1],
                details[2].replace(':', ''), details[3].replace('.', '')
            )

            if details[5] == new_root:
                return True

            old_root_len = len(details[5])

            os.rename('{0}/{1}.jpg'.format(self.root, details[5]),
                      '{0}/{1}.jpg'.format(self.root, new_root))

            for i in range(6, len(details)):
                new_path = new_root + details[i][old_root_len:]

                os.rename(self.root + '/' + details[i],
                          self.root + '/' + new_path)
                details[i] = new_path

            details[5] = new_root

            return True

    def __init__(self):
        super().__init__()

        QtUic.loadUi(metro.resource_filename(
            __name__, 'storage_browse.ui'), self)

        self.model = BrowseStorageDialog.StorageFilesModel()
        self.tableFiles.setModel(self.model)

        self.menuReplay = QtWidgets.QMenu(self)
        self.menuReplay.triggered.connect(self.on_menuReplay_triggered)

        self.tableFiles.contextMenuEvent = self.tableFiles_contextMenuEvent

    def setLocation(self, root):
        self.root = root

        if not os.path.isdir(root):
            metro.app.showError('An occured on reading the storage directory.',
                                'The current storage directory does not '
                                'exist.')

        self.model.setLocation(root)
        self.tableFiles.resizeColumnsToContents()
        self.displayLocation.setText(root)

    def tableFiles_contextMenuEvent(self, e):
        # This is rather quirky, but we do not want to use a custom
        # class just for this one method

        idx = self.tableFiles.indexAt(e.pos())

        if idx.row() == -1:
            return

        details = self.model.files[idx.row()]

        self.menuReplay.clear()

        channels = [(path, path[(len(details[5])+1):path.rfind('.')])
                    for path
                    in details[6:]]
        channels.sort(key=lambda x: x[1])

        for path, name in channels:
            self.menuReplay.addAction(name).setData(path)

        self.menuReplay.popup(e.globalPos())

    @staticmethod
    def _createUniqueChannelName(path, meas_name, channel_name):
        file_prefix = path[:-(5+len(channel_name))]
        hash_fragment = hashlib.md5(file_prefix.encode('ascii')).hexdigest()

        return '{0}-{1}-{2}'.format(hash_fragment[:6], meas_name, channel_name)

    @QtCore.pyqtSlot(int)
    def on_dialogReplay_finished(self, code):
        self.dialogReplay = None

    def _getReplayDialog(self, path):
        if path.endswith('.txt'):
            return ReplayStreamChannelDialog(path)
        elif path.endswith('.h5'):
            return ReplayDatagramChannelDialog(path)

    # should be @QtCore.pyqtSlot(QtWidgets.QAction)
    def on_menuReplay_triggered(self, action):
        path = action.data()

        self.dialogReplay = self._getReplayDialog(self.root + '/' + path)
        self.dialogReplay.finished.connect(self.on_dialogReplay_finished)
        self.dialogReplay.show()

    @QtCore.pyqtSlot(str)
    def on_labelReplayExternal_linkActivated(self, link):
        dialog = QtWidgets.QFileDialog(self)
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptOpen)
        dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)

        if dialog.exec_() == QtWidgets.QDialog.Rejected:
            return

        self.dialogReplay = self._getReplayDialog(dialog.selectedFiles()[0])
        self.dialogReplay.finished.connect(self.on_dialogReplay_finished)
        self.dialogReplay.show()

    @QtCore.pyqtSlot()
    def on_buttonDelete_clicked(self):
        rows = set()

        for index in self.tableFiles.selectedIndexes():
            rows.add(index.row())

        res = QtWidgets.QMessageBox.warning(
            self, 'Delete files - Metro', 'Are you sure to delete these {0} '
                                          'measurement?'.format(len(rows)),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res != QtWidgets.QMessageBox.Yes:
            return

        self.model.deleteFiles(rows)

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()
        self.close()


class ConfigStorageDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()

        QtUic.loadUi(metro.resource_filename(
            __name__, 'storage_config.ui'), self)
        self.resize(self.sizeHint())

    @metro.QSlot(str)
    def on_labelShowIndicators_linkActivated(self, link):
        indicators = metro.app.indicators
        all_keys = sorted(indicators.keys())

        internal_keys = []
        device_keys = []

        for key in all_keys:
            if key.startswith('d.'):
                device_keys.append(key)
            else:
                internal_keys.append(key)

        tooltip_text = ''

        if internal_keys:
            tooltip_text += '\n'.join(['{0}: {1}'.format(key, indicators[key])
                                       for key in internal_keys])

            if device_keys:
                tooltip_text += '\n'

        if device_keys:
            tooltip_text += '\n'.join(['{0}: {1}'.format(key, indicators[key])
                                       for key in device_keys])

        QtWidgets.QToolTip.showText(metro.QtGui.QCursor.pos(), tooltip_text,
                                    self.labelShowIndicators)

    @QtCore.pyqtSlot()
    def on_buttonBox_accepted(self):
        self.hide()
        self.accepted.emit()

    @QtCore.pyqtSlot()
    def on_buttonBrowse_clicked(self):
        last_dir = None

        if self.editDirectory.text():
            last_dir = self.editDirectory.text()

        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Select base directory', directory=last_dir
        )

        self.editDirectory.setText(path)

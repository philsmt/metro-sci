
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import math
import time

import numpy as np
import xarray as xr
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets

import metro
from metro.external import pyqtgraph
from metro.devices.abstract import fittable_plot

pyqtgraph.setConfigOptions(antialias=False)

# Create a default gradient, which is almost viridis. It adds a new
# lower bracket though for very small values (< 1e-3 relatively) which
# is pure black.
from metro.external.pyqtgraph.graphicsItems.GradientEditorItem \
    import Gradients  # noqa
default_gradient = Gradients['viridis'].copy()
default_gradient['ticks'][0] = (1e-3, default_gradient['ticks'][0][1])
default_gradient['ticks'].insert(0, (0.0, (0, 0, 0, 255)))


class DataViewBox(pyqtgraph.ViewBox):
    def raiseContextMenu(self, ev):
        menu = self.getMenu(ev)
        if menu is not None:
            # In newer pyqtgraph versions, a better implementation may
            # se GraphicsScene.sigMouseClicked and interact with
            # GraphicsScene.addParentContextMenus or QMenu.aboutToSHow().
            self.last_data_pos = self.mapSceneToView(ev.scenePos())

            menu.labelCoordX.setText(f'X: {self.last_data_pos.x()}')
            menu.labelCoordY.setText(f'Y: {self.last_data_pos.y()}')

            super().raiseContextMenu(ev)


class DataImageItem(pyqtgraph.ImageItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._coords = None

    def setCoordinates(self, x, y):
        if len(x) > 1:
            x_min = x.min()
            dx = x[1] - x[0]
            x_start = x_min - dx/2
            x_len = x.max() - x_min + dx
        else:
            x_start = x[0] - 0.5
            x_len = 1.0

        if len(y) > 1:
            y_min = y.min()
            dy = y[1] - y[0]
            y_start = y_min - dy/2
            y_len = y.max() - y_min + dy
        else:
            y_start = y[0] - 0.5
            y_len = 1.0

        self._coords = (x_start, y_start, x_len, y_len)

    def boundingRect(self):
        if self._coords is None:
            return super().boundingRect()

        return QtCore.QRectF(*self._coords)

    def paint(self, p, *args):
        # Verbatim copy of ImageItem.paint() except for the actual
        # drawImage call.

        if self.image is None:
            return
        if self.qimage is None:
            self.render()
            if self.qimage is None:
                return
        if self.paintMode is not None:
            p.setCompositionMode(self.paintMode)

        shape = self.image.shape[:2] if self.axisOrder == 'col-major' \
            else self.image.shape[:2][::-1]

        if self._coords is None:
            p.drawImage(QtCore.QRectF(0, 0, *shape), self.qimage)
        else:
            p.drawImage(QtCore.QRectF(*self._coords), self.qimage)

        if self.border is not None:
            p.setPen(self.border)
            p.drawRect(self.boundingRect())


class Device(metro.WidgetDevice, metro.DisplayDevice, fittable_plot.Device):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(type_=metro.DatagramChannel),
        'history_streak': -1,
        'axis_order': ('row-major', 'col-major')
    }

    def prepare(self, args, state):
        self.history_streak = args['history_streak']
        self.axis_order = args['axis_order']

        self.viewBox = DataViewBox()
        self.plotItem = pyqtgraph.PlotItem(viewBox=self.viewBox)
        self.imageItem = DataImageItem()
        self.imageItem.setOpts(axisOrder=self.axis_order)

        self.displayImage = pyqtgraph.ImageView(
            self, view=self.plotItem, imageItem=self.imageItem)
        self.displayImage._opt_2d_parallel_profiles = True

        # Must be set after creating the other pyqtgraph objects.
        self.viewBox.setAspectLocked(False)

        menu = self.viewBox.menu
        menu.addSeparator()

        label_css = '''QLabel {{
            color: {color};
            font-family: monospace;
            padding: {top} 4 {bottom} 5px;
            font-size: 15px
        }}'''

        self.actionCoordX = QtWidgets.QWidgetAction(menu)
        menu.labelCoordX = QtWidgets.QLabel('')
        menu.labelCoordX.setStyleSheet(label_css.format(
            color='#BB0000', top=4, bottom=1))
        self.actionCoordX.setDefaultWidget(menu.labelCoordX)

        self.actionCoordY = QtWidgets.QWidgetAction(menu)
        menu.labelCoordY = QtWidgets.QLabel('')
        menu.labelCoordY.setStyleSheet(label_css.format(
            color='#0000BB', top=0, bottom=2))
        self.actionCoordY.setDefaultWidget(menu.labelCoordY)

        menu.insertSeparator(menu.actions()[0])
        menu.insertAction(menu.actions()[0], self.actionCoordY)
        menu.insertAction(menu.actions()[0], self.actionCoordX)

        self.actionPauseDrawing = menu.addAction('Pause drawing')
        self.actionPauseDrawing.setCheckable(True)
        self.actionPauseDrawing.setChecked(False)
        self.actionPauseDrawing.toggled.connect(
            self.on_actionPauseDrawing_toggled
        )

        self.actionRedrawOnce = menu.addAction('Redraw once')
        self.actionRedrawOnce.setEnabled(False)
        self.actionRedrawOnce.triggered.connect(
            self.on_actionRedrawOnce_triggered
        )

        self.actionAutoScale = menu.addAction('Always rescale Z axis')
        self.actionAutoScale.setCheckable(True)
        self.actionAutoScale.setChecked(False)
        self.actionAutoScale.toggled.connect(
            self.on_actionAutoScale_toggled
        )

        self.actionRescaleOnce = menu.addAction('Rescale Z axis once')
        self.actionRescaleOnce.setEnabled(True)
        self.actionRescaleOnce.triggered.connect(
            self.on_actionRescaleOnce_triggered
        )

        self.throttle_total = 0
        self.throttle_i = 0

        self.pause_drawing = False
        self.redraw_once = False
        self.auto_z_scale = True  # Always scale once in the beginning
        self.scale_z_once = False

        self.history_buffer = None

        layout = metro.QtWidgets.QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.displayImage)
        self.setLayout(layout)

        self.channel_rate = 10

        self.fit_curves = {}

        if state is not None:
            roi_state = state[0]

            self.displayImage.roi.setPos(*roi_state[0])
            self.displayImage.roi.setSize(roi_state[1])
            self.displayImage.roi.setAngle(roi_state[2])

            if roi_state[3]:
                self.displayImage.ui.roiBtn.click()

            self.actionAutoScale.setChecked(state[1])
            self.displayImage.ui.histogram.gradient.restoreState(state[2])
        else:
            self.displayImage.ui.histogram.gradient.restoreState(
                default_gradient)

        self.channel = args['channel']
        self.channel.subscribe(self)

    def finalize(self):
        self.channel.unsubscribe(self)

    def serialize(self):
        roi = self.displayImage.roi.getState()
        roi_state = ((roi['pos'].x(), roi['pos'].y()),
                     (roi['size'].x(), roi['size'].y()),
                     roi['angle'], self.displayImage.ui.roiBtn.isChecked())

        return roi_state, self.actionAutoScale.isChecked(), \
            self.displayImage.ui.histogram.gradient.saveState()

    def dataSet(self, d):
        pass

    @staticmethod
    def _get_axis_idx(axis_order):
        if axis_order == 'row-major':
            return 1, 0
        elif axis_order == 'col-major':
            return 0, 1

    def dataAdded(self, d):
        if isinstance(d, xr.DataArray):
            axis_order = d.attrs.get('axis_order', self.axis_order)
            if axis_order not in Device.arguments['axis_order']:
                axis_order = self.axis_order

            x_axis_idx, y_axis_idx = self._get_axis_idx(axis_order)

            x = d.coords[d.dims[x_axis_idx]].data
            self.plotItem.setLabel('bottom', d.dims[x_axis_idx])
            y = d.coords[d.dims[y_axis_idx]].data
            self.plotItem.setLabel('left', d.dims[y_axis_idx])

            d = d.data

        elif isinstance(d, np.ndarray) and d.ndim == 2:
            axis_order = self.axis_order
            x_axis_idx, y_axis_idx = self._get_axis_idx(axis_order)

            x = np.arange(d.shape[x_axis_idx])
            y = np.arange(d.shape[y_axis_idx])

        elif self.history_streak > 0:
            d = np.squeeze(d)

            # Remove any additional axes
            while len(d.shape) > 1:
                d = d[-1]

            if self.history_buffer is None or \
                    self.history_buffer.shape[1] != len(d):
                self.history_buffer = np.zeros(
                    (self.history_streak, len(d)), dtype=d.dtype)

            # Pretty expensive for now
            self.history_buffer = np.roll(self.history_buffer, 1, axis=0)
            self.history_buffer[0, :] = d

            # Draw the history buffer now
            d = self.history_buffer
            axis_order = 'col-major'
            x_axis_idx, y_axis_idx = self._get_axis_idx(axis_order)

            x = np.arange(self.history_buffer.shape[0])
            y = np.arange(self.history_buffer.shape[1])

        else:
            raise ValueError('incompatible type')

        if self.pause_drawing:
            if self.redraw_once:
                self.redraw_once = False
            else:
                return

        if self.throttle_total > 0:
            if self.throttle_i < self.throttle_total:
                self.throttle_i += 1
                return

        z_scale = False

        if self.auto_z_scale:
            z_scale = True
        else:
            if self.scale_z_once:
                z_scale = True
                self.scale_z_once = False

        start = time.time()

        if axis_order != self.axis_order:
            self.imageItem.setOpts(axisOrder=axis_order)
            self.axis_order = axis_order

        self.imageItem.setCoordinates(x, y)
        self.displayImage.setImage(d, autoLevels=z_scale, autoRange=False)
        self.auto_z_scale = self.actionAutoScale.isChecked()
        end = time.time()

        draw_time = end - start

        if self.displayImage.roiCurves:
            roi_curve = self.displayImage.roiCurves[0]

            if roi_curve.xData is not None:
                self._notifyFittingCallbacks(roi_curve.xData, roi_curve.yData)

        if draw_time > 0.8/self.channel_rate:
            prev_throttle_total = self.throttle_total

            self.throttle_total = math.ceil(draw_time*self.channel_rate/0.8)+1
            self.throttle_i = 0

            if self.throttle_total != prev_throttle_total:
                print('Now skipping {0} frames'.format(self.throttle_total))

        else:
            if self.throttle_total > 0:
                print('Now longer skipping frames')
                self.throttle_total = 0

    def dataCleared(self):
        pass

    def addFittedCurve(self, tag, x, y):
        try:
            curve = self.fit_curves[tag]
        except KeyError:
            curve = self.displayImage.ui.roiPlot.plot(pen='y')
            self.fit_curves[tag] = curve

        curve.setData(x, y)

    def removeFittedCurve(self, tag):
        try:
            curve = self.fit_curves[tag]
        except KeyError:
            pass
        else:
            self.displayImage.ui.roiPlot.removeItem(curve)
            del self.fit_curves[tag]

    @staticmethod
    def isChannelSupported(channel):
        if not isinstance(channel, metro.DatagramChannel):
            raise ValueError('image only supports DatagramChannel')

        return True

    @metro.QSlot(bool)
    def on_actionPauseDrawing_toggled(self, flag):
        self.pause_drawing = flag
        self.actionRedrawOnce.setEnabled(flag)

    @metro.QSlot(bool)
    def on_actionRedrawOnce_triggered(self, flag):
        self.redraw_once = True

    @metro.QSlot(bool)
    def on_actionAutoScale_toggled(self, flag):
        self.auto_z_scale = flag
        self.actionRescaleOnce.setEnabled(not flag)

    @metro.QSlot(bool)
    def on_actionRescaleOnce_triggered(self, flag):
        self.scale_z_once = True

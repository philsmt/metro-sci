
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from itertools import repeat
import math
import time

import numpy as np
import xarray as xr
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets
import pyqtgraph
pyqtgraph.setConfigOptions(antialias=True)

import metro
from metro.devices.abstract import fittable_plot

# Create a default gradient, which is almost viridis. It adds a new
# lower bracket though for very small values (< 1e-3 relatively) which
# is pure black.
from pyqtgraph.graphicsItems.GradientEditorItem import Gradients

default_gradient = Gradients['viridis'].copy()
default_gradient['ticks'][0] = (1e-3, default_gradient['ticks'][0][1])
default_gradient['ticks'].insert(0, (0.0, (0, 0, 0, 255)))

from matplotlib import colormaps
ticks = np.linspace(0.0, 1.0, 20)

for cmap in ['RdBu', 'seismic', 'turbo']:
    Gradients[cmap] = {'mode': 'rgb', 'ticks': [
        (x, tuple(color))
        for x, color
        in zip(ticks, (colormaps[cmap](ticks, alpha=1.0, bytes=True)))
    ]}


class DataViewBox(pyqtgraph.ViewBox):
    def _get_last_data_z(self):
        for item in self.addedItems:
            if isinstance(item, DataImageItem):
                break
        else:
            return 'n/a'

        image = item.image

        if image is None:
            return 'n/a'

        x = int(self.last_data_pos.x())
        y = int(self.last_data_pos.y())

        if x < 0 or x >= image.shape[1] or y < 0 or y >= image.shape[0]:
            return 'n/a'

        return image[y, x]

    def raiseContextMenu(self, ev):
        menu = self.getMenu(ev)
        if menu is not None:
            # In newer pyqtgraph versions, a better implementation may
            # se GraphicsScene.sigMouseClicked and interact with
            # GraphicsScene.addParentContextMenus or QMenu.aboutToSHow().
            self.last_data_pos = self.mapSceneToView(ev.scenePos())

            menu.labelCoordX.setText(f'X: {self.last_data_pos.x()}')
            menu.labelCoordY.setText(f'Y: {self.last_data_pos.y()}')
            menu.labelCoordZ.setText(f'Z: {self._get_last_data_z()}')

            super().raiseContextMenu(ev)


class DataImageItem(pyqtgraph.ImageItem):
    def __init__(self, *args, **kwargs):
        # ImageView requires the image to be array-like when constructed
        # with an explicit (this) ImageItem.
        super().__init__(*args, image=np.zeros((1, 1)), **kwargs)

        self._coords = None

        self._local_marker_color = QtGui.QColor(200, 0, 0)
        self._remote_marker_color = QtGui.QColor(0, 0, 200)
        self._lines_color = QtGui.QColor(200, 200, 0)

        font = QtGui.QFont()
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setWeight(QtGui.QFont.Bold)
        font.setStretch(QtGui.QFont.Expanded)

        self._marker_font = font

        self.local_markers = {}
        self.remote_markers = {}
        self.vlines = None
        self.hlines = None
        self.rects = None
        self.ellipses = None

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

    def _drawMarkers(self, p, view, markers):
        flags = QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop
        for label, pos in markers:
            m = view.mapViewToDevice(pos)

            x = m.x()
            y = m.y()

            p.drawLine(QtCore.QPointF(x - 20, y), QtCore.QPointF(x + 20, y))
            p.drawLine(QtCore.QPointF(x, y - 20), QtCore.QPointF(x, y + 20))

            if label is not None:
                p.drawText(p.boundingRect(
                    QtCore.QRectF(x, y + 20, 1, 1), flags, label),
                    flags, label
                )

    def paint(self, p, *args):
        # Verbatim copy of ImageItem.paint() except for the actual
        # drawImage call.

        if self.image is None:
            return
        if self._renderRequired:
            self.render()
            if self._unrenderable:
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
        p.save()
        p.resetTransform()
        view = self.getViewBox()

        p.setPen(self._lines_color)

        if self.vlines is not None:
            height = p.device().geometry().height()
            flags = QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft

            if isinstance(self.vlines, dict):
                vlines_it = self.vlines.items()
            else:
                vlines_it = zip(self.vlines, repeat(None))

            for dx, text in vlines_it:
                rx = view.mapViewToDevice(QtCore.QPointF(dx, 0)).x()
                p.drawLine(QtCore.QPointF(rx, 0), QtCore.QPointF(rx, height))

                if text is not None:
                    p.drawText(p.boundingRect(
                        QtCore.QRectF(rx + 4, 4, 1, 1), flags, text),
                        flags, text)

        if self.hlines is not None:
            width = p.device().geometry().width()
            flags = QtCore.Qt.AlignTop | QtCore.Qt.AlignRight

            if isinstance(self.hlines, dict):
                hlines_it = self.hlines.items()
            else:
                hlines_it = zip(self.hlines, repeat(None))

            for dy, text in hlines_it:
                ry = view.mapViewToDevice(QtCore.QPointF(0, dy)).y()
                p.drawLine(QtCore.QPointF(0, ry), QtCore.QPointF(width, ry))

                if text is not None:
                    p.drawText(p.boundingRect(
                        QtCore.QRectF(width - 4, ry + 2, 1, 1), flags, text),
                        flags, text)

        if self.rects is not None:
            flags = QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft

            if isinstance(self.rects, dict):
                rects_it = self.rects.items()
            else:
                rects_it = zip(self.rects, repeat(None))

            for (x1, y1, x2, y2), text in rects_it:
                rect = QtCore.QRectF(
                    view.mapViewToDevice(QtCore.QPointF(x1, y1)),
                    view.mapViewToDevice(QtCore.QPointF(x2, y2)))

                p.drawRect(rect)

                if text is not None:
                    bl = rect.bottomLeft()
                    p.drawText(p.boundingRect(
                        int(bl.x()), int(bl.y()) + 1, 1, 1, flags, text
                    ), flags, text)

        if self.ellipses is not None:
            flags = QtCore.Qt.AlignTop | QtCore.Qt.AlignHCenter

            if isinstance(self.ellipses, dict):
                ellipses_it = self.ellipses.items()
            else:
                ellipses_it = zip(self.ellipses, repeat(None))

            for (x, y, *r), text in ellipses_it:
                if len(r) == 1:
                    r_x = r_y = r[0]
                elif len(r) > 1:
                    r_x, r_y = r[:2]

                rect = QtCore.QRectF(
                    view.mapViewToDevice(QtCore.QPointF(x - r_x, y - r_y)),
                    view.mapViewToDevice(QtCore.QPointF(x + r_x, y + r_y)))

                p.drawEllipse(rect)

                if text is not None:
                    p.drawText(p.boundingRect(
                        QtCore.QRectF(
                            rect.center().x(), rect.bottom() + 1, 1, 1),
                            flags, text),
                            flags, text)

        p.setFont(self._marker_font)

        p.setPen(self._local_marker_color)
        self._drawMarkers(p, view, self.local_markers.items())

        p.setPen(self._remote_marker_color)
        if isinstance(self.remote_markers, dict):
            self._drawMarkers(p, view, (
                (v, QtCore.QPointF(*k))
                for k, v in self.remote_markers.items()
            ))
        elif isinstance(self.remote_markers, list):
            self._drawMarkers(p, view, (
                (None, QtCore.QPointF(*x)) for x in self.remote_markers
            ))

        p.restore()


# Inject our own LUTWidget.
from metro.external.pyqtgraph.imageview \
    import ImageViewTemplate_pyqt5 as imageview_tpl

class DataHistogramLUTWidget(imageview_tpl.HistogramLUTWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paused_by_mouse = False

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)

        if not self._device.pause_drawing:
            self._device.pause_drawing = True
            self.paused_by_mouse = True

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)

        if self.paused_by_mouse:
            self._device.pause_drawing = False
            self.paused_by_mouse = False

imageview_tpl.HistogramLUTWidget = DataHistogramLUTWidget


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

        if state is None:
            state = {}
        elif not isinstance(state, dict):
            # Compatibility with tuple serialization.
            state = {
                'roi_state': state[0],
                'auto_scale': state[1],
                'gradient_scale': state[2],
            }

        self.viewBox = DataViewBox()
        self.plotItem = pyqtgraph.PlotItem(viewBox=self.viewBox)
        self.imageItem = DataImageItem()
        self.imageItem.setOpts(axisOrder=self.axis_order)

        self.displayImage = pyqtgraph.ImageView(
            self, view=self.plotItem, imageItem=self.imageItem)
        self.displayImage._opt_2d_parallel_profiles = True
        hist_widget = self.displayImage.getHistogramWidget()
        hist_widget.gradient.restoreState(
            state.get('gradient_state', default_gradient))

        levels = state.get('levels', None)
        if levels is not None:
            hist_widget.setLevels(*levels)

        hist_widget._device = self

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
            color='#0000BB', top=2, bottom=2))
        self.actionCoordY.setDefaultWidget(menu.labelCoordY)

        self.actionCoordZ = QtWidgets.QWidgetAction(menu)
        menu.labelCoordZ = QtWidgets.QLabel('')
        menu.labelCoordZ.setStyleSheet(label_css.format(
            color='#007700', top=0, bottom=2))
        self.actionCoordZ.setDefaultWidget(menu.labelCoordZ)

        self.actionAddMarker = QtGui.QAction('Add marker here', menu)
        self.actionAddMarker.triggered.connect(
            self.on_actionAddMarker_triggered)

        self.menuRemoveMarker = QtGui.QMenu('Remove marker', menu)
        self.menuRemoveMarker.triggered.connect(
            self.on_menuRemoveMarker_triggered)

        menu.insertSeparator(menu.actions()[0])
        menu.insertMenu(menu.actions()[0], self.menuRemoveMarker)
        menu.insertAction(menu.actions()[0], self.actionAddMarker)
        menu.insertAction(menu.actions()[0], self.actionCoordZ)
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
        self.actionAutoScale.setChecked(state.get('auto_scale', False))
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
        self.paused_by_hotkey = False
        self.scale_z_once = False

        # Always scale once in the beginning if no state were restored
        # from a prior state.
        self.auto_z_scale = levels is None

        self.history_buffer = None

        layout = metro.QtWidgets.QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.displayImage)
        self.setLayout(layout)

        self.channel_rate = 10

        self.fit_curves = {}

        roi_state = state.get('roi_state', None)
        if roi_state is not None:
            self.displayImage.roi.setPos(*roi_state[0])
            self.displayImage.roi.setSize(roi_state[1])
            self.displayImage.roi.setAngle(roi_state[2])

            if roi_state[3]:
                self.displayImage.ui.roiBtn.click()

        for label, (x, y) in state.get('markers', {}).items():
            self._addMarker(label, QtCore.QPointF(x, y))

        self.channel = args['channel']
        self.channel.subscribe(self)

    def finalize(self):
        del self.displayImage.getHistogramWidget()._device
        self.channel.unsubscribe(self)

    def serialize(self):
        roi = self.displayImage.roi.getState()
        roi_state = ((roi['pos'].x(), roi['pos'].y()),
                     (roi['size'].x(), roi['size'].y()),
                     roi['angle'], self.displayImage.ui.roiBtn.isChecked())

        hist_widget = self.displayImage.getHistogramWidget()

        return {
            'roi_state': roi_state,
            'auto_scale': self.actionAutoScale.isChecked(),
            'levels': hist_widget.getLevels(),
            'gradient_state': hist_widget.gradient.saveState(),
            'markers': {label: (p.x(), p.y()) for label, p
                        in self.imageItem.local_markers.items()}
        }

    def dataSet(self, d):
        pass

    def _addMarker(self, label, pos):
        self.imageItem.local_markers[label] = pos

        actionRemove = self.menuRemoveMarker.addAction(
            f'{label} ({pos.x():.6g}, {pos.y():.6g})')
        actionRemove.setData(label)

    @staticmethod
    def _get_axis_idx(axis_order):
        if axis_order == 'row-major':
            return 1, 0
        elif axis_order == 'col-major':
            return 0, 1

    def dataAdded(self, d):
        if self.history_streak > 0:
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

            # Axis coordinates
            x = np.arange(self.history_buffer.shape[0])

            if isinstance(d, xr.DataArray):
                y = d.coords[d.dims[0]].data
            else:
                y = np.arange(self.history_buffer.shape[1])

            # Draw the history buffer now
            d = self.history_buffer
            axis_order = 'col-major'
            x_axis_idx, y_axis_idx = self._get_axis_idx(axis_order)

        elif isinstance(d, xr.DataArray):
            axis_order = d.attrs.get('axis_order', self.axis_order)
            if axis_order not in Device.arguments['axis_order']:
                axis_order = self.axis_order

            x_axis_idx, y_axis_idx = self._get_axis_idx(axis_order)

            x = d.coords[d.dims[x_axis_idx]].data
            self.plotItem.setLabel('bottom', d.dims[x_axis_idx])
            y = d.coords[d.dims[y_axis_idx]].data
            self.plotItem.setLabel('left', d.dims[y_axis_idx])

            self.imageItem.remote_markers = d.attrs.get('markers', None)
            self.imageItem.vlines = d.attrs.get('vlines', None)
            self.imageItem.hlines = d.attrs.get('hlines', None)
            self.imageItem.rects = d.attrs.get('rects', None)
            self.imageItem.ellipses = d.attrs.get('ellipses', None)

            d = d.data

        elif isinstance(d, np.ndarray) and d.ndim == 2:
            axis_order = self.axis_order
            x_axis_idx, y_axis_idx = self._get_axis_idx(axis_order)

            x = np.arange(d.shape[x_axis_idx])
            y = np.arange(d.shape[y_axis_idx])

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
        self.displayImage.clear()
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

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Control and not self.pause_drawing:
            self.pause_drawing = True
            self.paused_by_hotkey = True

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key_Control and self.paused_by_hotkey:
            self.pause_drawing = False
            self.paused_by_hotkey = False

    @metro.QSlot(bool)
    def on_actionAddMarker_triggered(self, flag):
        text, confirmed = QtWidgets.QInputDialog.getText(
            None, self.windowTitle(), 'Name for new marker'
        )

        if not confirmed or not text:
            return

        if text in self.imageItem.local_markers:
            self.showError('A marker with that name already exists.')
            return

        self._addMarker(text, self.viewBox.last_data_pos)

    # Should be @metro.QSlot(QtCore.QAction)
    def on_menuRemoveMarker_triggered(self, action):
        self.imageItem.local_markers.pop(action.data(), None)
        self.menuRemoveMarker.removeAction(action)

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

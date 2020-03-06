
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from math import ceil, floor, log10

import numpy
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets

try:
    import lttbc
except ImportError:
    lttbc = None

import metro
from metro.devices.abstract import fittable_plot

from . import _fast_plot_native as _native

QtConsts = QtCore.Qt


COLOR_STYLES = {
    'default': [
        ((180, 180, 255), (0, 0, 200)),
        ((180, 255, 180), (0, 200, 0)),
        ((255, 180, 180), (200, 0, 0)),
        ((64, 224, 208), (0, 102, 153)),
        ((204, 102, 255), (153, 0, 204)),
    ],

    'mpl': [
        (0x1F, 0x77, 0xB4), (0xFF, 0x7F, 0x0E), (0x2C, 0xA0, 0x2C),
        (0xD6, 0x27, 0x28), (0x94, 0x67, 0xBD), (0x8C, 0x56, 0x4B),
        (0xE3, 0x77, 0xC2), (0x7F, 0x7F, 0x7F), (0xBC, 0xBD, 0x22),
        (0x17, 0xBE, 0xCF)
    ],

    'blue': [
        ((180, 180, 255), (0, 0, 200))
    ],

    'blueShaded': [
        ((180, 180, 255, 150), (0, 0, 200))
    ],
}


class RenderOperator(QtCore.QObject):
    renderingCompleted = metro.QSignal()

    def __init__(self, in_device):
        super().__init__()

        self.dev = in_device
        self.running = False

    @metro.QSlot()
    def render(self):
        self.running = True

        _native.surface_clear(self.dev.surface)

        n_colors = len(self.dev.style)

        dev = self.dev

        if dev.idx_data is not None:
            for i in reversed(range(dev.idx_data.shape[0])):
                try:
                    _native.plot(dev.surface,
                                 *dev.downsample(dev.x, dev.idx_data[i]),
                                 i % n_colors, dev.show_marker)
                except ValueError:
                    print(dev.x.shape, dev.idx_data.shape)

        for data in dev.fit_data.values():
            _native.plot(dev.surface, data, 5, False)

        self.renderingCompleted.emit()
        self.running = False


class Device(metro.WidgetDevice, metro.DisplayDevice, fittable_plot.Device):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(),
        'index': metro.IndexArgument(),
        'bg_text': '',
        'mt_render': False,
        'style': tuple(COLOR_STYLES.keys()),
        'with_x': False,
        'show_marker': True,
        'show_legend': False,
        'downsampling': 0,
    }

    MOUSE_MOVE_PLOT_BEGIN = 0
    MOUSE_MOVE_PLOT_ON = 1
    MOUSE_MOVE_PLOT_X_BEGIN = 2
    MOUSE_MOVE_PLOT_X_ON = 3
    MOUSE_MOVE_PLOT_Y_BEGIN = 4
    MOUSE_MOVE_PLOT_Y_ON = 5
    MOUSE_MOVE_ROI = 6
    MOUSE_MOVE_ROI_LEDGE = 7
    MOUSE_MOVE_ROI_REDGE = 8

    renderingRequested = metro.QSignal()

    def prepare(self, args, state):
        self.style = COLOR_STYLES[args['style']]
        self.with_x = args['with_x']

        self.channel = args['channel']
        self.roi_map = {}

        self.has_metropc_tags = hasattr(self.channel, '_metropc_tags')

        self.stacking_outp = None

        self.axes_texts = []
        self.axes_lines = []
        self.roi_rect = None
        self.roi_lines = []

        self.surface = _native.surface_new()

        self.x = None
        self.ch_data = None
        self.idx_data = None
        self.fit_data = {}

        self.data_img = None

        self.plot_geometry = numpy.zeros((4,), dtype=numpy.int32)
        self.plot_roi = numpy.zeros((2,), dtype=numpy.int32)
        self.plot_transform = numpy.zeros((2,), dtype=numpy.float64)

        if state is None:
            state = {}

        self.index = metro.IndexArgument._str2index(state['index']) \
            if 'index' in state else args['index']
        self.plot_axes = numpy.asarray(state['axes'], dtype=numpy.float64) \
            if 'axes' in state \
            else numpy.array((0.0, 10.0, 0.0, 10.0), dtype=numpy.float64)

        plot_title = state.pop('title',
                               args['bg_text'] if args['bg_text']
                               else self._getDefaultTitle())
        self.current_roi = state.pop('current_roi', None)
        self.autoscale_x = state.pop('autoscale_x', True)
        self.autoscale_y = state.pop('autoscale_y', True)
        self.stacking = state.pop('stacking', 0.0)
        self.show_marker = state.pop('show_marker', args['show_marker'])
        self.show_legend = state.pop(
            'show_legend', args['show_legend'] and self.has_metropc_tags)
        self.downsampling = state.pop('downsampling', args['downsampling'])

        if lttbc is None:
            self.downsampling = 0

        self.timerResize = metro.QTimer(self)
        self.timerResize.setInterval(500)
        self.timerResize.setSingleShot(True)
        self.timerResize.timeout.connect(self.on_timerResize_timeout)

        self.axis_color = QtGui.QColor(150, 150, 150)
        self.axis_pen = QtGui.QPen(self.axis_color)

        self.roi_edgecolor = QtGui.QColor(200, 200, 0)
        self.roi_facecolor = QtGui.QColor(150, 150, 0, 80)

        self.mouse_move_origin = None
        self.mouse_move_roi = None
        self.mouse_move_axes = None
        self.mouse_move_mode = 0

        self.title_text = None
        self.title_bbox = None
        self.title_font = None
        self.title_color = QtGui.QColor(255, 70, 70, 60)

        self.menuContext = QtWidgets.QMenu()
        self.menuContext.triggered.connect(self.on_menuContext_triggered)

        self.actionIndexEdit = self.menuContext.addAction('Edit index...')
        self.actionTitleEdit = self.menuContext.addAction('Edit title...')

        self.menuContext.addSeparator()

        self.actionViewAll = self.menuContext.addAction('View all')

        self.menuAxisX = self.menuContext.addMenu('X axis')
        self.groupAxisX = QtWidgets.QActionGroup(self.menuAxisX)

        self.actionAxisX_Auto = self.menuAxisX.addAction('Auto')
        self.actionAxisX_Auto.setCheckable(True)
        self.actionAxisX_Auto.setChecked(self.autoscale_x)
        self.groupAxisX.addAction(self.actionAxisX_Auto)

        self.actionAxisX_Manual = self.menuAxisX.addAction('Manual...')
        self.actionAxisX_Manual.setCheckable(True)
        self.actionAxisX_Manual.setChecked(not self.autoscale_x)
        self.groupAxisX.addAction(self.actionAxisX_Manual)

        self.menuAxisX.addSeparator()

        self.menuAxisX_copyFrom = self.menuAxisX.addMenu('Copy from')
        self.menuAxisX_copyFrom.aboutToShow.connect(
            self.on_menuAxisX_copyFrom_aboutToShow
        )
        self.menuAxisX_copyFrom.triggered.connect(
            self.on_menuAxisX_copyFrom_triggered
        )

        self.menuAxisY = self.menuContext.addMenu('Y axis')
        self.groupAxisY = QtWidgets.QActionGroup(self.menuAxisY)

        self.actionAxisY_Auto = self.menuAxisY.addAction('Auto')
        self.actionAxisY_Auto.setCheckable(True)
        self.actionAxisY_Auto.setChecked(self.autoscale_y)
        self.groupAxisY.addAction(self.actionAxisY_Auto)

        self.actionAxisY_Manual = self.menuAxisY.addAction('Manual...')
        self.actionAxisY_Manual.setCheckable(True)
        self.actionAxisY_Manual.setChecked(not self.autoscale_y)
        self.groupAxisY.addAction(self.actionAxisY_Manual)

        self.menuAxisY.addSeparator()

        self.menuAxisY_copyFrom = self.menuAxisY.addMenu('Copy from')
        self.menuAxisY_copyFrom.aboutToShow.connect(
            self.on_menuAxisY_copyFrom_aboutToShow
        )
        self.menuAxisY_copyFrom.triggered.connect(
            self.on_menuAxisY_copyFrom_triggered
        )

        if lttbc is not None:
            self.menuContext.addSeparator()

            self.menuDownsampling = self.menuContext.addMenu('Downsampling')
            self.menuDownsampling.triggered.connect(
                self.on_menuDownsampling_triggered)

            self.groupDownsampling = QtWidgets.QActionGroup(
                self.menuDownsampling)

            self.actionDownsamplingNone = self.menuDownsampling.addAction(
                'Disabled')
            self.actionDownsamplingNone.setCheckable(True)
            self.actionDownsamplingNone.setChecked(self.downsampling == 0)
            self.groupDownsampling.addAction(self.actionDownsamplingNone)

            self.actionDownsamplingGeometry = self.menuDownsampling.addAction(
                'Geometry')
            self.actionDownsamplingGeometry.setCheckable(True)
            self.actionDownsamplingGeometry.setChecked(self.downsampling == -1)
            self.groupDownsampling.addAction(self.actionDownsamplingGeometry)

            self.actionDownsamplingCustom = self.menuDownsampling.addAction(
                'Custom...')
            self.actionDownsamplingCustom.setCheckable(True)
            self.actionDownsamplingCustom.setChecked(self.downsampling > 0)
            self.groupDownsampling.addAction(self.actionDownsamplingCustom)

        self.menuContext.addSeparator()

        self.actionStacking = self.menuContext.addAction('Stacking...')

        self.menuContext.addSeparator()

        self.menuRoi = self.menuContext.addMenu('Show ROI')
        self.menuRoi.triggered.connect(self.on_menuRoi_triggered)

        self.groupRoi = QtWidgets.QActionGroup(self.menuRoi)

        self.actionRoiNone = self.menuRoi.addAction('none')
        self.actionRoiNone.setCheckable(True)
        self.actionRoiNone.setChecked(self.current_roi is None)

        self.groupRoi.addAction(self.actionRoiNone)

        self.menuContext.addSeparator()

        self.actionShowMarker = self.menuContext.addAction(
            'Show point markers')
        self.actionShowMarker.setCheckable(True)
        self.actionShowMarker.setChecked(self.show_marker)

        if self.has_metropc_tags:
            self.actionShowLegend = self.menuContext.addAction(
                'Show scan legend')
            self.actionShowLegend.setCheckable(True)
            self.actionShowLegend.setChecked(self.show_legend)

        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.on_menuContext_requested)

        self._setTitle(plot_title)
        self.setStyleSheet('background-color: black;')

        if args['mt_render']:
            self.render_thread = metro.QThread(self)
            self.render_operator = RenderOperator(self)
            self.render_operator.moveToThread(self.render_thread)

            self.renderingRequested.connect(self.render_operator.render)
            self.render_operator.renderingCompleted.connect(
                self.on_render_completed
            )

            self.render_thread.start()

        else:
            self.render_thread = None

        try:
            rois = self.channel._rois.items()
        except AttributeError:
            self.menuRoi.setEnabled(False)
        else:
            for name, roi in rois:
                new_action = self.menuRoi.addAction(name)
                new_action.setCheckable(True)
                new_action.setChecked(self.current_roi == name)
                self.groupRoi.addAction(new_action)

            metro.channels.watch(self, channel=self.channel, callbacks=[
                'roiChanged_add', 'roiChanged_delete', 'roiChanged_remote'
            ])

        self.channel.subscribe(self)

        if self.current_roi is not None:
            self._setCurrentRoi()

    def finalize(self):
        if self.render_thread is not None:
            self.render_thread.quit()
            self.render_thread.wait()

            self.render_operator.dev = None
            self.render_operator = None

        self.channel.unsubscribe(self)

        try:
            self.channel._rois
        except AttributeError:
            pass
        else:
            metro.channels.unwatch(self)

        _native.surface_delete(self.surface)

    def serialize(self):
        return {
            'index': metro.IndexArgument._index2str(self.index),
            'current_roi': self.current_roi,
            'title': self.title_text,
            'autoscale_x': self.autoscale_x,
            'autoscale_y': self.autoscale_y,
            'axes': self.plot_axes.tolist(),
            'stacking': self.stacking,
            'show_marker': self.show_marker,
            'show_legend': self.show_legend,
            'downsampling': self.downsampling
        }

    def sizeHint(self):
        return QtCore.QSize(520, 200)

    def resizeEvent(self, event):
        if self.data_img is None:
            self.on_timerResize_timeout()
        else:
            self.timerResize.start()

    def mousePressEvent(self, event):
        x = event.x()
        y = event.y()

        if self.roi_rect is not None and self.roi_rect.contains(x, y):
            edge_width = min(0.2 * self.roi_rect.width(), 10)

            if (x - self.roi_rect.left()) < edge_width:
                self.mouse_move_mode = self.MOUSE_MOVE_ROI_LEDGE
            elif (self.roi_rect.right() - x) < edge_width:
                self.mouse_move_mode = self.MOUSE_MOVE_ROI_REDGE
            else:
                self.mouse_move_mode = self.MOUSE_MOVE_ROI

            self.mouse_move_roi = self.plot_roi.copy()

        else:
            if x < self.plot_geometry[0]:
                self.mouse_move_mode = self.MOUSE_MOVE_PLOT_Y_BEGIN
            elif y > self.size().height() - self.plot_geometry[1]:
                self.mouse_move_mode = self.MOUSE_MOVE_PLOT_X_BEGIN
            else:
                self.mouse_move_mode = self.MOUSE_MOVE_PLOT_BEGIN

            self.mouse_move_axes = self.plot_axes.copy()

        self.mouse_move_origin = event.pos()

    def mouseReleaseEvent(self, event):
        if self.mouse_move_origin is None:
            return

        if self.mouse_move_mode >= self.MOUSE_MOVE_ROI:
            self.channel._rois[self.current_roi][self.index, :] = self.plot_roi
            self.channel._notify('roiChanged_remote')

        self.mouse_move_origin = None
        self.mouse_move_roi = None

    def mouseMoveEvent(self, event):
        if self.mouse_move_origin is None:
            return

        dx = int((event.x() - self.mouse_move_origin.x()) /
                 self.plot_transform[0])
        dy = int((event.y() - self.mouse_move_origin.y()) /
                 self.plot_transform[1])

        if self.mouse_move_mode == self.MOUSE_MOVE_PLOT_BEGIN:
            self.mouse_move_mode = self.MOUSE_MOVE_PLOT_ON
            self._axisChanged_manual(True, True)

        elif self.mouse_move_mode == self.MOUSE_MOVE_PLOT_X_BEGIN:
            self.mouse_move_mode = self.MOUSE_MOVE_PLOT_X_ON
            self._axisChanged_manual(True, False)

        elif self.mouse_move_mode == self.MOUSE_MOVE_PLOT_Y_BEGIN:
            self.mouse_move_mode = self.MOUSE_MOVE_PLOT_Y_ON
            self._axisChanged_manual(False, True)

        if self.mouse_move_mode == self.MOUSE_MOVE_PLOT_ON:
            self.plot_axes[0:2] = self.mouse_move_axes[0:2] - dx
            self.plot_axes[2:4] = self.mouse_move_axes[2:4] + dy

        elif self.mouse_move_mode == self.MOUSE_MOVE_PLOT_X_ON:
            self.plot_axes[0:2] = self.mouse_move_axes[0:2] - dx

        elif self.mouse_move_mode == self.MOUSE_MOVE_PLOT_Y_ON:
            self.plot_axes[2:4] = self.mouse_move_axes[2:4] + dy

        elif self.mouse_move_mode == self.MOUSE_MOVE_ROI:
            self.plot_roi = self.mouse_move_roi + dx

        elif self.mouse_move_mode == self.MOUSE_MOVE_ROI_REDGE:
            self.plot_roi[1] = self.mouse_move_roi[1] + dx

        elif self.mouse_move_mode == self.MOUSE_MOVE_ROI_LEDGE:
            self.plo_roi[0] = self.mouse_move_roi[0] + dx

        self.repaint(axes_changed=True)

    def wheelEvent(self, event):
        x = event.x()
        y = event.y()
        height = self.size().height()

        if x < self.plot_geometry[0]:
            scale_x = False
            scale_y = True
        elif y > height - self.plot_geometry[1]:
            scale_x = True
            scale_y = False
        else:
            scale_x = True
            scale_y = True

        delta = event.angleDelta().y()
        delta /= 20

        interval_x = (self.plot_axes[1] - self.plot_axes[0]) / delta
        interval_y = (self.plot_axes[3] - self.plot_axes[2]) / delta

        rel_x = (x - self.plot_geometry[0]) / self.plot_geometry[2]
        rel_y = ((height - y) - self.plot_geometry[1]) / self.plot_geometry[3]

        if scale_x and interval_x != 0:
            self.plot_axes[0] += rel_x * interval_x
            self.plot_axes[1] -= (1 - rel_x) * interval_x

        if scale_y and interval_y != 0:
            self.plot_axes[2] += rel_y * interval_y
            self.plot_axes[3] -= (1 - rel_y) * interval_y

        self._axisChanged_manual(scale_x, scale_y)

        self.repaint(axes_changed=True)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)

        if self.title_text is not None:
            p.save()
            p.setPen(self.title_color)
            p.setFont(self.title_font)
            p.drawText(self.title_bbox, QtConsts.AlignRight, self.title_text)
            p.restore()

        p.drawImage(self.rect(), self.data_img)
        p.setPen(self.axis_pen)

        p.save()
        font = p.font()
        font.setStretch(80)
        p.setFont(font)

        if not self.axes_texts:
            self._buildAxes(p)

        for text in self.axes_texts:
            p.drawText(text, text._flags, text._str)

        p.restore()

        if self.show_legend:
            p.save()

            font = p.font()
            font.setBold(True)
            p.setFont(font)

            x = self.width() - 8
            y = 12
            flags = QtConsts.AlignVCenter | QtConsts.AlignRight

            for i, tag in enumerate(self.channel._metropc_tags):
                color_idx = ((i % len(self.style)) + 1) * 10 + 2
                tag_str = '{:.5g}'.format(tag) \
                          if isinstance(tag, float) else str(tag)

                p.setPen(QtGui.QColor(self.data_img.color(color_idx)))
                p.drawText(p.boundingRect(x, y, 1, 1, flags, tag_str), flags,
                           tag_str)

                y += 15

            p.restore()

        p.drawLines(self.axes_lines)

        if self.roi_rect is not None:
            p.setPen(self.roi_edgecolor)
            p.drawLines(self.roi_lines)

            p.fillRect(self.roi_rect, self.roi_facecolor)

        p.end()

    def downsample(self, x, y):
        if self.downsampling == 0:
            return x, y

        elif self.downsampling == -1:
            threshold = self.plot_geometry[2]*2

        else:
            threshold = self.downsampling

        return lttbc.downsample(x, y, threshold)

    def repaint(self, axes_changed=False, data_changed=False,
                roi_changed=False, title_changed=False):

        if axes_changed:
            data_changed = True
            roi_changed = True

            self.axes_texts.clear()

            self.plot_transform[0] = (self.plot_geometry[2] /
                                      (self.plot_axes[1] - self.plot_axes[0]))
            self.plot_transform[1] = (self.plot_geometry[3] /
                                      (self.plot_axes[3] - self.plot_axes[2]))

            _native.surface_set_view(self.surface, self.plot_axes,
                                     self.plot_transform)

        if data_changed and self.data_img is not None:
            if self.render_thread is not None:
                if not self.render_operator.running:
                    self.renderingRequested.emit()

            else:
                _native.surface_clear(self.surface)

                if self.idx_data is not None:
                    for i in reversed(range(self.idx_data.shape[0])):
                        _native.plot(
                            self.surface,
                            *self.downsample(self.x, self.idx_data[i]),
                            i % len(self.style), self.show_marker
                        )

                for data in self.fit_data.values():
                    _native.plot(self.surface, data, 5, False)

        if roi_changed:
            self.roi_lines.clear()

            # First check if there is actually anything visible
            is_visible = not(self.plot_roi[1] < self.plot_axes[0] or
                             self.plot_roi[0] > self.plot_axes[1])

            if self.current_roi is not None and is_visible:
                start = max(self.plot_axes[0], self.plot_roi[0])
                end = min(self.plot_axes[1], self.plot_roi[1])

                self.roi_rect = QtCore.QRect(
                    (start - self.plot_axes[0]) * self.plot_transform[0] +
                    self.plot_geometry[0],
                    self.size().height() - self.plot_geometry[1],
                    (end - start) * self.plot_transform[0],
                    -self.plot_geometry[3]
                )

                if self.plot_roi[0] > self.plot_axes[0]:
                    self.roi_lines.append(QtCore.QLineF(
                        self.roi_rect.topLeft(), self.roi_rect.bottomLeft())
                    )

                if self.plot_roi[1] < self.plot_axes[1]:
                    self.roi_lines.append(QtCore.QLineF(
                        self.roi_rect.topRight(), self.roi_rect.bottomRight())
                    )

        if title_changed:
            stretch = 100
            point_size = 30
            max_width = self.width() - 100

            if max_width <= 0:
                return

            while True:
                font = QtGui.QFont()
                font.setStyleHint(QtGui.QFont.SansSerif)
                font.setStretch(stretch)
                font.setPointSize(point_size)

                metric = QtGui.QFontMetrics(font)
                bbox = metric.boundingRect(self.title_text)

                if bbox.width() > max_width:
                    if stretch > 70:
                        stretch -= 5
                    else:
                        point_size -= 1
                else:
                    break

            self.title_bbox = QtCore.QRect(0, 30, self.width() - 30,
                                           bbox.height())
            self.title_font = font

        if self.render_thread is None:
            super().repaint()

    @metro.QSlot()
    def on_render_completed(self):
        super().repaint()

    def _buildAxisLabel(self, value, x, y, p, flags):
        text = str(value)

        r = p.boundingRect(x, y, 1, 1, flags, text)
        r._flags = flags
        r._str = text

        self.axes_texts.append(r)

        return r

    def _computeTicks(self, start, end, offset, div, max_ticks, minor_ticks,
                      label_fmt):
        interval = max(1, end - start)
        frac = interval / max_ticks

        dim = floor(log10(frac))
        tick = pow(10, dim)

        while interval // tick > max_ticks:
            tick += 10**dim

        value = ceil(start / tick) * tick
        labels = [value]
        major_pos = [(value - start) * div + offset]
        minor_pos = []

        while True:
            for i in range(1, minor_ticks+1):
                minor_pos.append((value + tick*(i/(minor_ticks+1)) - start)
                                 * div + offset)

            value = value + tick

            if value > end:
                break

            labels.append(label_fmt.format(value))
            major_pos.append((value - start) * div + offset)

        return labels, major_pos, minor_pos

    def _computeTicksForAxis(self, idx, max_ticks, minor_ticks, label_fmt):
        start = self.plot_axes[2 * idx]
        end = self.plot_axes[2 * idx + 1]
        offset = self.plot_geometry[idx]
        div = self.plot_transform[idx]

        return self._computeTicks(start, end, offset, div, max_ticks,
                                  minor_ticks, label_fmt)

    def _buildAxes(self, p):
        # Probably unnecessary
        self.axes_texts.clear()
        self.axes_lines.clear()

        offset_x = self.plot_geometry[0]
        offset_y = self.plot_geometry[1]
        height = self.size().height()

        # X axis
        labels_x, major_pos_x, minor_pos_x = self._computeTicksForAxis(
            0, self.plot_geometry[2] // 40, 3, '{:g}'
        )
        flags = QtConsts.AlignHCenter | QtConsts.AlignTop

        prev_r = None

        for i in range(len(labels_x)):
            r = self._buildAxisLabel(labels_x[i], major_pos_x[i],
                                     height - offset_y + 4, p, flags)

            if prev_r is not None and r.left()-5 < prev_r.right():
                self.axes_texts.remove(r)
            else:
                prev_r = r

            self.axes_lines.append(QtCore.QLineF(
                major_pos_x[i], height - offset_y + 2, major_pos_x[i],
                height - offset_y - 5
            ))

        for minor_x in minor_pos_x:
            self.axes_lines.append(QtCore.QLineF(
                minor_x, height - offset_y, minor_x, height - offset_y - 3
            ))

        self.axes_lines.append(QtCore.QLineF(
            offset_x, height - offset_y,
            offset_x + self.plot_geometry[2], height - offset_y
        ))

        # Y axis
        labels_y, major_pos_y, minor_pos_y = self._computeTicksForAxis(
            1, self.plot_geometry[3] // 25, 3, '{:.3g}'
        )
        flags = QtConsts.AlignVCenter | QtConsts.AlignRight

        for i in range(len(labels_y)):
            self._buildAxisLabel(labels_y[i], offset_x - 6,
                                 height - major_pos_y[i], p, flags)
            self.axes_lines.append(QtCore.QLineF(
                offset_x, height - major_pos_y[i], offset_x + 5,
                height - major_pos_y[i]
            ))

        for minor_y in minor_pos_y:
            self.axes_lines.append(QtCore.QLineF(
                offset_x, height - minor_y, offset_x + 2, height - minor_y
            ))

        self.axes_lines.append(QtCore.QLineF(
            offset_x, height - offset_y,
            offset_x, height - offset_y - self.plot_geometry[3]
        ))

    def _axisChanged_manual(self, axisX_changed, axisY_changed):
        if axisX_changed and self.actionAxisX_Auto.isChecked():
            self.actionAxisX_Manual.setChecked(True)
            self.autoscale_x = False

        if axisY_changed and self.actionAxisY_Auto.isChecked():
            self.actionAxisY_Manual.setChecked(True)
            self.autoscale_y = False

    def _getDefaultTitle(self):
        plot_title = self.channel.name

        if self.index != metro.IndexArgument.fullIndex:
            plot_title += '/' + metro.IndexArgument._index2str(self.index)

        return plot_title

    def _setTitle(self, title):
        self.setWindowTitle('{0} - {1}'.format(title, self._name))
        self.title_text = title

    def _setCurrentRoi(self, roi_name=None):
        if roi_name is not None:
            self.current_roi = roi_name

        try:
            roi = self.channel._rois[self.current_roi][self.index, :]
        except AttributeError:
            self.roi_rect = None
        else:
            if len(roi.shape) > 1:
                roi = roi[0]

            self.plot_roi = roi
            self.repaint(roi_changed=True)

    def _createAxisDialog(self, axis_limits, axis_name):
        dialog = self.createDialog('axis')
        dialog.setParent(None)
        dialog.labelText.setText(dialog.labelText.text().replace('{axis}',
                                                                 axis_name))
        dialog.editStart.setText(str(axis_limits[0]))
        dialog.editEnd.setText(str(axis_limits[1]))
        dialog.exec_()

        if dialog.result() != QtWidgets.QDialog.Accepted:
            return None

        try:
            start = float(dialog.editStart.text())
            end = float(dialog.editEnd.text())
        except ValueError:
            return None

        return start, end

    @metro.QSlot()
    def on_timerResize_timeout(self):
        new_width = self.size().width()
        new_height = self.size().height()

        self.data_img = QtGui.QImage(new_width, new_height,
                                     QtGui.QImage.Format_Indexed8)

        self.data_img.setColor(0, QtGui.qRgba(0, 0, 0, 0))
        self.data_img.setColor(1, self.axis_color.rgb())

        def qtColor(color):
            n_vals = len(color)

            if n_vals == 3:
                return QtGui.qRgb(*color)
            elif n_vals == 4:
                return QtGui.qRgba(*color)

        for i, color in enumerate(self.style):
            color_idx = (i+1) * 10 + 1

            if len(color) == 2 and isinstance(color[0], tuple):
                self.data_img.setColor(color_idx, qtColor(color[0]))
                self.data_img.setColor(color_idx+1, qtColor(color[1]))
            else:
                self.data_img.setColor(color_idx, qtColor(color))
                self.data_img.setColor(color_idx+1, qtColor(color))

        self.data_img.fill(0)

        self.plot_geometry[0] = 50
        self.plot_geometry[1] = 20
        self.plot_geometry[2] = new_width - 60
        self.plot_geometry[3] = new_height - 30

        _native.surface_set_geometry(
            self.surface, self.data_img.bits(), self.data_img.bytesPerLine(),
            new_height, self.plot_geometry
        )

        self.repaint(True, True, True, True)

    @metro.QSlot(QtCore.QPoint)
    def on_menuContext_requested(self, pos):
        self.menuContext.popup(self.mapToGlobal(pos))

    # @metro.QSlot(QtCore.QAction)
    def on_menuContext_triggered(self, action):
        if action == self.actionIndexEdit:
            text, confirmed = QtWidgets.QInputDialog.getText(
                None, self.windowTitle(), 'Index',
                text=metro.IndexArgument._index2str(self.index)
            )

            if not confirmed:
                return

            is_default_title = self.title_text == self._getDefaultTitle()

            try:
                self.index = metro.IndexArgument._str2index(text)
            except Exception as e:
                self.showException(e)

            if is_default_title:
                self._setTitle(self._getDefaultTitle())

            self.dataAdded(self.ch_data)

        elif action == self.actionTitleEdit:
            text, confirmed = QtWidgets.QInputDialog.getText(
                None, self.windowTitle(), 'Title',
                text=self.title_text
            )

            if not confirmed:
                return

            if not text:
                text = self._getDefaultTitle()

            self._setTitle(text)
            self.repaint(title_changed=True)

        elif action == self.actionViewAll:
            self.autoscale_x = True
            self.autoscale_y = True

            self.actionAxisX_Auto.setChecked(True)
            self.actionAxisY_Auto.setChecked(True)

            self.repaint(axes_changed=True)

        elif action == self.actionAxisX_Auto:
            self.autoscale_x = True
            self.repaint(axes_changed=True)

        elif action == self.actionAxisX_Manual:
            self.autoscale_x = False

            limits = self._createAxisDialog(self.plot_axes[0:2], 'X')

            if limits is None:
                return

            self.plot_axes[0:2] = limits
            self.repaint(axes_changed=True)

        elif action == self.actionAxisY_Auto:
            self.autoscale_y = True
            self.repaint(axes_changed=True)

        elif action == self.actionAxisY_Manual:
            self.autoscale_y = False

            limits = self._createAxisDialog(self.plot_axes[2:4], 'Y')

            if limits is None:
                return

            self.plot_axes[2:4] = limits
            self.repaint(axes_changed=True)

        elif action == self.actionStacking:
            value, confirmed = QtWidgets.QInputDialog.getDouble(
                None, self.windowTitle(), 'Number of channels after which '
                'the signal is stacked onto itself (0 disables stacking)\n'
                'WARNING: This method assumes the data points are '
                'equidistant!',
                value=self.stacking, min=0.0, decimals=3
            )

            if not confirmed:
                return

            if self.stacking == value:
                return

            self.stacking = value
            self.stacking_outp = None

            self.dataAdded(self.ch_data)

        elif action == self.actionShowMarker:
            self.show_marker = self.actionShowMarker.isChecked()
            self.repaint(data_changed=True)

        elif action == self.actionShowLegend:
            self.show_legend = self.actionShowLegend.isChecked()
            super().repaint()  # Trigger direct repaint as nothing is cached.

    # @metro.QSlot(QtCore.QAction)
    def on_menuDownsampling_triggered(self, action):
        orig_downsampling = self.downsampling

        if action == self.actionDownsamplingNone:
            self.downsampling = 0

        elif action == self.actionDownsamplingGeometry:
            self.downsampling = -1

        elif action == self.actionDownsamplingCustom:
            value, confirmed = QtWidgets.QInputDialog.getInt(
                None, self.windowTitle(), 'Number of samples to downsample to',
                value=self.downsampling, min=10,
            )

            if not confirmed:
                return

            if self.downsampling == value:
                return

            self.downsampling = value

        if orig_downsampling != self.downsampling:
            self.repaint(data_changed=True)

    # @metro.QSlot(QtCore.QAction)
    def on_menuRoi_triggered(self, action):
        self._setCurrentRoi(action.text() if action != self.actionRoiNone
                            else None)

    def _onMenuAxis_copyFrom_aboutToShow(self, menu):
        menu.clear()

        my_cls = self.__class__

        for dev in metro.getAllDevices():
            # Not sure why isinstance is not working properly for newly
            # loaded devices?! For now we can safely check for the
            # module name, but that's not really a solution.
            if dev is not self and dev.__class__ == my_cls:
                menu.addAction(f'{dev.title_text} ({dev._name})') \
                    .setData(dev._name)

    def on_menuAxisX_copyFrom_aboutToShow(self):
        self._onMenuAxis_copyFrom_aboutToShow(self.menuAxisX_copyFrom)

    def on_menuAxisY_copyFrom_aboutToShow(self):
        self._onMenuAxis_copyFrom_aboutToShow(self.menuAxisY_copyFrom)

    def _onMenuAxis_copyFrom_triggered(self, action, axes_slice):
        copied_device = metro.getDevice(action.data())

        self.plot_axes[axes_slice] = copied_device.plot_axes[axes_slice]
        self.repaint(axes_changed=True)

    def on_menuAxisX_copyFrom_triggered(self, action):
        self._onMenuAxis_copyFrom_triggered(action, slice(0, 2))
        self.autoscale_x = False

    def on_menuAxisY_copyFrom_triggered(self, action):
        self._onMenuAxis_copyFrom_triggered(action, slice(2, 4))
        self.autoscale_y = False

    def roiChanged_remote(self, channel_name):
        if self.current_roi is not None:
            self._setCurrentRoi()

    def roiChanged_add(self, channel_name):
        roi_actions = [action.text() for action in self.menuRoi.actions()]

        for name, roi in self.channel._rois.items():
            if name not in roi_actions:
                new_action = self.menuRoi.addAction(name)
                new_action.setCheckable(True)
                new_action.setChecked(False)
                self.groupRoi.addAction(new_action)

    def roiChanged_delete(self, channel_name):
        roi_names = self.channel._rois.keys()

        for action in self.menuRoi.actions():
            name = action.text()

            if name and name != 'none' and name not in roi_names:
                self.menuRoi.removeAction(action)
                self.groupRoi.removeAction(action)

                if name == self.current_roi:
                    self.actionRoiNone.trigger()

    @classmethod
    def isChannelSupported(self, ch):
        return True

    def dataSet(self, d):
        pass

    def dataAdded(self, d):
        self.ch_data = d
        self.idx_data = d[self.index]

        if len(self.idx_data.shape) == 1:
            self.idx_data = self.idx_data[None, :]

        if self.with_x and self.idx_data.shape[0] > 1:
            self.x = self.idx_data[0]
            self.idx_data = self.idx_data[1:]
        else:
            self.x = numpy.arange(self.idx_data.shape[1])

        self._notifyFittingCallbacks(self.x, self.idx_data[0])

        if self.stacking > 0.0:
            if self.stacking_outp is None:
                self.stacking_outp = numpy.zeros(
                    (self.idx_data.shape[0],
                     min(self.idx_data.shape[1], int(self.stacking))),
                    dtype=self.idx_data.dtype
                )

            _native.stack(self.idx_data, self.stacking_outp, self.stacking)

            self.x = self.x[:self.stacking_outp.shape[1]]
            self.idx_data = self.stacking_outp

        if self.autoscale_x:
            x_min = self.x.min()
            x_max = self.x.max()

            x_pad = (x_max - x_min) * 0.03

            if x_pad == 0.0:
                x_pad = 1.0

            self.plot_axes[0] = x_min - x_pad
            self.plot_axes[1] = x_max + x_pad

        if self.autoscale_y:
            y_min = self.idx_data.min()
            y_max = self.idx_data.max()

            y_pad = (y_max - y_min) * 0.02

            if y_pad != 0.0:
                self.plot_axes[2] = y_min - y_pad
                self.plot_axes[3] = y_max + y_pad

        self.repaint(axes_changed=self.autoscale_x or self.autoscale_y,
                     data_changed=True)

    def dataCleared(self):
        pass

    def addFittedCurve(self, tag, x, y):
        # We just assume x to be the same as for our own data currently,
        # which is just an numpy.arange(len(y))
        self.fit_data[tag] = y.astype(numpy.int32)

        self.repaint(data_changed=True)

    def removeFittedCurve(self, tag):
        try:
            del self.fit_data[tag]
        except KeyError:
            pass

        self.repaint(data_changed=True)

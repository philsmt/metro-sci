
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from math import log10, floor, ceil
from ctypes import memset, memmove
import collections

import numpy
import scipy.sparse
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets

import metro
from metro.frontend import widgets

# We try to import the native version of add_pixel and use the older
# version using numpy ufuncs as a fallback.
try:
    from ._hist2d_native import add_pixel
except ImportError:
    # Global variables for vectorized functions
    data_size = 0
    max_value = 0
    data_matrix = None
    data_img_bits = None

    def add_pixel_element(x, y):
        global max_value

        data_matrix[y, x] += 1

        scaled_value = int(255 - 255/(1 + 0.005 * data_matrix[y, x]))
        max_value = max(scaled_value, max_value)

        memset(data_img_bits + (size_y - y) * size_x + x, scaled_value, 1)

    add_pixel_array = numpy.frompyfunc(add_pixel_element, 2, 1)

    def add_pixel(in_data_matrix, pos, in_size_x, in_size_y, in_data_img_bits,
                  in_max_value):
        global data_matrix, size_x, size_y, data_img_bits, max_value

        data_matrix = in_data_matrix
        size_x = in_size_x
        size_y = in_size_y
        data_img_bits = int(in_data_img_bits)
        max_value = in_max_value

        add_pixel_array(pos[:, 0], pos[:, 1])

        return max_value


def filterWindow(pos):
    if pos.min() < 0.0 or pos.max() >= 1.0:
        try:
            # Filter out any hits outside our windows
            pos = pos[numpy.greater(pos, 0).all(axis=1)]
            pos = pos[numpy.less(pos, 1).all(axis=1)]
        except IndexError:
            return None

    return pos


def filterRoi(coords, pos):
    pos = pos[numpy.greater(pos[:, 0], coords[0]), :]
    pos = pos[numpy.greater(pos[:, 1], coords[1]), :]
    pos = pos[numpy.less(pos[:, 0], coords[2]), :]
    pos = pos[numpy.less(pos[:, 1], coords[3]), :]

    return pos


def projectMatrix(pos, size_x, size_y):
    # Project onto self.num_channels
    # Makes a copy of the argument array
    pos = filterWindow(pos).copy()
    pos[:, 0] *= size_x - 1
    pos[:, 1] *= size_y - 1
    pos = pos.astype(numpy.int32)

    x, y = pos[:, 0], pos[:, 1]

    mtx = scipy.sparse.coo_matrix(
        (
            numpy.ones_like(x), (y, x)
        ),
        shape=(
            size_y, size_x
        )
    ).toarray()

    return mtx


class DetectorImageWidget(QtWidgets.QWidget):
    HOT_RECT_SCALE = 1
    HOT_RECT_ROI_AREA = 2
    HOT_RECT_ROI_EDGE = 3

    def __init__(self, parent, size_x, size_y, roi_map={}, title=None):
        super().__init__(parent)

        self.size_x = size_x
        self.size_y = size_y

        self.data_matrix = numpy.zeros((size_y, size_x), dtype=numpy.int32)

        # The spectrum along x, how often does each x value occur
        self.x_spectrum = numpy.zeros((size_x,), dtype=numpy.int32)

        # The spectrum along y, how often does each y value occur
        self.y_spectrum = numpy.zeros((size_y,), dtype=numpy.int32)

        self.x_spectrum_polygon = QtGui.QPolygonF(size_x)
        self.y_spectrum_polygon = QtGui.QPolygonF(size_y)

        self.x_scaling = 1
        self.y_scaling = 1

        self.data_img = QtGui.QImage(size_x, size_y,
                                     QtGui.QImage.Format_Indexed8)
        self.data_img.setColor(0, QtGui.qRgb(0, 0, 0))
        self.data_img.fill(0)

        self.data_img_dest = QtCore.QRect(0, 150, size_x, size_y)
        self.x_spectrum_img_dest = QtCore.QRect(0, 0, size_x, 150)
        self.y_spectrum_img_dest = QtCore.QRect(size_y, 150, 100, size_y)
        self.z_scale_img_dest = QtCore.QRect(size_x + 100 - 15, 0, 15, 110)

        self.data_img_src = None
        self.x_spectrum_img_src = None
        self.y_spectrum_img_src = None

        self.z_scale_img = QtGui.QImage(10, 150, QtGui.QImage.Format_RGB32)
        self.z_scale_img.fill(QtGui.qRgb(0, 0, 0))

        self.setMouseTracking(True)

        self.setMinimumSize(50 + 100 + 5, 50 + 150 + 5)
        self.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                           QtWidgets.QSizePolicy.MinimumExpanding)

        self.scale_x = 1
        self.scale_y = 1
        self.offset_x = 0
        self.offset_y = 0

        self.hovering_hot_rect = None
        self.hot_rects = []
        self.hot_roi = None

        self.axes_text_rects = {}

        self.roi_map = roi_map
        self.active_roi = None

        self.dragged_plot_mode = 0

        self.zoom_rect_origin = None
        self.zoom_rect_dest = None

        self.axes = {
            'x_min': 0, 'x_max': size_x,
            'y_min': 0, 'y_max': size_y,
            'z_min': 0, 'z_max': 1
        }
        self.z_auto_scale = True
        self.max_value = 0

        self.axes_tick_x_labels = []
        self.axes_tick_x_lines = []
        self.axes_tick_y_labels = []
        self.axes_tick_y_lines = []

        self.annotation_text = ''

        self.setMouseMode('axes')

        self.opened_scale_editor = None
        self.scale_editor_widget = QtWidgets.QLineEdit(self)
        self.scale_editor_widget.setStyleSheet('color: white;')
        self.scale_editor_widget.setMinimumWidth(50)
        self.scale_editor_widget.setMaximumWidth(50)
        self.scale_editor_widget.returnPressed.connect(self.scaleEditorSubmit)
        self.scale_editor_widget.hide()

        self.roi_recalc_timer = QtCore.QTimer(self)
        self.roi_recalc_timer.setInterval(250)
        self.roi_recalc_timer.setSingleShot(True)
        self.roi_recalc_timer.timeout.connect(self.on_recalculateRoi)

        self.mouseMoveEvent = self.mouseMoveEvent_default

        self.times = []

        self.proj_stack = collections.deque(maxlen=10)

        self.bg_title_str = title
        self.bg_title_pen = metro.QtGui.QColor(255, 70, 70, 60)

    def sizeHint(self, factor=None):
        if factor is None:
            factor = 1.0

        return QtCore.QSize(int(self.size_x * factor) + 100 + 5,
                            int(self.size_y * factor) + 150 + 5)

    # There is always a resizeEvent before the first paintEvent
    def resizeEvent(self, event):
        data_im_width = event.size().width() - 100 - 5
        data_im_height = event.size().height() - 150 - 5

        self.data_img_dest.setWidth(data_im_width)
        self.data_img_dest.setHeight(data_im_height)

        self.x_spectrum_img_dest.setWidth(data_im_width)

        self.y_spectrum_img_dest.setLeft(data_im_width)
        self.y_spectrum_img_dest.setWidth(100)
        self.y_spectrum_img_dest.setHeight(data_im_height)

        self.z_scale_img_dest.setLeft(data_im_width + 100 - 15)
        self.z_scale_img_dest.setWidth(15)

        self._findTitleMetric()

        self.invalidate()

    def paintEvent(self, event):
        qp = QtGui.QPainter(self)

        qp.drawImage(self.data_img_dest,
                     self.data_img.copy(self.data_img_src)
                     if self.data_img_src else self.data_img)

        qp.drawImage(self.z_scale_img_dest, self.z_scale_img)

        if self.bg_title_str is not None:
            qp.save()
            qp.setFont(self.bg_title_font)
            qp.setPen(self.bg_title_pen)

            qp.drawText(
                QtCore.QRect(0, 150 + 20,
                             self.data_img_dest.width() - 30,
                             self.bg_title_bbox.height()),
                QtCore.Qt.AlignRight, self.bg_title_str
            )
            qp.restore()

        qp.setPen(QtCore.Qt.red)

        x_spectrum_max = self.x_spectrum.max()
        y_spectrum_max = self.y_spectrum.max()

        # Drawing a polygon is ~15% faster than drawing it line by line
        if x_spectrum_max > 0:
            x_spectrum = self.x_spectrum
            x_min = self.axes['x_min']
            x_max = self.axes['x_max']

            n_points = x_max - x_min
            x_scale = n_points / self.data_img_dest.width()
            y_scale = x_spectrum_max / 130
            
            self.x_spectrum_polygon = QtGui.QPolygonF(
                [QtCore.QPointF(
                    i / x_scale,
                    145 - x_spectrum[x_min+i] / y_scale
                )
                for i in range(n_points)]
            )

            qp.drawPolyline(self.x_spectrum_polygon)

            qp.rotate(90)
            qp.drawText(3, -(self.data_img_dest.width()+22), 150, 20,
                        QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom,
                        str(x_spectrum_max))
            qp.rotate(-90)

        if y_spectrum_max > 0:
            y_spectrum = self.y_spectrum
            y_min = self.axes['y_min']
            y_max = self.axes['y_max']

            n_points = y_max - y_min
            x_scale = y_spectrum_max / 85
            y_scale = n_points / self.data_img_dest.height()

            x_offset = 5 + int(self.data_img_dest.right())

            self.y_spectrum_polygon = QtGui.QPolygonF(
                [QtCore.QPointF(
                    x_offset + int(y_spectrum[y_min+i] / x_scale),
                    150 + self.data_img_dest.height() - i / y_scale
                )
                for i in range(n_points)]
            )

            qp.drawPolyline(self.y_spectrum_polygon)

            qp.drawText(self.data_img_dest.right(), 150 - 22, 97, 20,
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom,
                        str(y_spectrum_max))

        # Rebuild our static objects
        if not self.hot_rects:
            self._rebuildStaticObjects(qp)

        for roi in self.roi_map.values():
            if not roi['visible']:
                continue

            qp.setPen(roi['color'])

            shape = roi['shape']
            if isinstance(shape, QtCore.QRect):
                qp.drawRect(shape)
            else:
                qp.drawLines(shape)

        if self.zoom_rect_origin is not None:
            qp.setPen(QtCore.Qt.white)
            qp.drawRect(QtCore.QRectF(self.zoom_rect_origin,
                                      self.zoom_rect_dest))

        qp.setPen(QtCore.Qt.gray)
        qp.drawRect(self.data_img_dest)
        qp.drawRect(self.x_spectrum_img_dest)
        qp.drawRect(self.y_spectrum_img_dest)
        qp.drawRect(self.z_scale_img_dest)
        qp.drawLines(self.axes_tick_x_lines)
        qp.drawLines(self.axes_tick_y_lines)

        qp.setLayoutDirection(QtCore.Qt.LeftToRight)
        qp.drawText(self.axes_text_rects['x_min'], QtCore.Qt.AlignHCenter,
                    str(self.axes['x_min']))
        qp.drawText(self.axes_text_rects['x_max'], QtCore.Qt.AlignHCenter,
                    str(self.axes['x_max']))
        qp.drawText(self.axes_text_rects['z_min'], QtCore.Qt.AlignVCenter,
                    str(self.axes['z_min']))
        qp.drawText(self.axes_text_rects['z_max'], QtCore.Qt.AlignVCenter,
                    str(self.axes['z_max']))

        for label, line in zip(self.axes_tick_x_labels,
                               self.axes_tick_x_lines):
            qp.drawText(QtCore.QRectF(line.x1() - 40, line.y1() - 20, 80, 20),
                        QtCore.Qt.AlignCenter, str(label))

        for label, line in zip(self.axes_tick_y_labels,
                               self.axes_tick_y_lines):
            qp.drawText(QtCore.QRectF(line.x1() + 10, line.y1() - 10, 80, 20),
                        QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                        str(label))

        qp.setLayoutDirection(QtCore.Qt.RightToLeft)
        qp.drawText(self.axes_text_rects['y_min'], QtCore.Qt.AlignVCenter,
                    str(self.axes['y_min']))
        qp.drawText(self.axes_text_rects['y_max'], QtCore.Qt.AlignVCenter,
                    str(self.axes['y_max']))

        if self.annotation_text:
            qp.setPen(QtCore.Qt.cyan)
            qp.drawText(6, 150 + 18, self.annotation_text)

    def _findTitleMetric(self):
        # Find the maximum font size we can use for the channel name.

        stretch = 100
        point_size = 25
        max_width = self.data_img_dest.width() - 50

        if max_width <= 0:
            return

        while True:
            font = QtGui.QFont()
            font.setStyleHint(QtGui.QFont.SansSerif)
            font.setStretch(stretch)
            font.setPointSize(point_size)

            metric = QtGui.QFontMetrics(font)
            bbox = metric.boundingRect(self.bg_title_str)

            if bbox.width() > max_width:
                if stretch > 70:
                    stretch -= 5
                else:
                    point_size -= 1
            else:
                break

        self.bg_title_bbox = bbox
        self.bg_title_font = font

    def _buildAxisTickLines(self, axis_min, axis_max, img_length, max_ticks,
                            labels, lines, ax_scale, ax_offset, ax_size,
                            line_func):
        interval = axis_max - axis_min
        frac = interval / max_ticks

        dim = floor(log10(frac))

        # For the moment, we only allow integer ticks
        dim = max(dim, 0)
        tick = pow(10, dim)

        while interval // tick > max_ticks:
            tick += 10**dim

        labels.clear()
        lines.clear()

        cur_tick_pos = (int(axis_min / tick) + 1) * tick
        tick_len = (tick/interval) * img_length
        offset = ((cur_tick_pos - axis_min) / interval) * img_length
        i = 0

        while cur_tick_pos < axis_max:
            line = line_func(offset, tick_len, i)

            orig_pos = (cur_tick_pos/ax_size - ax_offset - 0.5)/ax_scale + 0.5
            labels.append(round(orig_pos, 3))
            lines.append(line)

            cur_tick_pos += tick
            i += 1

    def _buildAxisRect(self, qp, name, x, y, flags):
        r = qp.boundingRect(x, y, 1, 1, flags, str(self.axes[name]))
        r.cursor = QtCore.Qt.IBeamCursor
        r.scale_name = name
        r.type = DetectorImageWidget.HOT_RECT_SCALE

        if name[0] == 'x':
            r.moveTop(r.y() - r.height())

        self.axes_text_rects[name] = r
        self.hot_rects.append(r)

        return r

    def _buildRoiAreaRect(self, qp, name, x, y, w, h):
        r = QtCore.QRectF(x, y, w, h)
        r.roi_name = name
        r.cursor = QtCore.Qt.SizeAllCursor
        r.type = DetectorImageWidget.HOT_RECT_ROI_AREA

        self.hot_rects.append(r)

    def _buildRoiEdgeRect(self, qp, name, edge_id, x, y, w, h):
        r = QtCore.QRectF(x, y, w, h)
        r.roi_name = name
        r.cursor = QtCore.Qt.SizeVerCursor \
            if w > h else QtCore.Qt.SizeHorCursor
        r.edge_id = edge_id
        r.type = DetectorImageWidget.HOT_RECT_ROI_EDGE

        self.hot_rects.append(r)

    def _rebuildStaticObjects(self, qp):
        img_width = self.data_img_dest.width()
        img_height = self.data_img_dest.height()

        self.axes_tick_lines = []

        qp.setLayoutDirection(QtCore.Qt.LeftToRight)

        # X scales
        self._buildAxisRect(qp, 'x_min', 5, 18,
                            QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self._buildAxisRect(qp, 'x_max', img_width - 5, 18,
                            QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)

        self._buildAxisTickLines(
            self.axes['x_min'], self.axes['x_max'], img_width, 10,
            self.axes_tick_x_labels, self.axes_tick_x_lines,
            self.scale_x, self.offset_x, self.size_x,
            lambda offset, tick_len, i:
                QtCore.QLineF(offset + i * tick_len, 150 - 3,
                              offset + i * tick_len, 150 + 3)
        )

        # Z scales
        self._buildAxisRect(
            qp, 'z_min', self.z_scale_img_dest.x() - 5,
            self.z_scale_img_dest.y() + self.z_scale_img_dest.height(),
            QtCore.Qt.AlignBottom | QtCore.Qt.AlignRight
        )
        self._buildAxisRect(
            qp, 'z_max', self.z_scale_img_dest.x() - 5,
            self.z_scale_img_dest.y(),
            QtCore.Qt.AlignTop | QtCore.Qt.AlignRight
        )

        # Y scales
        self._buildAxisRect(qp, 'y_min',
                            img_width + 100 - 4, 150 + img_height - 2,
                            QtCore.Qt.AlignBottom | QtCore.Qt.AlignRight)
        self._buildAxisRect(qp, 'y_max',
                            img_width + 100 - 4, 150 + 2,
                            QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)

        self._buildAxisTickLines(
            self.axes['y_min'], self.axes['y_max'], img_height, 10,
            self.axes_tick_y_labels, self.axes_tick_y_lines,
            self.scale_y, self.offset_y, self.size_y,
            lambda offset, tick_len, i: QtCore.QLineF(
                img_width - 3, 150 + img_height - offset - i * tick_len,
                img_width + 3, 150 + img_height - offset - i * tick_len
            )
        )

        s_x = img_width / (self.axes['x_max'] - self.axes['x_min'])
        s_y = img_height / (self.axes['y_max'] - self.axes['y_min'])

        # Region of interest
        for roi in self.roi_map.values():
            if not roi['visible']:
                continue

            coords = roi['coords']

            roi_x = int(s_x * (coords[0] - self.axes['x_min']))
            roi_y = int(s_y * (self.axes['y_max'] - coords[3]))

            top_visible = bottom_visible = left_visible = right_visible = True

            if roi_x < 0:
                left_visible = False
                roi_x = 0
            elif roi_x > img_width:
                left_visible = False
                roi_x = img_width

            if roi_y < 0:
                top_visible = False
                roi_y = 0
            elif roi_y > img_height:
                top_visible = False
                roi_y = img_height

            roi_width = int(s_x * (coords[2] - coords[0]))
            roi_height = int(s_y * (coords[3] - coords[1]))

            if (roi_x + roi_width) > img_width:
                right_visible = False
                roi_width = img_width - roi_x
            elif (roi_x + roi_width) < 0:
                right_visible = False
                roi_width = 0

            if (roi_y + roi_height) > img_height:
                bottom_visible = False
                roi_height = img_height - roi_y
            elif (roi_y + roi_height) < 0:
                bottom_visible = False
                roi_height = 0

            self._buildRoiAreaRect(qp, roi['name'],
                                   0 + 4 + roi_x, 150 + 4 + roi_y,
                                   -8 + roi_width, -8 + roi_height)

            if left_visible:
                self._buildRoiEdgeRect(qp, roi['name'], 0,
                                       0 - 3 + roi_x, 150 - 2 + roi_y,
                                       6, 3 + roi_height)

            if top_visible:
                self._buildRoiEdgeRect(qp, roi['name'], 3,
                                       0 - 2 + roi_x, 150 - 3 + roi_y,
                                       3 + roi_width, 6)

            if right_visible:
                self._buildRoiEdgeRect(qp, roi['name'], 2,
                                       0 - 3 + roi_x + roi_width,
                                       150 - 2 + roi_y,
                                       6, 3 + roi_height)

            if bottom_visible:
                self._buildRoiEdgeRect(qp, roi['name'], 1,
                                       0 - 2 + roi_x,
                                       150 - 3 + roi_y + roi_height,
                                       3 + roi_width, 6)

            if (left_visible and bottom_visible and right_visible and
                    top_visible):
                roi['shape'] = QtCore.QRectF(roi_x, 150 + roi_y,
                                            roi_width, roi_height)
            else:
                shapes = []
                roi_y += 150

                if left_visible:
                    shapes.append(QtCore.QLineF(roi_x, roi_y, roi_x,
                                                roi_y + roi_height))

                if bottom_visible:
                    shapes.append(QtCore.QLineF(roi_x, roi_y + roi_height,
                                                roi_x + roi_width,
                                                roi_y + roi_height))

                if right_visible:
                    shapes.append(QtCore.QLineF(roi_x + roi_width, roi_y,
                                                roi_x + roi_width,
                                                roi_y + roi_height))

                if top_visible:
                    shapes.append(QtCore.QLineF(roi_x, roi_y,
                                                roi_x + roi_width, roi_y))

                roi['shape'] = shapes

        self.x_scaling = s_x
        self.y_scaling = s_y

    def invalidate(self):
        # hot rects are used as our reset marker
        self.hot_rects.clear()

        self.roi_recalc_timer.start()

    def mouseMoveEvent_default(self, event):
        if self.hovering_hot_rect is not None:
            if not self.hovering_hot_rect.contains(event.x(), event.y()):
                self.setCursor(QtCore.Qt.ArrowCursor)
                self.hovering_hot_rect = None
        else:
            for rect in self.hot_rects:
                if rect.contains(event.x(), event.y()):
                    self.setCursor(rect.cursor)
                    self.hovering_hot_rect = rect
                    break

    def mouseMoveEvent_moveRoi(self, event):
        mx = event.pos().x() - self.last_pos_x
        dx = int(mx / self.x_scaling)

        my = event.pos().y() - self.last_pos_y
        dy = -int(my / self.y_scaling)

        if dx != 0 or dy != 0:
            coords = self.hot_roi['coords']

            if dx != 0:
                coords[0] += dx
                coords[2] += dx
                self.last_pos_x += mx

            if dy != 0:
                coords[1] += dy
                coords[3] += dy
                self.last_pos_y += my

            self.invalidate()
            self.repaint()

    def mouseMoveEvent_resizeRoi(self, event):
        # ds in screen coordinates
        # dd in data coordiates

        if self.dragged_roi_axis == 0 or self.dragged_roi_axis == 2:
            ds = event.pos().x() - self.last_pos
            dd = int(ds / self.x_scaling)
            size = self.size_x
        else:
            ds = event.pos().y() - self.last_pos
            dd = -int(ds / self.y_scaling)
            size = self.size_y

        if dd != 0:
            roi_c = self.hot_roi['coords']
            roi_c[self.dragged_roi_axis] += dd

            if roi_c[self.dragged_roi_axis] < 0:
                roi_c[self.dragged_roi_axis] = 0
            elif roi_c[self.dragged_roi_axis] > size:
                roi_c[self.dragged_roi_axis] = size
            else:
                self.last_pos += ds

            self.invalidate()
            self.repaint()

    def mouseMoveEvent_moveAxes(self, event):
        if self.dragged_plot_mode & 1:
            dx = -int(round(
                (event.x() - self.dragged_plot_origin.x()) / self.x_scaling
            ))

            if self.dragged_plot_axes['x_min'] + dx < 0:
                dx = -self.dragged_plot_axes['x_min']
            elif self.dragged_plot_axes['x_max'] + dx > self.size_x:
                dx = self.size_x - self.dragged_plot_axes['x_max']

            self.axes['x_min'] = self.dragged_plot_axes['x_min'] + dx
            self.axes['x_max'] = self.dragged_plot_axes['x_max'] + dx

        if self.dragged_plot_mode & 2:
            dy = int(round(
                (event.y() - self.dragged_plot_origin.y()) / self.y_scaling
            ))

            if self.dragged_plot_axes['y_min'] + dy < 0:
                dy = -self.dragged_plot_axes['y_min']
            elif self.dragged_plot_axes['y_max'] + dy > self.size_y:
                dy = self.size_y - self.dragged_plot_axes['y_max']

            self.axes['y_min'] = self.dragged_plot_axes['y_min'] + dy
            self.axes['y_max'] = self.dragged_plot_axes['y_max'] + dy

        self._updateRects()

    def mouseMoveEvent_moveProj(self, event):
        dev = self.parent().proj_dev

        if self.dragged_plot_mode & 1:
            # [distance in pixel] *
            # [visible portion of data size] /
            # [screen width]
            dx = (
                (event.x() - self.dragged_plot_origin.x()) *
                ((self.axes['x_max'] - self.axes['x_min']) / self.size_x) /
                self.data_img_dest.width()
            )

            dev.offset_x = self.dragged_plot_offset_x + dx

        if self.dragged_plot_mode & 2:
            height = self.data_img_dest.height()
            dy = -(
                (event.y() - self.dragged_plot_origin.y()) *
                ((self.axes['y_max'] - self.axes['y_min']) / self.size_y) /
                height
            )

            dev.offset_y = self.dragged_plot_offset_y + dy

        self._updateProj()

    def mouseMoveEvent_zoom(self, event):
        self.zoom_rect_dest = event.localPos()

        self.invalidate()
        self.repaint()

    def mousePressEvent(self, event):
        if event.button() != 1:
            return

        if event.modifiers() == QtCore.Qt.ShiftModifier:
            self.zoom_rect_origin = event.localPos()
            self.zoom_rect_dest = event.localPos()
            self.mouseMoveEvent = self.mouseMoveEvent_zoom

        elif event.modifiers() == QtCore.Qt.ControlModifier:
            local_pos = event.pos()

            if self.data_img_dest.contains(local_pos):
                mode = 1 | 2

            elif self.x_spectrum_img_dest.contains(local_pos):
                mode = 1

            elif self.y_spectrum_img_dest.contains(local_pos):
                mode = 2

            else:
                return

            self.dragged_plot_mode = mode
            self.dragged_plot_origin = event.pos()

            self.mousePressEvent_movePlot()
            self.mouseMoveEvent = self.mouseMoveEvent_movePlot

        elif self.hovering_hot_rect:
            cur_type = self.hovering_hot_rect.type

            if cur_type == DetectorImageWidget.HOT_RECT_SCALE:
                c_x = self.hovering_hot_rect.center().x()
                c_y = self.hovering_hot_rect.center().y()

                cur_width = self.size().width()
                cur_height = self.size().height()

                if c_x > cur_width/2:
                    c_x -= 50

                if c_y > cur_height/2:
                    c_y -= self.scale_editor_widget.size().height()

                self.scale_editor_widget.move(c_x, c_y)
                self.scale_editor_widget.setText(str(
                    self.axes[self.hovering_hot_rect.scale_name])
                )
                self.scale_editor_widget.show()
                self.scale_editor_widget.setFocus(QtCore.Qt.MouseFocusReason)

                self.opened_scale_editor = self.hovering_hot_rect

            elif cur_type == DetectorImageWidget.HOT_RECT_ROI_AREA:
                self.mouseMoveEvent = self.mouseMoveEvent_moveRoi

                self.hot_roi = self.roi_map[self.hovering_hot_rect.roi_name]

                self.hot_roi['volatile'] = True
                self.hot_roi['update'](self.hot_roi['name'])

                self.last_pos_x = event.pos().x()
                self.last_pos_y = event.pos().y()

            elif cur_type == DetectorImageWidget.HOT_RECT_ROI_EDGE:
                self.mouseMoveEvent = self.mouseMoveEvent_resizeRoi

                self.hot_roi = self.roi_map[self.hovering_hot_rect.roi_name]

                self.hot_roi['volatile'] = True
                self.hot_roi['update'](self.hot_roi['name'])

                self.dragged_roi_axis = self.hovering_hot_rect.edge_id

                if self.dragged_roi_axis == 0 or self.dragged_roi_axis == 2:
                    self.last_pos = event.pos().x()
                else:
                    self.last_pos = event.pos().y()

        else:
            self.scale_editor_widget.hide()

            dev = self.parent().proj_dev

            if dev is None:
                return

            image_point = event.pos() - self.data_img_dest.topLeft()

            # Relative coordinates in image space
            rel_x = image_point.x() / self.data_img_dest.width()
            rel_y = 1 - image_point.y() / self.data_img_dest.height()

            # Normalize to zoomed portion
            rel_x *= (self.axes['x_max'] - self.axes['x_min']) / self.size_x
            rel_y *= (self.axes['y_max'] - self.axes['y_min']) / self.size_y

            # Add relative offset of zoomed portion
            rel_x += self.axes['x_min'] / self.size_x
            rel_y += self.axes['y_min'] / self.size_y

            # rel_x, rel_y are now relative coordinates in data space,
            # i.e. after the projection

            data_x = (rel_x - self.offset_x - 0.5) / self.scale_x + 0.5
            data_y = (rel_y - self.offset_y - 0.5) / self.scale_y + 0.5

            QtWidgets.QToolTip.showText(
                event.globalPos(),
                'X: {0:.9g}\nY: {1:.9g}'.format(data_x, data_y)
            )

    def mousePressEvent_moveAxes(self):
        self.dragged_plot_axes = self.axes.copy()

    def mousePressEvent_moveProj(self):
        self.dragged_plot_offset_x = self.parent().proj_dev.offset_x
        self.dragged_plot_offset_y = self.parent().proj_dev.offset_y

    def mouseReleaseEvent(self, event):
        if event.button() != 1:
            return

        if event.modifiers() == QtCore.Qt.ShiftModifier:
            # Offset by current axis minimum
            offset_x = self.axes['x_min'] / self.size_x
            offset_y = self.axes['y_min'] / self.size_y

            # Size of the currently shown window in relative units
            window_x = (self.axes['x_max'] - self.axes['x_min']) / self.size_x
            window_y = (self.axes['y_max'] - self.axes['y_min']) / self.size_y

            start_x = offset_x + window_x * \
                (self.zoom_rect_origin.x() / self.data_img_dest.width())

            height = self.data_img_dest.height()
            start_y = offset_y + window_y * \
                ((height - (self.zoom_rect_origin.y()-150)) / height)

            dest_x = offset_x + window_x * \
                (self.zoom_rect_dest.x() / self.data_img_dest.width())

            dest_y = offset_y + window_y * \
                ((height - (self.zoom_rect_dest.y()-150)) / height)

            if start_x > dest_x:
                start_x, dest_x = dest_x, start_x

            if start_y > dest_y:
                start_y, dest_y = dest_y, start_y

            self._zoom(start_x, start_y, dest_x, dest_y)

        self.mouseMoveEvent = self.mouseMoveEvent_default

        if self.dragged_plot_mode != 0:
            # No need to check for CTRL again, we always want to reset
            # these flags here if they are set.
            self.dragged_plot_mode = 0
            self.dragged_plot_origin = 0

        elif self.hot_roi is not None:
            coords = self.hot_roi['coords']

            coord_str = 'X {0}:{2} - Y {1}:{3}'.format(coords[0], coords[1],
                                                       coords[2], coords[3])

            self.hot_roi['labelName'].setToolTip(coord_str)
            self.hot_roi['channelRate'].setHeaderTag('roi', coord_str)
            self.hot_roi['channelCounts'].setHeaderTag('roi', coord_str)

        elif self.zoom_rect_origin is not None:
            self.zoom_rect_origin = None
            self.zoom_rect_dest = None

        self.invalidate()
        self.repaint()

    def mouseDoubleClickEvent(self, event):
        # Offset by current axis minimum
        offset_x = self.axes['x_min'] / self.size_x
        offset_y = self.axes['y_min'] / self.size_y

        # Size of the currently shown window in relative units
        window_x = (self.axes['x_max'] - self.axes['x_min']) / self.size_x
        window_y = (self.axes['y_max'] - self.axes['y_min']) / self.size_y

        center_x = offset_x + window_x * \
            (event.x() / self.data_img_dest.width())

        height = self.data_img_dest.height()
        center_y = offset_y + window_y * \
            ((height - (event.y() - 150)) / height)

        self._center(center_x, center_y)

    def _centerAxes(self, center_x, center_y):
        dx = (self.axes['x_max'] - self.axes['x_min']) / 2
        dy = (self.axes['x_max'] - self.axes['x_min']) / 2

        self.axes['x_min'] = floor(center_x * self.size_x - dx)
        self.axes['x_max'] = ceil(center_x * self.size_x + dx)
        self.axes['y_min'] = floor(center_y * self.size_y - dy)
        self.axes['y_max'] = ceil(center_y * self.size_y + dy)

        if self.axes['x_min'] < 0:
            self.axes['x_max'] -= self.axes['x_min']
            self.axes['x_min'] = 0

        if self.axes['x_max'] > self.size_x:
            self.axes['x_min'] -= self.axes['x_max'] - self.size_x
            self.axes['x_max'] = self.size_x

        if self.axes['y_min'] < 0:
            self.axes['y_max'] -= self.axes['y_min']
            self.axes['y_min'] = 0

        if self.axes['y_max'] > self.size_y:
            self.axes['y_min'] -= self.axes['y_max'] - self.size_y
            self.axes['y_max'] = self.size_y

        self._updateRects()

    def _scaleAxis(self, min_key, max_key, rel_center, delta, size):
        axis_diff = self.axes[max_key] - self.axes[min_key]

        delta_mag = abs(delta)
        delta_sign = delta / delta_mag

        if axis_diff == 1 and delta_sign > 0:
            delta = 0
        else:
            delta = max(1, axis_diff / 10) * delta_sign

        self.axes[min_key] = int(max(
            0, self.axes[min_key] + 2 * delta * rel_center
        ))
        self.axes[max_key] = int(min(
            size, self.axes[max_key] - 2 * delta * (1 - rel_center)
        ))

        if self.axes[min_key] >= self.axes[max_key]:
            if self.axes[min_key] >= size:
                self.axes[min_key] = size - 1
            else:
                self.axes[max_key] = self.axes[min_key] + 1

    def _scaleAxes(self, rel_x, rel_y, delta):
        if rel_x is not None:
            self._scaleAxis('x_min', 'x_max', rel_x, delta, self.size_x)

        if rel_y is not None:
            self._scaleAxis('y_min', 'y_max', rel_y, delta, self.size_y)

        self._updateRects()

    def _zoomAxes(self, start_x, start_y, dest_x, dest_y):
        self.axes['x_min'] = floor(start_x * self.size_x)
        self.axes['y_min'] = floor(start_y * self.size_y)

        self.axes['x_max'] = ceil(dest_x * self.size_x)
        self.axes['y_max'] = ceil(dest_y * self.size_y)

        self._updateRects()

    def _centerProj(self, center_x, center_y):
        self._pushProjection()
        dev = self.parent().proj_dev

        dev.offset_x = dev.scale_x * \
            (0.5 - ((center_x - dev.offset_x - 0.5) / dev.scale_x + 0.5))
        dev.offset_y = dev.scale_y * \
            (0.5 - ((center_y - dev.offset_y - 0.5) / dev.scale_y + 0.5))

        self._updateProj()

    def _scaleProj(self, rel_x, rel_y, delta):
        dev = self.parent().proj_dev

        if dev is None:
            return

        mod = 1.2 if delta > 0 else 0.8

        if rel_x is not None:
            dev.scale_x *= mod

            # Calculated with the ansatz that both the position in
            # data space χ = χ' and projection space x = x' shall
            # remain constant when the scaling changes s -> s'.
            # The formula below then follows directly from
            # χ(x; s, o) = χ(x; s', o') with
            # χ(x; s, o) = (x - o - 0.5)*s + 0.5
            dev.offset_x = rel_x - 0.5 + mod * (0.5 + dev.offset_x - rel_x)

        if rel_y is not None:
            dev.scale_y *= mod
            dev.offset_y = rel_y - 0.5 + mod * (0.5 + dev.offset_y - rel_y)

        self._updateProj()

    def _zoomProj(self, start_x, start_y, dest_x, dest_y):
        center_x = (dest_x + start_x) / 2
        center_y = (dest_y + start_y) / 2

        self._pushProj()
        dev = self.parent().proj_dev

        # The ansatz here is to calculate the origin so that the new
        # center point is at 0.5/0.5 in the new projection.

        # new scaling parameters
        scale_x = dev.scale_x / (dest_x - start_x)
        scale_y = dev.scale_y / (dest_y - start_y)

        dev.offset_x = scale_x * \
            (0.5 - ((center_x - dev.offset_x - 0.5) / dev.scale_x + 0.5))
        dev.offset_y = scale_y * \
            (0.5 - ((center_y - dev.offset_y - 0.5) / dev.scale_y + 0.5))

        dev.scale_x = scale_x
        dev.scale_y = scale_y

        self._updateProj()

    def _updateRects(self):
        if (self.axes['x_min'] == 0 and
                self.axes['x_max'] == self.size_x and
                self.axes['y_min'] == 0 and
                self.axes['y_max'] == self.size_y):
            self.data_img_src = None
        else:
            if not self.data_img_src:
                self.data_img_src = QtCore.QRect(0, 0, 0, 0)

            self.data_img_src.setRect(
                self.axes['x_min'], self.size_x - self.axes['y_max'],
                self.axes['x_max'] - self.axes['x_min'],
                self.axes['y_max'] - self.axes['y_min']
            )

        self.x_spectrum_polygon = QtGui.QPolygonF(
            self.axes['x_max'] - self.axes['x_min'])
        self.y_spectrum_polygon = QtGui.QPolygonF(
            self.axes['y_max'] - self.axes['y_min'])

    def _updateProj(self):
        dev = self.parent().proj_dev

        dev.editXscale.setText('{0:.6g}'.format(dev.scale_x))
        dev.editXoffset.setText('{0:.6g}'.format(dev.offset_x))
        dev.editYscale.setText('{0:.6g}'.format(dev.scale_y))
        dev.editYoffset.setText('{0:.6g}'.format(dev.offset_y))

        dev._update()

        self.scale_x = dev.scale_x
        self.scale_y = dev.scale_y
        self.offset_x = dev.offset_x
        self.offset_y = dev.offset_y

    def wheelEvent(self, event):
        local_pos = event.pos()

        data_center = local_pos - self.data_img_dest.topLeft()
        rel_x = data_center.x() / self.data_img_dest.width()
        rel_y = 1 - (data_center.y() / self.data_img_dest.height())

        delta = event.angleDelta().y() / 10

        if self.data_img_dest.contains(local_pos):
            self._scale(rel_x, rel_y, delta)

        elif self.x_spectrum_img_dest.contains(local_pos):
            self._scale(rel_x, None, delta)

        elif self.y_spectrum_img_dest.contains(local_pos):
            self._scale(None, rel_y, delta)

        else:
            return

        self.invalidate()
        self.repaint()

    @QtCore.pyqtSlot()
    def scaleEditorSubmit(self):
        scale_name = self.opened_scale_editor.scale_name

        try:
            value = int(self.scale_editor_widget.text())

            if scale_name[0] == 'z':
                self.z_auto_scale = False

                if scale_name == 'z_min':
                    if value < 0:
                        value = 0
                    elif value >= self.axes['z_max']:
                        value = self.axes['z_max'] - 1

                elif scale_name == 'z_max':
                    if value <= self.axes['z_min']:
                        value = self.axes['z_min'] + 1

                self.axes[scale_name] = value

                self._buildColorPalette()
            else:
                if scale_name == 'x_min' and self.axes['x_max'] == value:
                    value -= 1
                elif scale_name == 'x_max' and self.axes['x_min'] == value:
                    value += 1
                elif scale_name == 'y_min' and self.axes['y_max'] == value:
                    value -= 1
                elif scale_name == 'y_max' and self.axes['y_min'] == value:
                    value += 1

                size = self.size_x if scale_name[0] == 'x' else self.size_y

                if value < 0:
                    value = 0
                elif value > size:
                    value = size

                self.axes[scale_name] = value

                self._updateRects()

            self.invalidate()
            self.repaint()

        # Not a proper number inserted
        except ValueError:
            if scale_name == 'z_max':
                self.axes['z_min'] = 0
                self.axes['z_max'] = 1

                self.z_auto_scale = True

                self._buildColorPalette()
                self.repaint()

        finally:
            self.scale_editor_widget.hide()

    @QtCore.pyqtSlot()
    def on_recalculateRoi(self):
        for roi in self.roi_map.values():
            if not roi['volatile']:
                continue

            coords = roi['coords']

            roi_mtx = self.data_matrix[coords[1]:coords[3],
                                       coords[0]:coords[2]]

            if roi == self.active_roi:
                self.x_spectrum[:] = 0
                self.x_spectrum[coords[0]:coords[2]] = roi_mtx.sum(axis=0)

                self.y_spectrum[:] = 0
                self.y_spectrum[coords[1]:coords[3]] = roi_mtx.sum(axis=1)

            roi['totalHits'] = int(roi_mtx.sum())
            roi['volatile'] = False

            roi['update'](roi['name'])

        if self.active_roi is None:
            self.x_spectrum = self.data_matrix.sum(axis=0).astype(int)
            self.y_spectrum = self.data_matrix.sum(axis=1).astype(int)

        self.repaint()

    def setActiveRoi(self, roi_name):
        old_roi = self.active_roi

        try:
            self.active_roi = self.roi_map[roi_name]
            self.active_roi['volatile'] = True
        except KeyError:
            self.active_roi = None

        if self.active_roi != old_roi:
            self.roi_recalc_timer.start()

    def setMouseMode(self, mode):
        if mode == 'axes':
            self._center = self._centerAxes
            self._scale = self._scaleAxes
            self._zoom = self._zoomAxes
            self.mousePressEvent_movePlot = self.mousePressEvent_moveAxes
            self.mouseMoveEvent_movePlot = self.mouseMoveEvent_moveAxes

        elif mode == 'projection':
            self._center = self._centerProj
            self._scale = self._scaleProj
            self._zoom = self._zoomProj
            self.mousePressEvent_movePlot = self.mousePressEvent_moveProj
            self.mouseMoveEvent_movePlot = self.mouseMoveEvent_moveProj

        else:
            raise ValueError('invalid mouse mode')

    def setTitle(self, new_title):
        self.bg_title_str = new_title if new_title else None

        if self.bg_title_str is not None:
            self._findTitleMetric()

        self.repaint()

    def setMatrix(self, mtx):
        scaled_mtx = (255 - 255/(1 + 0.005 * mtx)).astype(dtype=numpy.uint8)
        self.max_value = int(scaled_mtx.max())

        memmove(int(self.data_img.bits()),
                numpy.ctypeslib.as_ctypes(numpy.ascontiguousarray(numpy.flipud(
                    scaled_mtx
                ))),
                self.data_img.byteCount())

        for roi in self.roi_map.values():
            roi['volatile'] = True

        self.data_matrix = mtx

        self.roi_recalc_timer.start()

        self._buildColorPalette()

    def addPoints(self, pos):
        try:
            max_value = add_pixel(self.data_matrix, pos, self.size_x,
                                  self.size_y, self.data_img.bits(),
                                  self.max_value)

        except IndexError:
            pass
        else:
            if max_value > self.max_value:
                self.max_value = max_value
                self._buildColorPalette()

        spectrum_pos = pos

        # Profile this against reshaping data_vector, slicing the matrix
        # and summing it up!
        # It looks like this method wins.
        for roi in self.roi_map.values():
            roi_pos = filterRoi(roi['coords'], pos)
            roi_hits = roi_pos.shape[0]

            if self.active_roi == roi:
                spectrum_pos = roi_pos

            roi['totalHits'] += roi_hits
            roi['hitsLastSec'] += roi_hits

        self.x_spectrum += numpy.bincount(spectrum_pos[:, 0],
                                          minlength=self.size_x)
        self.y_spectrum += numpy.bincount(spectrum_pos[:, 1],
                                          minlength=self.size_y)

    def clear(self):
        self.data_matrix[:, :] = 0
        self.x_spectrum[:] = 0
        self.y_spectrum[:] = 0

        self.data_img.fill(0)
        self.max_value = 0

        self._buildColorPalette()
        self.repaint()

    def _buildColorPalette(self):
        # no data yet
        if self.max_value == 0:
            return

        if self.z_auto_scale:
            max_value = self.max_value + 1
            self.axes['z_max'] = self.data_matrix.max()
        else:
            max_value = int(255 - 255/(1 + 0.005 * self.axes['z_max']))

        z_min = self.axes['z_min']

        mx_20 = max_value * 0.2 + z_min
        mx_40 = max_value * 0.4 + z_min
        mx_60 = max_value * 0.6 + z_min
        mx_80 = max_value * 0.8 + z_min

        color_table = [QtGui.qRgb(255, 255, 255)] * 256
        color_table[0] = QtGui.qRgb(0, 0, 0)

        grad = QtGui.QLinearGradient()
        grad.setStart(0, 0)
        grad.setFinalStop(10, 150)

        grad.setColorAt(1.0, QtCore.Qt.black)
        grad.setColorAt(0.0, QtCore.Qt.white)

        # 0 and max_value have been set explicitly above
        for i in range(1, max_value):
            # 0 - 20
            if i < mx_20:
                red = 0.0  # constant
                green = 0.0  # constant
                blue = i / mx_20  # rising
            # 20 - 40
            elif i < mx_40:
                red = 0.0
                green = (i - mx_20) / (mx_40 - mx_20)  # rising
                blue = (mx_40 - i) / (mx_40 - mx_20)  # falling
            # 40 - 60
            elif i < mx_60:
                red = (i - mx_40) / (mx_60 - mx_40)  # rising
                green = 1.0  # constant
                blue = 0.0
            # 60 - 80
            elif i < mx_80:
                red = 1.0  # constant
                green = (mx_80 - i) / (mx_80 - mx_60)  # falling
                blue = 0.0
            # 80 - 100
            else:
                red = 1.0  # constant
                green = (i - mx_80) / (max_value - mx_80)  # rising
                blue = (i - mx_80) / (max_value - mx_80)  # rising

            color_table[i] = QtGui.qRgb(
                int(red * 255.0), int(green * 255.0), int(blue * 255.0))
            grad.setColorAt(1.0 - (i / max_value),
                            QtGui.QColor.fromRgb(color_table[i]))

        self.data_img.setColorTable(color_table)

        qp = QtGui.QPainter(self.z_scale_img)
        qp.fillRect(QtCore.QRect(0, 0, 15, 150), QtGui.QBrush(grad))
        qp.drawRect(0, 0, 15, 150)

        # Can be removed once z_max is handled elsewhere
        self.invalidate()

    def _pushProj(self):
        self.proj_stack.append((self.scale_x, self.scale_y,
                                self.offset_x, self.offset_y))

    def popProj(self):
        try:
            t = self.proj_stack.pop()
        except IndexError:
            return

        dev = self.parent().proj_dev
        dev.scale_x = t[0]
        dev.scale_y = t[1]
        dev.offset_x = t[2]
        dev.offset_y = t[3]

        self._updateProj()


class Device(metro.WidgetDevice, metro.DisplayDevice):
    ROI_COLORS = [QtCore.Qt.white, QtCore.Qt.darkBlue,
                  QtCore.Qt.darkMagenta, QtCore.Qt.darkGreen,
                  QtCore.Qt.darkCyan, QtCore.Qt.darkYellow]

    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(type_=metro.StreamChannel, shape=2),
        'size_x': 512,
        'size_y': 512,
        'internalProj': False,
        'mouseMode': ('axes', 'projection'),
        'bg_text': ''
    }

    descriptions = {
        '__main__': 'Displays histograms of 2d data sets sampled point by '
                    'point.',
        'channel': 'The channel to be displayed.',
        'size_x': 'The number of channels the input samples are '
                  'projected on along the x axis.',
        'size_y': 'The number of channels the input samples are '
                  'projected on along the y axis.',
        'bg_text': 'Initial background text, chosen automatically if empty.'
    }

    def prepare(self, args, state):
        self.size_x = args['size_x']
        self.size_y = args['size_y']
        self.proj_dev = None

        if state is None:
            state = {}

        if args['internalProj']:
            proj_args = {'channel': args['channel'], 'tag': 'map',
                         'count_rows': False}

            if isinstance(args['internalProj'], dict):
                proj_args.update(args['internalProj'])

            self.proj_dev = self.createChildDevice(
                'project.generic2d', 'internal', args=proj_args,
                state=state.pop('internal_proj', {'visible': False})
            )

            self.ch_in = self.proj_dev.ch_out

            # INTERNAL API
            self.proj_dev.ch_out.transient = True
        else:
            self.ch_in = args['channel']

            ch_dev = metro.findDeviceForChannel(self.ch_in.name)

            if ch_dev is not None and ch_dev.isSubDevice('project.generic2d'):
                self.proj_dev = ch_dev

        self.dirty = False

        self.hits_last_sec = 0
        self.total_hits = 0

        self.roi_map = {}
        self.roi_color_pool = Device.ROI_COLORS[:]

        self.ch_mtx = metro.DatagramChannel(self, 'matrix', hint='indicator',
                                            freq='step', compression=True,
                                            transient=True)
        self.ch_xspec = metro.NumericChannel(self, 'xspec', shape=1,
                                             hint='indicator', freq='step',
                                             transient=True)
        self.ch_yspec = metro.NumericChannel(self, 'yspec', shape=1,
                                             hint='indicator', freq='step',
                                             transient=True)

        self.menuChannelLink = widgets.ChannelLinkMenu()

        # Set up the widget itself
        self.setStyleSheet('background-color: black;')

        # Info area at the bottom
        labelTotalName = QtWidgets.QLabel('<i>total area</i>')
        labelTotalName.setStyleSheet('color: white;')

        self.labelTotalRate = QtWidgets.QLabel('0 Hz')
        self.labelTotalRate.setStyleSheet('color: white;')
        self.labelTotalCounts = QtWidgets.QLabel('0')
        self.labelTotalCounts.setStyleSheet('color: white;')

        self.labelTotalLinks = widgets.ChannelLinksLabel()
        self.labelTotalLinks.setContextMenu(self.menuChannelLink)
        self.labelTotalLinks.setStyleSheet('color: white;')
        self.labelTotalLinks.addChannel(self.ch_mtx, 'matrix')
        self.labelTotalLinks.addChannel(self.ch_xspec, 'x')
        self.labelTotalLinks.addChannel(self.ch_yspec, 'y')

        self.layoutInfo = QtWidgets.QGridLayout()
        self.layoutInfo.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.layoutInfo.addWidget(labelTotalName, 1, 1, QtCore.Qt.AlignLeft)
        self.layoutInfo.addWidget(self.labelTotalRate, 1, 2,
                                  QtCore.Qt.AlignRight)
        self.layoutInfo.addWidget(self.labelTotalCounts, 1, 3,
                                  QtCore.Qt.AlignRight)
        self.layoutInfo.addWidget(self.labelTotalLinks, 1, 4,
                                  QtCore.Qt.AlignRight)

        # Detector image
        self.imageDetector = DetectorImageWidget(self, self.size_x,
                                                 self.size_y, self.roi_map,
                                                 args['bg_text']
                                                 if args['bg_text'] else None)

        # Context menu
        self.menuContext = QtWidgets.QMenu()
        self.menuContext.triggered.connect(self.on_menuContext_triggered)

        # Show step
        self.menuStep = self.menuContext.addMenu('Choose step')
        self.menuStep.triggered.connect(self.on_menuStep_triggered)
        self.groupStep = QtWidgets.QActionGroup(self.menuStep)

        # Current step
        self.actionStepCurrent = self.menuStep.addAction('Current')
        self.actionStepCurrent.setCheckable(True)
        self.actionStepCurrent.setChecked(True)
        self.groupStep.addAction(self.actionStepCurrent)

        # All steps
        self.actionStepAll = self.menuStep.addAction('All')
        self.actionStepAll.setCheckable(True)
        self.groupStep.addAction(self.actionStepAll)

        self.menuStep.addSeparator()

        # Manual step by index
        self.actionStepIndex = self.menuStep.addAction('By index...')

        # Manual step by value
        self.actionStepName = self.menuStep.addAction('By value...')

        self.menuContext.addSeparator()

        # Add ROI
        self.actionRoiAdd = self.menuContext.addAction('Add new ROI...')

        # Delete ROI
        self.menuRoiDelete = self.menuContext.addMenu('Delete ROI')
        self.menuRoiDelete.triggered.connect(self.on_menuRoiDelete_triggered)

        # Show spectra for
        self.menuRoiSpectrum = self.menuContext.addMenu('Show spectra of')
        self.menuRoiSpectrum.triggered.connect(
            self.on_menuRoiSpectrum_triggered
        )
        self.groupRoiSpectrum = QtWidgets.QActionGroup(self.menuRoiSpectrum)

        # Total area spectrum
        self.actionTotalArea = self.menuRoiSpectrum.addAction('total area')
        self.actionTotalArea.setCheckable(True)
        self.actionTotalArea.setChecked(True)
        self.groupRoiSpectrum.addAction(self.actionTotalArea)
        self.menuRoiSpectrum.addSeparator()

        self.imageDetector.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.imageDetector.customContextMenuRequested.connect(
            self.on_menuContext_requested
        )

        self.menuContext.addSeparator()

        self.menuResize = self.menuContext.addMenu('Resize data image')
        self.menuResize.triggered.connect(self.on_menuResize_triggered)

        self.actionResizeDefault = self.menuResize.addAction('Default')
        self.actionResizeNative = self.menuResize.addAction('Native')
        self.actionResizeFactor = self.menuResize.addAction('Factor...')

        self.menuMouseMode = self.menuContext.addMenu('Mouse mode')
        self.menuMouseMode.triggered.connect(self.on_menuMouseMode_triggered)
        self.groupMouseMode = QtWidgets.QActionGroup(self.menuMouseMode)

        self.actionMouseModeAxes = self.menuMouseMode.addAction('Axes')
        self.actionMouseModeAxes.setCheckable(True)
        self.actionMouseModeAxes.setChecked(True)
        self.groupMouseMode.addAction(self.actionMouseModeAxes)

        self.actionMouseModeProj = self.menuMouseMode.addAction('Projection')
        self.actionMouseModeProj.setCheckable(True)
        self.actionMouseModeProj.setEnabled(self.proj_dev is not None)
        self.groupMouseMode.addAction(self.actionMouseModeProj)

        if self.proj_dev is not None:
            self.actionShowProj = self.menuContext.addAction(
                'Show projection...')

            # TODO: Fix like fastPlot axes copy
            self.menuCopyProj = self.menuContext.addMenu(
                'Copy projection from'
            )
            self.menuCopyProj.aboutToShow.connect(
                self.on_menuCopyProj_aboutToShow
            )
            self.menuCopyProj.triggered.connect(
                self.on_menuCopyProj_triggered
            )

        self.menuContext.addSeparator()
        self.actionEditTitle = self.menuContext.addAction('Edit title...')

        # Acceleration method
        try:
            add_pixel_element
        except NameError:
            accel_str = 'Acceleration: native'
        else:
            accel_str = 'Acceleration: ufunc'

        self.menuContext.addSeparator()
        self.actionAccelMethod = self.menuContext.addAction(accel_str)
        self.actionAccelMethod.setEnabled(False)

        # main layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        layout.addWidget(self.imageDetector)
        layout.addLayout(self.layoutInfo)
        self.setLayout(layout)

        # Redraws detector image and spectrum
        self.draw_timer = metro.QTimer(self)
        self.draw_timer.setInterval(1000)
        self.draw_timer.timeout.connect(self.on_draw_tick)

        self.rate_timer = metro.QTimer(self)
        self.rate_timer.setInterval(1000)
        self.rate_timer.timeout.connect(self.on_rate_tick)

        self.ch_in.subscribe(self)

        for roi in state.pop('roi', []):
            self._addRoi(*roi)

        active_roi = state.pop('active_roi', None)
        if active_roi is not None:
            self.imageDetector.setActiveRoi(state[1])
            self.actionTotalArea.setChecked(False)
            self.roi_map[active_roi]['actionSpectrum'].setChecked(True)

        projection = state.pop('mouse_proj', args['mouseMode'] == 'projection')

        axes = state.pop('axes', None)
        if axes is not None:
            self.imageDetector.axes['x_min'] = axes[0]
            self.imageDetector.axes['x_max'] = axes[1]
            self.imageDetector.axes['y_min'] = axes[2]
            self.imageDetector.axes['y_max'] = axes[3]
            self.imageDetector._updateRects()

        if self.proj_dev is not None and projection:
            self.actionMouseModeProj.setChecked(True)
            self.on_menuMouseMode_triggered(self.actionMouseModeProj)

        if self.proj_dev is not None and self.proj_dev._parent == self:
            self.imageDetector.scale_x = self.proj_dev.scale_x
            self.imageDetector.scale_y = self.proj_dev.scale_y
            self.imageDetector.offset_x = self.proj_dev.offset_x
            self.imageDetector.offset_y = self.proj_dev.offset_y

        self.shortcutUndoProjection = QtWidgets.QShortcut(
            QtGui.QKeySequence('CTRL+Y'), self,
            context=QtCore.Qt.WindowShortcut
        )
        self.shortcutUndoProjection.activated.connect(
            self.on_shortcutUndoProjection_activated
        )

        if self.ch_in.isStatic():
            return

        self.measure_connect(stopped=self.measuringStopped)
        self.measure_connect(started=self.rate_timer.start,
                             stopped=self.rate_timer.stop)

        meas = self.measure_getCurrent()

        if meas is not None:
            # If this device was created during a measurement, the
            # signal connections have not been made, so wire it up
            # by hand for the moment.

            self.rate_timer.start()
            meas.finalized.connect(self.rate_timer.stop)

        self.draw_timer.start()

    def finalize(self):
        self.draw_timer.stop()
        self.rate_timer.stop()

        try:
            self.ch_in.unsubscribe(self)
        except AttributeError:
            pass

        if self.proj_dev is not None and self.proj_dev._parent == self:
            self.proj_dev.close()

        for roi in self.roi_map.values():
            roi['channelRate'].close()
            roi['channelCounts'].close()
            roi['channelSpecX'].close()
            roi['channelSpecY'].close()

        self.ch_mtx.close()
        self.ch_xspec.close()
        self.ch_yspec.close()

        # Prevent leak
        for name in self.roi_map.keys():
            self.roi_map[name]['update'] = None

        self.roi_map = {}

    def serialize(self):
        active_roi = self.imageDetector.active_roi

        if self.proj_dev is not None and self.proj_dev._parent == self:
            internal_proj_state = {}
            self.proj_dev._serialize(internal_proj_state)  # PRIVATE API
        else:
            internal_proj_state = None

        return {
            'roi': [(x['name'], x['coords'][0], x['coords'][1],
                     x['coords'][2], x['coords'][3])
                    for x in self.roi_map.values()],
            'active_roi': active_roi['name']
                if active_roi is not None else None,  # noqa
            'mouse_proj': self.actionMouseModeProj.isChecked(),
            'axes': [self.imageDetector.axes['x_min'],
                     self.imageDetector.axes['x_max'],
                     self.imageDetector.axes['y_min'],
                     self.imageDetector.axes['y_max']],
            'internal_proj': internal_proj_state
        }

    @staticmethod
    def isChannelSupported(channel):
        if channel.shape != 2:
            raise ValueError('hist2d only supports 2d channels')

        return channel.shape == 2

    def _addRoi(self, name, x0, y0, x1, y1):
        rate_channel = metro.NumericChannel(self, name + '_rate', shape=0,
                                            hint='waveform', freq='cont')

        counts_channel = metro.NumericChannel(self, name + '_counts', shape=0,
                                              hint='waveform', freq='step')

        xspec_channel = metro.NumericChannel(self, name + '_xspec', shape=1,
                                             hint='indicator', freq='step')

        yspec_channel = metro.NumericChannel(self, name + '_yspec', shape=1,
                                             hint='indicator', freq='step')

        try:
            color = self.roi_color_pool.pop()
        except IndexError:
            color = QtCore.Qt.white

        labelName = QtWidgets.QLabel(name)
        labelName.setStyleSheet('color: {0};'.format(
            QtGui.QColor(color).name())
        )
        labelName.setToolTip('X {0}:{2}\nY {1}:{3}'.format(x0, y0, x1, y1))

        labelRate = QtWidgets.QLabel('0 Hz')
        labelRate.setStyleSheet('color: white;')

        labelCounts = QtWidgets.QLabel('0')
        labelCounts.setStyleSheet('color: white;')

        labelLinks = widgets.ChannelLinksLabel()
        labelLinks.setContextMenu(self.menuChannelLink)
        labelLinks.setStyleSheet('color: white;')
        labelLinks.addChannel(rate_channel, 'rate')
        labelLinks.addChannel(counts_channel, 'counts')
        labelLinks.addChannel(xspec_channel, 'x')
        labelLinks.addChannel(yspec_channel, 'y')

        row_idx = self.layoutInfo.rowCount()
        self.layoutInfo.addWidget(labelName, row_idx, 1,
                                  QtCore.Qt.AlignLeft)
        self.layoutInfo.addWidget(labelRate, row_idx, 2,
                                  QtCore.Qt.AlignRight)
        self.layoutInfo.addWidget(labelCounts, row_idx, 3,
                                  QtCore.Qt.AlignRight)
        self.layoutInfo.addWidget(labelLinks, row_idx, 4,
                                  QtCore.Qt.AlignRight)

        actionDelete = self.menuRoiDelete.addAction(name)
        actionDelete.setData(name)

        actionSpectrum = self.menuRoiSpectrum.addAction(name)
        actionSpectrum.setData(name)
        actionSpectrum.setCheckable(True)
        actionSpectrum.setChecked(False)
        self.groupRoiSpectrum.addAction(actionSpectrum)

        self.roi_map[name] = {
            'name': name,
            'coords': [x0, y0, x1, y1],
            'color': color,
            'shape': None,
            'visible': True,
            'volatile': True,

            'totalHits': 0,
            'hitsLastSec': 0,

            'channelRate': rate_channel,
            'channelCounts': counts_channel,
            'channelSpecX': xspec_channel,
            'channelSpecY': yspec_channel,

            'labelName': labelName,
            'labelRate': labelRate,
            'labelCounts': labelCounts,
            'labelLinks': labelLinks,
            'actionDelete': actionDelete,
            'actionSpectrum': actionSpectrum,

            # Kind of a hack right now, but we would need significant
            # refactoring to make this nicer.
            'update': self._updateRoi
        }

        self.imageDetector.invalidate()
        self.imageDetector.repaint()

    def _removeRoi(self, name):
        roi = self.roi_map[name]

        self.roi_color_pool.append(roi['color'])

        roi['channelRate'].close()
        roi['channelCounts'].close()
        roi['channelSpecX'].close()
        roi['channelSpecY'].close()

        self.layoutInfo.removeWidget(roi['labelName'])
        self.layoutInfo.removeWidget(roi['labelRate'])
        self.layoutInfo.removeWidget(roi['labelCounts'])
        self.layoutInfo.removeWidget(roi['labelLinks'])

        roi['labelName'].hide()
        roi['labelRate'].hide()
        roi['labelCounts'].hide()
        roi['labelLinks'].hide()

        self.menuRoiDelete.removeAction(roi['actionDelete'])
        self.groupRoiSpectrum.removeAction(roi['actionSpectrum'])
        self.menuRoiSpectrum.removeAction(roi['actionSpectrum'])

        del self.roi_map[name]

        self.imageDetector.invalidate()
        self.imageDetector.repaint()

    def _updateRoi(self, name):
        roi = self.roi_map[name]
        roi['labelCounts'].setText(str(roi['totalHits'])
                                   if not roi['volatile']
                                   else '---')

    def _getCurrentSelectedStep(self):
        index = self.ch_in.getSubscribedStep(self)

        if index == metro.NumericChannel.CURRENT_STEP:
            value = self.ch_in.getStepCount() - 1
        elif index == metro.NumericChannel.ALL_STEPS:
            value = 0
        else:
            value = index

        return value

    @metro.QSlot()
    def measuringStopped(self):
        data = self.ch_in.getData(metro.NumericChannel.CURRENT_STEP)

        if data is None:
            return

        mtx = projectMatrix(data, self.size_x, self.size_y)

        self.ch_mtx.addData(mtx)

        self.ch_xspec.addData(mtx.sum(axis=0).astype(int))
        self.ch_yspec.addData(mtx.sum(axis=1).astype(int))

        for roi in self.roi_map.values():
            roi['channelCounts'].addData(roi['totalHits'])

            coords = roi['coords']
            sub_mtx = mtx[coords[1]:coords[3], coords[0]:coords[2]]

            roi['channelSpecX'].addData(sub_mtx.sum(axis=0).astype(int))
            roi['channelSpecY'].addData(sub_mtx.sum(axis=1).astype(int))

    def dataSet(self, pos):
        if self.proj_dev is not None and self.proj_dev._parent == self:
            self.imageDetector.scale_x = self.proj_dev.scale_x
            self.imageDetector.scale_y = self.proj_dev.scale_y
            self.imageDetector.offset_x = self.proj_dev.offset_x
            self.imageDetector.offset_y = self.proj_dev.offset_y

        if pos is None or len(pos) == 0:
            mtx = numpy.zeros((self.size_x, self.size_y), dtype=numpy.int32)
            self.total_hits = 0
        else:
            mtx = projectMatrix(pos, self.size_x, self.size_y)
            self.total_hits = int(mtx.sum())

        self.labelTotalCounts.setText(str(self.total_hits))
        self.imageDetector.setMatrix(mtx)

        self.imageDetector.repaint()

    def dataAdded(self, pos):
        pos = filterWindow(pos).copy()
        pos[:, 0] *= self.size_x - 1
        pos[:, 1] *= self.size_y - 1
        pos = pos.astype(numpy.int32)

        self.imageDetector.addPoints(pos)

        n_hits = len(pos)
        self.hits_last_sec += n_hits
        self.total_hits += n_hits

        self.dirty = True  # Render on draw tick.

    def dataCleared(self):
        self.imageDetector.clear()

        self.total_hits = 0

        for roi in self.roi_map.values():
            roi['totalHits'] = 0

    @metro.QSlot()
    def on_draw_tick(self):
        if self.dirty:
            self.labelTotalCounts.setText(str(self.total_hits))

            for roi in self.roi_map.values():
                roi['labelCounts'].setText(str(roi['totalHits'])
                                           if not roi['volatile']
                                           else '---')

            self.repaint()
            self.dirty = False

    @metro.QSlot()
    def on_rate_tick(self):
        self.labelTotalRate.setText(str(self.hits_last_sec) + ' Hz')
        self.hits_last_sec = 0

        for roi in self.roi_map.values():
            roi['labelRate'].setText(str(roi['hitsLastSec']) + ' Hz'
                                     if not roi['volatile']
                                     else '---')
            roi['channelRate'].addData(roi['hitsLastSec'])
            roi['hitsLastSec'] = 0

    @metro.QSlot(QtCore.QPoint)
    def on_menuContext_requested(self, pos):
        self.menuContext.popup(self.imageDetector.mapToGlobal(pos))

    # Should be @metro.QSlot(QtCore.QAction)
    def on_menuContext_triggered(self, action):
        if action == self.actionRoiAdd:
            text, confirmed = QtWidgets.QInputDialog.getText(
                None, self.windowTitle(), 'Name for new ROI'
            )

            if not confirmed or not text:
                return

            if text in self.roi_map:
                self.showError('An ROI with that name already exists.')
                return

            quarter_x = int(self.size_x/4)
            quarter_y = int(self.size_y/4)
            self._addRoi(text, quarter_x, quarter_y, 3*quarter_x, 3*quarter_y)

        elif action == self.actionShowProj:
            self.proj_dev.show()

        elif action == self.actionEditTitle:
            text, confirmed = QtWidgets.QInputDialog.getText(
                None, self.windowTitle(), 'Title',
                text=self.imageDetector.bg_title_str
            )

            if not confirmed:
                return

            self.imageDetector.setTitle(text)

    # Should be @metro.QSlot(QtCore.QAction)
    def on_menuStep_triggered(self, action):
        if action == self.actionStepCurrent:
            self.imageDetector.annotation_text = ''
            self.ch_in.setSubscribedStep(
                self, metro.NumericChannel.CURRENT_STEP)

        elif action == self.actionStepAll:
            self.imageDetector.annotation_text = 'All steps'
            self.ch_in.setSubscribedStep(
                self, metro.NumericChannel.ALL_STEPS)

        elif action == self.actionStepIndex:
            # Do not use the device as parent widget to avoid inheriting
            # its stylesheet...
            idx, success = QtWidgets.QInputDialog.getInt(
                None, self.windowTitle(), 'Display step with index:',
                min=0, max=self.ch_in.getStepCount() - 1, step=1,
                value=self._getCurrentSelectedStep()
            )

            if not success:
                return

            try:
                value = self.ch_in.step_values[idx]
            except IndexError:
                value = '?'
            except TypeError:
                value = '?'

            self.imageDetector.annotation_text = 'Step {0} / {1}'.format(idx,
                                                                         value)
            self.ch_in.setSubscribedStep(self, idx)

            self.actionStepCurrent.setChecked(False)
            self.actionStepAll.setChecked(False)

        elif action == self.actionStepName:
            # PRIVATE API
            try:
                step_values = [str(v) for v in self.ch_in.step_values]
            except TypeError:
                return

            value, success = QtWidgets.QInputDialog.getItem(
                None, self.windowTitle(), 'Display step with value:',
                step_values, current=self._getCurrentSelectedStep(),
                editable=False
            )

            if not success:
                return

            try:
                idx = step_values.index(value)
            except ValueError:
                return

            self.imageDetector.annotation_text = 'Step {0} / {1}'.format(
                idx, value
            )

            self.ch_in.setSubscribedStep(self, idx)

            self.actionStepCurrent.setChecked(False)
            self.actionStepAll.setChecked(False)

    # Should be @metro.QSlot(QtCore.QAction)
    def on_menuRoiDelete_triggered(self, action):
        name = action.data()

        if self.imageDetector.active_roi == self.roi_map[name]:
            self.imageDetector.setActiveRoi(None)

        self._removeRoi(name)

    # Should be @metro.QSlot(QtCore.QAction)
    def on_menuRoiSpectrum_triggered(self, action):
        self.imageDetector.setActiveRoi(
            None if action == self.actionTotalArea else action.data())

    # Should be @metro.QSlot(QtCore.Action)
    def on_menuResize_triggered(self, action):
        extra_rect = self.size() - self.imageDetector.size()

        if action == self.actionResizeDefault:
            im_rect = self.imageDetector.sizeHint()
        elif action == self.actionResizeNative:
            im_rect = self.imageDetector.sizeHint(1)
        elif action == self.actionResizeFactor:
            factor, success = QtWidgets.QInputDialog.getDouble(
                None, self.windowTitle(), 'Relative size with respect to '
                'channel count:', value=1
            )

            if not success:
                return

            im_rect = self.imageDetector.sizeHint(factor)

        self.resize(im_rect.width() + extra_rect.width(),
                    im_rect.height() + extra_rect.height())

    def on_menuMouseMode_triggered(self, action):
        if action == self.actionMouseModeAxes:
            self.imageDetector.setMouseMode('axes')
        elif action == self.actionMouseModeProj:
            self.imageDetector.setMouseMode('projection')

    @metro.QSlot()
    def on_menuCopyProj_aboutToShow(self):
        if self.proj_dev is None:
            return

        self.menuCopyProj.clear()

        proj_cls = self.proj_dev.__class__

        for dev in metro.getAllDevices():
            if dev is not self.proj_dev and dev.__class__ == proj_cls:
                self.menuCopyProj.addAction(dev._name)

    def on_menuCopyProj_triggered(self, action):
        copied_device = metro.getDevice(action.text())

        self.proj_dev.scale_x = copied_device.scale_x
        self.proj_dev.scale_y = copied_device.scale_y
        self.proj_dev.offset_x = copied_device.offset_x
        self.proj_dev.offset_y = copied_device.offset_y

        self.imageDetector._updateProj()
        self.imageDetector.invalidate()
        self.imageDetector.repaint()

    @metro.QSlot()
    def on_shortcutUndoProjection_activated(self):
        if self.proj_dev is not None:
            self.imageDetector.popProj()

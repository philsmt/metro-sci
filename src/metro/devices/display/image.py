
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import math
import time

import numpy

import metro
from metro.external import pyqtgraph
from metro.devices.abstract import fittable_plot

pyqtgraph.setConfigOptions(antialias=False)


class Device(metro.WidgetDevice, metro.DisplayDevice, fittable_plot.Device):
    ui_file = None

    arguments = {
        'channel': metro.ChannelArgument(type_=metro.DatagramChannel),
        'scale_to_fit': False,
        'history_streak': -1
    }

    def prepare(self, args, state):
        self.scale_to_fit = args['scale_to_fit']
        self.history_streak = args['history_streak']

        self.displayImage = pyqtgraph.ImageView(self)
        self.displayImage._opt_2d_parallel_profiles = True

        view = self.displayImage.getView()
        view.setAspectLocked(False)

        menu = view.menu
        menu.addSeparator()

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
            from metro.external.pyqtgraph.graphicsItems.GradientEditorItem \
                import Gradients
            self.displayImage.ui.histogram.gradient.restoreState(
                Gradients['viridis'])

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

    def dataAdded(self, d):
        if self.history_streak > 0:
            d = numpy.squeeze(d)

            # Remove any additional axes
            while len(d.shape) > 1:
                d = d[-1]

            if self.history_buffer is None or \
                    self.history_buffer.shape[1] != len(d):
                self.history_buffer = numpy.zeros(
                    (self.history_streak, len(d)), dtype=d.dtype)

            # Pretty expensive for now
            self.history_buffer = numpy.roll(self.history_buffer, 1,
                                             axis=0)
            self.history_buffer[0, :] = d

            # Draw the history buffer now
            d = self.history_buffer

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

        if self.scale_to_fit:
            view = self.displayImage.ui.graphicsView
            scale = [d.shape[1]/d.shape[0], view.height() / view.width()]
        else:
            scale = None

        start = time.time()
        self.displayImage.setImage(d, autoLevels=z_scale, autoRange=False,
                                   scale=scale)
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

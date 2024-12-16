
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import metro
import pyqtgraph


class Device(metro.WidgetDevice, metro.DisplayDevice):
    ui_file = None

    def prepare(self, args, state, bg_title=None):
        self.plot_widget = pyqtgraph.PlotWidget(antialias=True)
        self.plot_widget.scene().sigMouseMoved.connect(self.mouseMoved)

        layout = metro.QtWidgets.QVBoxLayout()
        layout.addWidget(self.plot_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.plot_item = self.plot_widget.getPlotItem()

        if bg_title is not None:
            self.orig_PlotItem_paint = self.plot_item.paint
            self.plot_item.paint = self.PlotItem_paint

            self.bg_title_str = bg_title
            self.bg_title_pen = metro.QtGui.QColor(255, 70, 70, 60)

            self._findTitleMetric()

    def finalize(self):
        try:
            # Prevent leak
            self.plot_item.paint = self.orig_PlotItem_paint
        except AttributeError:
            pass

    def _findTitleMetric(self):
        # Find the maximum font size we can use for the channel name.

        stretch = 100
        point_size = 30
        max_width = self.width() - 100

        if max_width <= 0:
            return

        while True:
            font = metro.QtGui.QFont()
            font.setStyleHint(metro.QtGui.QFont.SansSerif)
            font.setStretch(stretch)
            font.setPointSize(point_size)

            metric = metro.QtGui.QFontMetrics(font)
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

    def resizeEvent(self, event):
        self._findTitleMetric()

    def PlotItem_paint(self, p, options, widget):
        p.setFont(self.bg_title_font)
        p.setPen(self.bg_title_pen)

        p.drawText(
            metro.QtCore.QRect(0, 30, self.plot_widget.geometry().width()-30,
                               self.bg_title_bbox.height()),
            metro.QtCore.Qt.AlignRight, self.bg_title_str
        )

        self.orig_PlotItem_paint(p, options, widget)

    # Should actually be QtCore.QPoint, but recent windows builds of
    # PyQt5 complain about a type mismatch and expect only 'object'
    @metro.QSlot(object)
    def mouseMoved(self, gui_point):
        data_point = self.plot_item.mapToView(gui_point)

        x = data_point.x()
        y = data_point.y()

        self.plot_item.setToolTip('{0:.4g}, {1:.4g}\n{2}'.format(
            x, y, bin(int(x))[2:].zfill(8)
        ))

    def addSubscriptionMenu(self, menu=None):
        if menu is None:
            menu = self.plot_widget.getPlotItem().getViewBox().menu
            menu.addSeparator()

        # Show step
        self.menuStep = menu.addMenu('Choose step')
        self.menuStep.triggered.connect(self.on_menuStep_triggered)
        self.groupStep = metro.QtWidgets.QActionGroup(self.menuStep)

        # Current step
        self.actionStepCurrent = self.menuStep.addAction('Current')
        self.actionStepCurrent.setData('__current__')
        self.actionStepCurrent.setCheckable(True)
        self.actionStepCurrent.setChecked(True)
        self.groupStep.addAction(self.actionStepCurrent)

        # All steps
        self.actionStepAll = self.menuStep.addAction('All')
        self.actionStepAll.setData('__all__')
        self.actionStepAll.setCheckable(True)
        self.groupStep.addAction(self.actionStepAll)

        self.menuStep.addSeparator()

        # Manual step by index
        actionStepIndex = self.menuStep.addAction('By index...')
        actionStepIndex.setData('__by_index__')

        # Manual step by value
        actionStepName = self.menuStep.addAction('By value...')
        actionStepName.setData('__by_value__')

    def _getCurrentSelectedStep(self):
        index = self.channel.getSubscribedStep(self)

        if index == metro.NumericChannel.CURRENT_STEP:
            value = self.channel.getStepCount() - 1
        elif index == metro.NumericChannel.ALL_STEPS:
            value = 0
        else:
            value = index

        return value

    # Should be @metro.QSlot(metro.QtCore.QAction)
    def on_menuStep_triggered(self, action):
        name = action.data()

        if name == '__current__':
            self.plot_widget.getPlotItem().setTitle(None)

            self.subscriptionChanged(metro.NumericChannel.CURRENT_STEP)
            self.channel.setSubscribedStep(self,
                                           metro.NumericChannel.CURRENT_STEP)

        elif name == '__all__':
            self.plot_widget.getPlotItem().setTitle('All steps',
                                                    color='00FFFF')

            self.subscriptionChanged(metro.NumericChannel.ALL_STEPS)
            self.channel.setSubscribedStep(self,
                                           metro.NumericChannel.ALL_STEPS)

        elif name == '__by_index__':
            idx, success = metro.QtWidgets.QInputDialog.getInt(
                None, self.windowTitle(), 'Display step with index:',
                min=0, max=self.channel.getStepCount()-1, step=1,
                value=self._getCurrentSelectedStep()
            )

            if not success:
                return

            try:
                value = self.channel.step_values[idx]
            except IndexError:
                value = '?'
            except TypeError:
                value = '?'

            self.plot_widget.getPlotItem().setTitle(
                'Step {0} / {1}'.format(idx, value), color='00FFFF'
            )

            self.subscriptionChanged(idx)
            self.channel.setSubscribedStep(self, idx)

            self.actionStepCurrent.setChecked(False)
            self.actionStepAll.setChecked(False)

        elif name == '__by_value__':
            # PRIVATE API
            try:
                step_values = [str(v) for v in self.channel.step_values]
            except TypeError:
                return

            value, success = metro.QtWidgets.QInputDialog.getItem(
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

            self.plot_widget.getPlotItem().setTitle(
                'Step {0} / {1}'.format(idx, value), color='00FFFF'
            )

            self.subscriptionChanged(idx)
            self.channel.setSubscribedStep(self, idx)

            self.actionStepCurrent.setChecked(False)
            self.actionStepAll.setChecked(False)

    def subscriptionChanged(self, step_idx):
        pass

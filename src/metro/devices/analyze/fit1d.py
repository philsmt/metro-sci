
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import numpy
from scipy.optimize import curve_fit

import metro
from metro.frontend import widgets
from metro.devices.abstract import fittable_plot


def gaussian(x, y0, A, x0, s):
    return y0+(0.3989422804/s)*A*numpy.exp((-1/2)*((x-x0)/s)**2)


def lorentzian(x, y0, A, x0, l):
    return y0+(0.15915494309*A*l)/((x-x0)**2+((1/2)*l)**2)


class Device(metro.WidgetDevice, fittable_plot.FittingCallback):
    arguments = {
        # DeviceArgument is leaking?
        'tag': 'fit',
        'plotDev': metro.DeviceArgument('abstract.fittable_plot')
    }

    def prepare(self, args, state):
        self.tag = args['tag']
        self.plotdev = args['plotDev']

        self.last_data_x = None
        self.last_data_y = None
        self.last_fit_x = None
        self.last_fit_y = None

        self.fitting_enabled = False
        self.drawing_enabled = False

        self.area_corr_arg = -1

        self.iteration_cap = 50

        self.func = lambda x: x

        self.args = []
        self.area_channel = metro.StreamChannel(
            self, 'area', freq='scheduled', hint='waveform', transient=True,
            buffering=False
        )

        self.menuChannelLink = widgets.ChannelLinkMenu()
        self.labelAreaLink.setContextMenu(self.menuChannelLink)
        self.labelAreaLink.addChannel(self.area_channel, '&lt;area&gt;')

        self.args_channels = []
        self.guess_widgets = []
        self.value_widgets = []
        self.stdev_widgets = []

        if state is not None:
            self.checkEnableFitting.setChecked(state[0])
            self.checkShowPlot.setChecked(state[1])
            self.checkAreaCorr.setChecked(state[2])
            self.checkStoreChannels.setChecked(state[4])
            self.editIterationCap.setValue(state[5])
            self.checkGaussian.setChecked(state[6])
            self.checkLorentzian.setChecked(state[7])
            self.checkPolynomial.setChecked(state[8])
            self.editPolynomialDegree.setValue(state[9])
            self.editCustomFunc.setText(state[11])  # Always before 10!
            self.checkCustomFunc.setChecked(state[10])
            if self.checkGaussian.isChecked():
                # We have to manually toggle it again, since it is
                # toggled already by default.
                self.on_checkGaussian_toggled(True)

            for i in range(len(state[12])):
                self.guess_widgets[i].setText(state[12][i])

            self.selectAreaCorrArg.setCurrentIndex(state[3])
        else:
            self.on_checkGaussian_toggled(True)

        self.plotdev.addFittingCallback(self)

    def finalize(self):
        self.plotdev.removeFittingCallback(self)
        self.plotdev = None

        self.area_channel.close()
        for ch in self.args_channels:
            ch.close()

        self.guess_widgets.clear()
        self.value_widgets.clear()
        self.stdev_widgets.clear()

    def serialize(self):
        return (self.checkEnableFitting.isChecked(),    # 0
                self.checkShowPlot.isChecked(),         # 1
                self.checkAreaCorr.isChecked(),         # 2
                self.selectAreaCorrArg.currentIndex(),  # 3
                self.checkStoreChannels.isChecked(),    # 4
                self.editIterationCap.value(),          # 5
                self.checkGaussian.isChecked(),         # 6
                self.checkLorentzian.isChecked(),       # 7
                self.checkPolynomial.isChecked(),       # 8
                self.editPolynomialDegree.value(),      # 9
                self.checkCustomFunc.isChecked(),       # 10
                self.editCustomFunc.text(),             # 11
                [self.guess_widgets[i].text() for i in range(len(self.args))])

    def dataAdded(self, x, y):
        self.last_data_x = x
        self.last_data_y = y

        if not self.fitting_enabled or self.func is None:
            return

        self._fit(x, y)

    def _fit(self, x, y):
        p0 = []
        for i in range(len(self.args)):
            text = self.guess_widgets[i].text()
            p0.append(float(text) if text else 1)

        try:
            coeff, cov = curve_fit(self.func, x, y, p0=p0,
                                   maxfev=self.iteration_cap)
        except RuntimeError:
            coeff = numpy.full((len(p0),), numpy.nan)
            fit_failed = True
        else:
            fit_failed = False

        try:
            diag = numpy.diag(cov)

            if numpy.less(diag, 0).any():
                raise ValueError('negative diagonal element')

            stdevs = numpy.sqrt(numpy.diag(cov))
        except:  # noqa: E722
            stdevs = numpy.full((len(p0),), numpy.nan)

        for i in range(len(coeff)):
            self.value_widgets[i].setText(str(coeff[i]))
            self.stdev_widgets[i].setText(str(stdevs[i]))
            self.args_channels[i].addData(coeff[i])

        if fit_failed:
            return

        fit_x = numpy.linspace(x[0], x[-1], 200)
        fit_y = self.func(fit_x, *coeff)

        if self.drawing_enabled:
            self.plotdev.addFittedCurve(self.tag, fit_x, fit_y)

        area_corr = coeff[self.area_corr_arg] if self.area_corr_arg > -1 else 0
        area = numpy.trapz(numpy.abs(fit_y - area_corr), fit_x)
        self.displayAreaValue.setText(str(area))

        self.area_channel.addData(area)

        self.last_fit_x = fit_x
        self.last_fit_y = fit_y

    def _setPolynomialFunc(self, degree):
        args_list = ['c' + str(i) for i in range(degree+1)]

        return self._setFunc('x0,{0}: numpy.polyval(({1}), x-x0)'.format(
            ','.join(args_list), ','.join(reversed(args_list))
        ))

    def _setFunc(self, code_str):
        if not code_str:
            self.func = None
            return

        try:
            func = eval('lambda x,' + code_str)
        except SyntaxError as e:
            self.func = None
            self.showError(str(e))
            return

        if not callable(func):
            self.func = None
            self.showError("The created code object is not callable")
            return

        self.func = func

        args = [arg.strip() for arg in code_str.split(':')[0].split(',')]
        self.args = args

        # Add any missing rows
        for row_idx in range(self.layoutParameters.rowCount()-2, len(args)):
            # Use row_idx+2 to account for header and area!

            name_widget = widgets.ChannelLinksLabel(self)
            name_widget.setContextMenu(self.menuChannelLink)
            guess_widget = metro.QtWidgets.QLineEdit(self)
            value_widget = metro.QtWidgets.QLabel('', self)
            stdev_widget = metro.QtWidgets.QLabel('', self)

            self.layoutParameters.addWidget(name_widget,  row_idx+2, 0)
            self.layoutParameters.addWidget(guess_widget, row_idx+2, 1)
            self.layoutParameters.addWidget(value_widget, row_idx+2, 2)
            self.layoutParameters.addWidget(stdev_widget, row_idx+2, 3)

            self.guess_widgets.append(guess_widget)
            self.value_widgets.append(value_widget)
            self.stdev_widgets.append(stdev_widget)

        # Hide all
        for row_idx in range(2, self.layoutParameters.rowCount()):
            for col_idx in range(self.layoutParameters.columnCount()):
                self.layoutParameters.itemAtPosition(
                    row_idx, col_idx
                ).widget().hide()

            self.layoutParameters.itemAtPosition(
                row_idx, 0
            ).widget().clearLinks()

        # Add any missing channels
        transient = not self.checkStoreChannels.isChecked()

        for idx in range(len(self.args_channels), len(args)):
            self.args_channels.append(metro.StreamChannel(
                self, str(idx), freq='scheduled', hint='waveform',
                buffering=False, transient=transient
            ))

        self.selectAreaCorrArg.clear()

        # Show the relevant ones
        for idx in range(len(args)):
            for col_idx in range(self.layoutParameters.columnCount()):
                self.layoutParameters.itemAtPosition(
                    idx+2, col_idx
                ).widget().show()

            self.layoutParameters.itemAtPosition(idx+2, 0).widget().addChannel(
                self.args_channels[idx], args[idx]
            )
            self.value_widgets[idx].setText('')
            self.stdev_widgets[idx].setText('')

            self.selectAreaCorrArg.addItem(args[idx])

        self.on_checkAreaCorr_toggled(self.checkAreaCorr.isChecked())

        self.displayAreaValue.setText('')

        self.resize(self.sizeHint())

    @metro.QSlot(bool)
    def on_checkEnableFitting_toggled(self, flag):
        self.fitting_enabled = flag

    @metro.QSlot(bool)
    def on_checkShowPlot_toggled(self, flag):
        self.drawing_enabled = flag

        if flag:
            if self.last_fit_x is None or self.last_fit_y is None:
                return

            self.plotdev.addFittedCurve(self.tag, self.last_fit_x,
                                        self.last_fit_y)
        else:
            self.plotdev.removeFittedCurve(self.tag)

    @metro.QSlot()
    def on_buttonFit_clicked(self):
        if self.last_data_x is None or self.last_data_y is None:
            return

        self._fit(self.last_data_x, self.last_data_y)

    @metro.QSlot(bool)
    def on_checkAreaCorr_toggled(self, flag):
        if flag:
            self.area_corr_arg = self.selectAreaCorrArg.currentIndex()
        else:
            self.area_corr_arg = -1

    @metro.QSlot(bool)
    def on_checkStoreChannels_toggled(self, flag):
        self.area_channel.transient = not flag

        for ch in self.args_channels:
            ch.transient = not flag

    @metro.QSlot(int)
    def on_editIterationCap_valueChanged(self, value):
        self.iteration_cap = value

    @metro.QSlot(bool)
    def on_checkGaussian_toggled(self, flag):
        if not flag:
            return

        self._setFunc('y0,A,x0,s: gaussian(x,y0,A,x0,s)')

    @metro.QSlot(bool)
    def on_checkLorentzian_toggled(self, flag):
        if not flag:
            return

        self._setFunc('y0,A,x0,l: lorentzian(x,y0,A,x0,l)')

    @metro.QSlot(bool)
    def on_checkPolynomial_toggled(self, flag):
        if not flag:
            return

        self._setPolynomialFunc(self.editPolynomialDegree.value())

    @metro.QSlot(int)
    def on_editPolynomialDegree_valueChanged(self, value):
        if not self.checkPolynomial.isChecked():
            return

        self._setPolynomialFunc(value)

    @metro.QSlot(bool)
    def on_checkCustomFunc_toggled(self, flag):
        if not flag:
            return

        self._setFunc(self.editCustomFunc.text())

    @metro.QSlot()
    def on_editCustomFunc_returnPressed(self):
        if not self.checkCustomFunc.isChecked():
            return

        self._setFunc(self.editCustomFunc.text())

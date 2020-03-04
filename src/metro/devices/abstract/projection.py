
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# This device implements the housekeeping necessary for a projection
# device with an input channel and an output channel. For most of the
# source devices, this class is actually treated as an interface by
# using the setInputChannel method.
#
# An implementation has to override init and _process, but is also free
# to override other device functionality like dump/restore. It is also
# expected to provide a QLineEdit (editChannel) and QPushButton
# (buttonFindChannel)for channel management.

# TODO: Handle empty arrays


import metro


class DeferWorker(metro.QObject):
    workFinished = metro.QSignal()

    def __init__(self, dev):
        super().__init__()

        self.dev = dev

    @metro.QSlot()
    def work(self):
        self.result = self.dev._process(self.dev.defer_data)
        self.workFinished.emit()


class Device(metro.WidgetDevice):
    deferWork = metro.QSignal()

    arguments = {
        'channel': metro.ChannelArgument(),
        'count_rows': True,
        'defer_limit': 50000
    }

    def prepare(self, args, state, ch_name, ch_shape):
        self.timerDefer = metro.QTimer(self)
        self.timerDefer.setInterval(500)
        self.timerDefer.setSingleShot(True)
        self.timerDefer.timeout.connect(self.on_timerDefer_timeout)

        self.defer_limit = args['defer_limit']

        self.defer_worker = DeferWorker(self)

        self.defer_thread = metro.QThread()
        self.defer_worker.moveToThread(self.defer_thread)
        self.defer_thread.start()

        self.deferWork.connect(self.defer_worker.work)
        self.defer_worker.workFinished.connect(self.on_defer_finished)

        self.ch_in = args['channel']

        self.ch_out = metro.NumericChannel(self, ch_name, shape=ch_shape,
                                           hint='histogram', freq='cont',
                                           static=self.ch_in.isStatic(),
                                           buffering=self.ch_in.isBuffering())

        self.ch_in.subscribe(self, silent=True)
        self.ch_out.copyLayoutFrom(self.ch_in)
        self._update()

        self.total_rows = 0
        self.rows_last_tick = 0

        if args['count_rows']:
            self.ch_rate = metro.NumericChannel(self, 'rate', shape=0,
                                                hint='waveform', freq='cont',
                                                static=self.ch_in.isStatic())

            self.ch_counts = metro.NumericChannel(self, 'counts', shape=0,
                                                  hint='waveform', freq='step',
                                                  static=self.ch_in.isStatic())

            self.rate_timer = metro.QTimer(self)
            self.rate_timer.setInterval(1000)
            self.rate_timer.timeout.connect(self.on_rate_tick)

            self.measure_connect(self.rate_timer.start, self.rate_timer.stop)

    def finalize(self):
        self.defer_worker.dev = None
        self.defer_thread.quit()
        self.defer_thread.wait()

        self.ch_in.unsubscribe(self)
        self.ch_in = None

        self.ch_out.close()
        self.ch_out = None

        try:
            self.ch_rate.close()
            self.ch_counts.close()
        except AttributeError:
            pass

    def stepEnded(self):
        try:
            self.ch_counts.addData(self.total_rows)
            self.total_rows = 0
        except AttributeError:
            pass

    def _setWidgetModified(self, widget, flag):
        font = widget.font()
        font.setItalic(flag)
        widget.setFont(font)

    def _process(self, rows):
        pass

    def _update(self):
        try:
            self.ch_in
        except AttributeError:
            # This is a special corner case meant to allow calling the
            # _update() path before prepare() is called on to get all
            # the proper variables in place.
            return

        for step_index in range(self.ch_in.getStepCount()):
            rows = self.ch_in.getData(step_index)

            if rows is not None and len(rows) > 0:
                if rows.shape[0] > self.defer_limit:
                    immediate_rows = rows[:self.defer_limit, :]

                    self.timerDefer.start()
                    self.defer_data = rows[self.defer_limit:]
                else:
                    immediate_rows = rows

                self.ch_out.setData(self._process(immediate_rows), step_index)

    def dataSet(self, rows):
        if self.ch_in.current_index != self.ch_out.current_index:
            # See comment of this check in dataCleared()
            return

        if rows is None:
            self.ch_out.clearData()
        else:
            if len(rows) > 0:
                self.ch_out.setData(self._process(rows))

    def dataAdded(self, rows):
        rows = self._process(rows)

        try:
            n_rows = len(rows)
        except TypeError:
            # Allows _process to return None
            return

        self.rows_last_tick += n_rows
        self.total_rows += n_rows

        self.ch_out.addData(rows)

    def dataCleared(self):
        if self.ch_in.current_index != self.ch_out.current_index:
            # This check is very important!
            # Due to the semantics of dataSet and dataCleared being
            # called during beginStep of NumericChannel, ch_in and
            # ch_out may have different current step indices, so we end
            # up clearing the previous step of actual data.
            return

        self.ch_out.clearData()

    @metro.QSlot()
    def on_rate_tick(self):
        self.ch_rate.addData(self.rows_last_tick)
        self.rows_last_tick = 0

    @metro.QSlot()
    def on_timerDefer_timeout(self):
        self.deferWork.emit()

    @metro.QSlot()
    def on_defer_finished(self):
        self.ch_out.addData(self.defer_worker.result)


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# High-speed parallel event source.
#
# This device template enables the easy implementation of a true multi-
# processing capable source device suited for reading out detectors with
# very high count rates. It extends the device of parallel_operator by
# additional functionality common to source devices that are based on
# continuous data acqusition of variable lengths. This includes the
# application of projection devices, calculation of event rates and
# posting to a channel. The operator objects remain compatible.


import json

import metro
from metro.devices.abstract import parallel_operator

# For easier access by inheriting devices
Operator = parallel_operator.Operator


class Device(parallel_operator.Device):
    def prepare(self, operator_cls, operator_args, state, raw_column_count,
                prefilter=lambda d: d, proj_devices=None, count_events=True,
                raw_channel_args={}, target=None, target_cap=5,
                data_pipes=None):

        super().prepare(operator_cls, operator_args, self.newData, state,
                        prefilter, target, target_cap, data_pipes)

        self.ch_raw = metro.NumericChannel(self, 'raw', shape=raw_column_count,
                                           hint='arbitrary', freq='cont',
                                           **raw_channel_args)

        self.proj_devices = {}

        if proj_devices is not None:
            i = 1

            for proj in proj_devices:
                if isinstance(proj, str):
                    name = 'proj{0}'.format(i)
                    entry_point = proj
                    args = {}
                else:
                    name, entry_point, args = proj

                if 'channel' not in args:
                    args['channel'] = self.ch_raw

                if state is not None and name in state:
                    proj_state = state[name]
                else:
                    proj_state = {'visible': False}

                dev = self.createChildDevice(entry_point, name, args,
                                             proj_state)
                self.proj_devices[name] = dev

                header_value = json.dumps((name, entry_point, dev.serialize()))
                self.ch_raw.setHeaderTag('Proj' + str(i),
                                         header_value.replace(' ', ''))

                i += 1

        self.total_events = 0
        self.events_last_sec = 0

        if count_events:
            self.ch_rate = metro.NumericChannel(self, 'rate', shape=0,
                                                hint='waveform', freq='cont')

            self.ch_events = metro.NumericChannel(self, 'events', shape=0,
                                                  hint='waveform', freq='step')

            self.rate_timer = metro.QTimer(self)
            self.rate_timer.setInterval(1000)
            self.rate_timer.timeout.connect(self.rateTimeout)

            self.measure_connect(started=self.rate_timer.start,
                                 stopped=self.rate_timer.stop)

    def finalize(self):
        # Catch the BrokenPipeError in case the process crashed, so that we
        # can still clean up the channels
        try:
            super().finalize()
        except BrokenPipeError as bpe:
            self.showError(str(bpe), bpe)

        # Close the channels last, since the thread might still add
        # some data
        self.ch_raw.close()

        try:
            self.rate_timer.stop()

            self.ch_rate.close()
            self.ch_events.close()
        except AttributeError:
            pass

    def serialize(self):
        proj_state = {}

        for name, obj in self.proj_devices.items():
            proj_state[name] = {}
            obj._serialize(proj_state[name])  # PRIVATE API

        return proj_state

    @metro.QSlot()
    def measuringStarted(self):
        super().measuringStarted()

        self.displayStatus.setText('Measuring')

    @metro.QSlot()
    def measuringStopped(self):
        super().measuringStopped()

        self.displayStatus.setText('Standby')

    @metro.QSlot()
    def operatorReady(self):
        super().operatorReady()

        self.displayStatus.setText('Standby')

    @metro.QSlot(object)
    def newData(self, d):
        n_events = len(d)

        if n_events == 0:
            return

        self.events_last_sec += n_events
        self.total_events += n_events

        self.ch_raw.addData(d)

    @metro.QSlot()
    def stepDone(self):
        try:
            self.ch_events.addData(self.total_events)
        except AttributeError:
            pass

        # Update the counter one last time
        self.displayCount.setText(str(self.total_events))

        self.total_events = 0
        self.events_last_sec = 0

        for d in self.proj_devices.values():
            d.stepEnded()

        super().stepDone()

    @metro.QSlot()
    def rateTimeout(self):
        # No try-except needed since this signal is only connected if
        # events are counted.
        self.displayRate.setText(str(self.events_last_sec))
        self.displayCount.setText(str(self.total_events))

        self.ch_rate.addData(self.events_last_sec)

        self.events_last_sec = 0

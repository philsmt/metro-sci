
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import time

import numpy

from metro.devices.abstract import parallel_event_source


class Operator(parallel_event_source.Operator):
    def prepare(self, args):
        self.center = args['center']
        self.sigma = args['sigma']

    def run(self, active, pipe):
        while active.value:
            samples = numpy.random.normal(self.center, self.sigma, (100, 1))
            pipe.send(samples)

            time.sleep(0.1)


class Device(parallel_event_source.Device):
    arguments = {
        'center': 350,
        'sigma': 30
    }

    def prepare(self, args, state):
        super().prepare(Operator, args, state, 1,
                        proj_devices=['project.window'])

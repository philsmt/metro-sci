
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from random import randint
from time import sleep

import numpy
import numpy.random as nprand

from metro.devices.abstract import parallel_event_source


class Operator(parallel_event_source.Operator):
    def prepare(self, args):
        for k, v in args.items():
            setattr(self, k, v)

        self.getPositionSamples = getattr(self, self.pos_shape)

    def run(self, active, pipe):
        while active.value:
            n_samples = randint(self.counts_min, self.counts_max)

            samples = numpy.zeros((n_samples, 3))

            samples[:, :2] = (self.pos_amplitude *
                              self.getPositionSamples(n_samples) + 0.5)
            samples[:, 2] = (nprand.exponential(self.time_decay, n_samples) *
                             10 + self.time_offset)

            pipe.send(samples)

            sleep(self.sleep_time)

    def gaussian(self, n_samples):
        return nprand.randn(n_samples, 2)

    def exponential(self, n_samples):
        return (nprand.exponential(0.6, (n_samples, 2)) *
                nprand.choice([-1, 1], (n_samples, 2)))

    def uniform(self, n_samples):
        return 4 * nprand.rand(n_samples, 2) - 2

    def lognormal(self, n_samples):
        return 0.2*(nprand.lognormal(1.5, 0.7, (n_samples, 2))-10)

    def beta(self, n_samples):
        return 10*(nprand.beta(2, 10, (n_samples, 2))-0.25)

    def point(self, n_samples):
        return numpy.ones((n_samples, 2)) * (3, 1)


class Device(parallel_event_source.Device):
    arguments = {
        'pos_shape': ('gaussian', 'exponential', 'uniform', 'lognormal',
                      'beta', 'point'),
        'pos_amplitude': 0.1,
        'time_offset': 100,
        'time_decay': 15,
        'counts_min': 300,
        'counts_max': 600,
        'sleep_time': 0.05,
        'raw_counter': False
    }

    descriptions = {
        '__main__': 'This device simulates an MCP-based position sensitive '
                    'detector by generating random sets of data based on a '
                    'predefined shape.',
        'pos_shape': 'The shape of the random position data.',
        'pos_amplitude': 'The amplitude of the random position data in '
                         'channels. This setting is guaranteed to behave '
                         'linearly, but each shape will interpret it '
                         'differently.',
        'time_offset': 'The offset for the virtual decay in channels.',
        'time_decay': 'The lifetime of the virtual decay in channels.',
        'counts_min': 'The minimal amount of counts to generate per cycle.',
        'counts_max': 'The maximal amount of counts to generate per cycle.',
        'sleep_time': 'The approximate of time between the generation of data '
                      'sets in seconds.',
        'raw_counter': 'Whether to create channels for the raw event counts.'
    }

    def prepare(self, args, state):
        super().prepare(Operator, args, state, 3,
                        proj_devices=['project.generic2d', 'project.window'],
                        count_events=args['raw_counter'], target='virtual')

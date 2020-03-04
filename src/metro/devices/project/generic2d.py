
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import math

import numpy

import metro
from metro.devices.abstract import projection


class Device(projection.Device):
    arguments = {
        'tag': 'pos',
        'pre_r': 0.0,
        'post_r': 0.0,
        'scale_x': 1.0,
        'scale_y': 1.0,
        'offset_x': 0.0,
        'offset_y': 0.0
    }
    arguments.update(projection.Device.arguments)

    def prepare(self, args, state):
        self.transform = numpy.zeros((2, 2), dtype=float)
        self.offset = numpy.zeros((2,), dtype=float)

        for w in (self.editXscale, self.editYscale,
                  self.editXoffset, self.editYoffset):
            w.setTypeCast(float)

        if state is not None:
            # FIX: Introduce super_state of device, but this breaks
            # a lot of older files when replaying!
            (self.pre_r, self.post_r, self.scale_x, self.scale_y,
             self.offset_x, self.offset_y) = state
        else:
            self.pre_r = args['pre_r']
            self.post_r = args['post_r']
            self.scale_x = args['scale_x']
            self.scale_y = args['scale_y']
            self.offset_x = args['offset_x']
            self.offset_y = args['offset_y']

        self.editPreRotation.setValue(self.pre_r)
        self.editPostRotation.setValue(self.post_r)
        self.editXscale.setText(str(self.scale_x))
        self.editYscale.setText(str(self.scale_y))
        self.editXoffset.setText(str(self.offset_x))
        self.editYoffset.setText(str(self.offset_y))

        # This will trigger the channel subscription and hence setData
        # for the first time.
        super().prepare(args, None, args['tag'], 2)

    def serialize(self):
        return (self.pre_r, self.post_r, self.scale_x, self.scale_y,
                self.offset_x, self.offset_y)

    def _process(self, rows):
        pos = (rows[:, :2] + self.offset).dot(self.transform) + 0.5

        # Only apply the filter if we're out of bounds
        if pos.min() < 0.0 or pos.max() >= 1.0:
            try:
                # Filter out any hits outside our windows
                pos = pos[numpy.greater(pos, 0).all(axis=1)]
                pos = pos[numpy.less(pos, 1).all(axis=1)]
            except IndexError:
                pass

        return pos

    def _update(self):
        pre_v, post_v = self.pre_r * 3.1415/180, self.post_r * 3.1415/180
        pre_sin, post_sin = math.sin(pre_v), math.sin(post_v)
        pre_cos, post_cos = math.cos(pre_v), math.cos(post_v)

        try:
            self.offset[0] = self.offset_x/self.scale_x - 0.5
            self.offset[1] = self.offset_y/self.scale_y - 0.5

            # First we rotate by the pre matrix, then scale and
            # afterwards rotate again by the post matrix.
            # The components are the product of these three matrices in
            # order.
            self.transform[0, 0] = (pre_cos * post_cos * (+self.scale_x) +
                                    pre_sin * post_sin * (-self.scale_y))

            self.transform[1, 0] = (pre_sin * post_cos * (+self.scale_x) +
                                    pre_cos * post_sin * (+self.scale_y))

            self.transform[0, 1] = (pre_cos * post_sin * (-self.scale_x) +
                                    pre_sin * post_cos * (-self.scale_y))

            self.transform[1, 1] = (pre_sin * post_sin * (-self.scale_x) +
                                    pre_cos * post_cos * (+self.scale_y))
        except ZeroDivisionError:
            pass

        super()._update()

    @metro.QSlot(float)
    def on_editPreRotation_valueChanged(self, v):
        self.pre_r = v

        self._update()

    @metro.QSlot(float)
    def on_editPostRotation_valueChanged(self, v):
        self.post_r = v

        self._update()

    @metro.QSlot(object)
    def on_editXscale_valueChanged(self, value):
        self.scale_x = value
        self._update()

    @metro.QSlot(object)
    def on_editYscale_valueChanged(self, value):
        self.scale_y = value
        self._update()

    @metro.QSlot(object)
    def on_editXoffset_valueChanged(self, value):
        self.offset_x = value
        self._update()

    @metro.QSlot(object)
    def on_editYoffset_valueChanged(self, value):
        self.offset_y = value
        self._update()

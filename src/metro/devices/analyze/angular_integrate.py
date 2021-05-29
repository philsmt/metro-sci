
import numpy as np

import metro


class Device(metro.WidgetDevice):
    arguments = {
        'channel': metro.ChannelArgument(type_=metro.DatagramChannel),
        'r_max': 512,
        'r_len': 512,
        'a_min': 0.0,
        'a_max': -1.0,
        'a_len': 512
    }

    def prepare(self, args, state):
        if args['a_max'] < 0.0:
            args['a_max'] = 2*np.pi

        self.R = (np.arange(1, args['r_len']+1) * args['r_max']) \
            / args['r_len']
        self.Rsq = self.R**2
        self.A = np.linspace(args['a_min'], args['a_max'], args['a_len'])
        self.Q2 = np.zeros((len(self.R), len(self.A)), dtype=np.float64)

        self.dr = self.R[1] - self.R[0]
        self.da = self.A[1] - self.A[0]

        if state is None:
            state = {}

        self.col_center = state.pop('col_center', 1024.0)
        self.row_center = state.pop('row_center', 1024.0)

        self.editCenterX.setTypeCast(float)
        self.editCenterX.setText(str(self.col_center))

        self.editCenterY.setTypeCast(float)
        self.editCenterY.setText(str(self.row_center))

        self.ch_out = metro.DatagramChannel(self, 'radial', hint='indicator',
                                            freq='cont', transient=True)
        self.ch_out.hintDisplayArgument('__default__', 'display.fast_plot')

        self.ch_in = args['channel']
        self.ch_in.subscribe(self)

    def finalize(self):
        self.ch_in.unsubscribe(self)
        self.ch_out.close()

    def serialize(self):
        return {'col_center': self.col_center, 'row_center': self.row_center}

    def dataSet(self, data):
        pass

    def dataAdded(self, M):
        row = -self.R[:, None] * np.cos(self.A)[None, :] + self.row_center
        col = self.R[:, None] * np.sin(self.A)[None, :] + self.col_center

        print(self.row_center, self.col_center)

        row_lo = row.astype(int)
        row_hi = row_lo + 1
        col_lo = col.astype(int)
        col_hi = col_lo + 1

        in_bounds = (row_lo >= 0) & (row_hi < M.shape[0]) & (col_lo >= 0) & \
            (col_hi < M.shape[1])

        row_lo = row_lo[in_bounds]
        row_hi = row_hi[in_bounds]
        col_lo = col_lo[in_bounds]
        col_hi = col_hi[in_bounds]

        t = row[in_bounds] - row_lo
        u = col[in_bounds] - col_lo

        tc = 1 - t
        uc = 1 - u

        self.Q2[in_bounds] = (
            M[row_lo, col_lo] * tc * uc +
            M[row_hi, col_lo] * t * uc +
            M[row_lo, col_hi] * tc * u +
            M[row_hi, col_hi] * t * u
        )

        Q1 = self.Q2.sum(axis=1) * self.da

        self.Q2 /= Q1[:, None]
        Q1 /= (self.Q2.sum(axis=1) * Q1 * self.R).sum() * self.dr * self.da

        self.ch_out.addData(Q1*self.Rsq)

    def dataCleared(self):
        pass

    @metro.QSlot(object)
    def on_editCenterX_valueChanged(self, value):
        self.col_center = value

    @metro.QSlot(object)
    def on_editCenterY_valueChanged(self, value):
        self.row_center = value


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import ctypes
import mmap
import multiprocessing
from time import perf_counter, time

import numpy

import metro

from . import _seq_cov_native as _native


def _bin(data, factor):
    if factor == 1:
        return data
    else:
        return data.reshape(*data.shape[:-1], -1, factor).sum(axis=-1) / factor


def alloc_shared_array(shape, dtype):
    n_elements = 1

    for _s in shape:
        n_elements *= _s

    n_bytes = n_elements * numpy.dtype(dtype).itemsize
    n_pages = n_bytes // mmap.PAGESIZE + 1

    buf = mmap.mmap(-1, n_pages * mmap.PAGESIZE,
                    flags=mmap.MAP_SHARED | mmap.MAP_ANONYMOUS,
                    prot=mmap.PROT_READ | mmap.PROT_WRITE)

    return numpy.frombuffer(memoryview(buf)[:n_bytes],
                            dtype=dtype).reshape(shape)


def compute_main(pipe, p_corr, p_uncorr, buf_A, buf_corr, buf_uncorr, buf_cov):
    buf_add = numpy.zeros_like(buf_corr, dtype=numpy.float32)
    buf_add[:] = 0

    # per incoming shots
    buf_Asum_shots = numpy.zeros((buf_A.shape[1],), dtype=numpy.float32)
    buf_Asum_shots[:] = 0

    # per step
    buf_Asum_step = numpy.zeros((buf_A.shape[1],), dtype=numpy.float32)
    buf_Asum_step[:] = 0

    prev_rows = new_rows = 0

    while True:
        msg = pipe.recv()

        if msg is True:
            prev_rows = new_rows
            new_rows = prev_rows + buf_A.shape[0]

            '''
            Let X be the random variable in the past. The additional
            measurements x extend this to X'. The matrix product X'X
            can then be obtained by XX + xx with the matrix product XX
            and outer vector product (or matrix product) xx.
            '''

            start = perf_counter()

            # The code below is mostly optimized for little to no
            # allocations per iteration.

            # ---------------------------------------------------------
            # correlated product

            # Outer/matrix product of new measurements
            numpy.dot(buf_A.T, buf_A, out=buf_add)

            # Remove the normalization of the previous result
            numpy.multiply(buf_corr, prev_rows, out=buf_corr)

            # Add the additional product to our old product
            numpy.add(buf_corr, buf_add, out=buf_corr)

            # Renormalize to our new amount
            numpy.multiply(buf_corr, 1/new_rows, out=buf_corr)

            # ---------------------------------------------------------
            # uncorrelated product

            # Add up our new measurements
            numpy.sum(buf_A, axis=0, out=buf_Asum_shots)

            # Remove the normalization of the previous result
            # (i.e. turn the average into a sum)
            numpy.multiply(buf_Asum_step, prev_rows, out=buf_Asum_step)

            # Add the new to the old sum
            numpy.add(buf_Asum_step, buf_Asum_shots, out=buf_Asum_step)

            # Renormalize to our new amount
            # (i.e. turn the sum into an average)
            numpy.multiply(buf_Asum_step, 1/new_rows, out=buf_Asum_step)

            # Compute the outer product of our sum vector
            numpy.outer(buf_Asum_step, buf_Asum_step, out=buf_uncorr)

            # ---------------------------------------------------------
            # covariance

            # p_corr * corr - p_uncorr * uncorr
            numpy.subtract(p_corr.value * buf_corr,
                           p_uncorr.value * buf_uncorr,
                           out=buf_cov)

            end = perf_counter()

            # Send the completion signal
            pipe.send((end-start)*1000)

        elif msg is False:
            buf_Asum_step[:] = 0
            new_rows = 0

        elif msg is None:
            break

    pipe.close()


class Device(metro.WidgetDevice):
    arguments = {
        'A_ch': metro.ChannelArgument(optional=False),
        'A_slice': metro.IndexArgument(),
        'A_binning': 1,
        'A_separation': 0.0,
        'B_ch': metro.ChannelArgument(optional=True),
        'B_slice': metro.IndexArgument(),
        'B_binning': 1,
        'B_separation': 0.0,
        'n_rows': 1,
    }

    descriptions = {
        '__main__': 'Sequential covariance mapping of one or two 1D channels.',
        'A_ch': 'Channel for first random variable.',
        'A_slice': 'Slice into A',
        'A_binnng': '(Integer) binning of A',
        'A_separation': '(Float) separation of A',
        'B_ch': 'Channel for second random variable or empty for '
                'autocovariance. (NYI)',
        'B_slice': 'Slice into B',
        'B_binning': '(Integer) binning of B',
        'B_separation': '(Float) separation of B',
        'n_rows': 'Number of rows to add at a time.'
    }

    def prepare(self, args, state):
        self.process = None
        self.n_rows = args['n_rows']

        self.i_A = 0
        self.local_A = None
        self.last_dataStart = 0

        self.A_slice = args['A_slice']
        self.A_binning = args['A_binning']
        self.A_separation = args['A_separation']

        self.timerPoll = metro.QTimer(self)
        self.timerPoll.setInterval(500)
        self.timerPoll.timeout.connect(self.on_poll)

        self.measure_connect(started=self.measuringStarted)

        self._buf = []

        self.ch_corr = metro.DatagramChannel(self, 'corr', hint='indicator',
                                             freq='step')
        self.ch_uncorr = metro.DatagramChannel(self, 'uncorr',
                                               hint='indicator', freq='step')
        self.ch_cov = metro.DatagramChannel(self, 'cov', hint='indicator',
                                            freq='step')
        self.ch_sep = metro.DatagramChannel(self, 'sep', hint='indicator',
                                            freq='step')

        self.ch_A = args['A_ch']
        self.ch_A.subscribe(self)

    def finalize(self):
        self.ch_corr.close()
        self.ch_uncorr.close()
        self.ch_cov.close()
        self.ch_sep.close()

        self.ch_A.unsubscribe(self)

        if self.process is not None:
            self.pipe.send(None)

            self.process.join()
            self.pipe.close()

    def _initBuffers(self, shape_A):
        A_start = self.A_slice.start if self.A_slice.start is not None \
            else 0

        A_stop = self.A_slice.stop if self.A_slice.stop is not None \
            else shape_A

        A_len = A_stop - A_start

        if self.A_separation > 0.0:
            self.n_parts = int(shape_A / self.A_separation)
            self.parts_len = int(self.n_parts * self.A_separation)
            self.n_rows *= self.n_parts

            shape_A = min(A_len, int(self.A_separation)) // self.A_binning
        else:
            shape_A = A_len // self.A_binning

        self.local_A = numpy.zeros((self.n_rows, shape_A), numpy.float32)
        self.local_A[:] = 0

    def _startProcess(self, shape_A):
        local_pipe, remote_pipe = multiprocessing.Pipe(duplex=True)
        self.pipe = local_pipe

        self.buf_A = alloc_shared_array((self.n_rows, shape_A), numpy.float32)
        self.buf_A[:] = 0

        self.buf_corr = alloc_shared_array((shape_A, shape_A), numpy.float32)
        self.buf_corr[:] = 0

        self.buf_uncorr = alloc_shared_array((shape_A, shape_A), numpy.float32)
        self.buf_uncorr[:] = 0

        self.buf_cov = alloc_shared_array((shape_A, shape_A), numpy.float32)
        self.buf_cov[:] = 0

        self.p_corr = multiprocessing.Value(ctypes.c_double,
                                            self.editCorrP.value())
        self.p_uncorr = multiprocessing.Value(ctypes.c_double,
                                              self.editUncorrP.value())

        self.process = multiprocessing.Process(
            target=compute_main,
            args=(remote_pipe, self.p_corr, self.p_uncorr,
                  self.buf_A, self.buf_corr, self.buf_uncorr, self.buf_cov)
        )
        self.process.start()

    def measuringStarted(self):
        self.i_A = 0

        if self.process is not None:
            self.pipe.send(False)
            self.buf_A[:] = 0
            self.buf_corr[:] = 0
            self.buf_uncorr[:] = 0
            self.buf_cov[:] = 0

        self.last_dataStart = time()

    def dataSet(self):
        pass

    def dataAdded(self, d):
        d = numpy.squeeze(d)

        if self.local_A is None:
            self._initBuffers(len(d))

        if self.A_separation > 0.0:
            _native.separate(d[:self.parts_len].astype(numpy.float32),
                             self.local_A[self.i_A:self.i_A+self.n_parts],
                             self.A_separation, self.A_binning, self.A_slice)

            self.ch_sep.addData(self.local_A[self.i_A:self.i_A+self.n_parts])
            self.i_A += self.n_parts
        else:
            self.local_A[self.i_A, :] = _bin(
                d[self.A_slice].astype(numpy.float32), self.A_binning
            )
            self.i_A += 1

        if self.i_A == self.n_rows:
            if self.process is None:
                self._startProcess(self.local_A.shape[1])

            now = time()
            self.last_dataTime = (now - self.last_dataStart)*1000

            self.displayTimeData.setText('{0:.0f} ms'.format(
                self.last_dataTime
            ))
            self.last_dataStart = now

            self.i_A = 0

            self.buf_A[:] = self.local_A

            self.pipe.send(True)

            if not self.timerPoll.isActive():
                self.timerPoll.start()

    def dataCleared(self):
        pass

    @metro.QSlot()
    def on_poll(self):
        if not self.pipe.poll():
            return

        try:
            res = self.pipe.recv()
        except EOFError:
            return

        if not res:
            return

        self.ch_corr.addData(self.buf_corr)
        self.ch_uncorr.addData(self.buf_uncorr)
        self.ch_cov.addData(self.buf_cov)

        self.displayTimeCalc.setText('{0:.0f} ms'.format(res))
        self.displayLoad.setText('{0:.2f}'.format(res / self.last_dataTime))

        self.timerPoll.stop()

    @metro.QSlot(float)
    def on_editCorrP_valueChanged(self, value):
        self.p_corr.value = value

    @metro.QSlot(float)
    def on_editUncorrP_valueChanged(self, value):
        self.p_uncorr.value = value

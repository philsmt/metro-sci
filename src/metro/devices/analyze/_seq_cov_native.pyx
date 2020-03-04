# cython: boundscheck=False, wraparound=False, cdivision=True

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


cimport numpy

def separate(numpy.ndarray[float, ndim=1, mode="c"] inp,
             numpy.ndarray[float, ndim=2, mode="c"] outp,
             double distance, int binning, outp_slice):

    cdef int inp_len = inp.shape[0], outp_len = min(inp_len, <int>distance), \
             n_parts = <int>(inp_len / distance)
    cdef int i, j
    cdef double part_start

    cdef int outp_begin, outp_end

    if outp_slice.start is not None:
        outp_begin = int(outp_slice.start)
    else:
        outp_begin = 0

    if outp_slice.stop is not None:
        outp_end = int(outp_slice.stop)
    else:
        outp_end = outp_len

    for i in range(n_parts):
        part_start = <double>i * distance

        for j in range(outp_begin, outp_end):
            outp[i, (j - outp_begin) // binning] = \
                inp[<int>(part_start + <double>j)]


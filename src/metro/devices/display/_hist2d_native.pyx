
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


cimport cython
cimport numpy


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
def add_pixel(numpy.ndarray[int, ndim=2, mode="c"] mtx,
              numpy.ndarray[int, ndim=2, mode="c"] pos,
              int size_x, int size_y, size_t data_img_bits,
              unsigned char prev_max_value):
    '''
    Add invididual hits to an image matrix.

    This function is the equivalent of the vectorized version of
    add_pixel_element using Cython. It achieves a speedup of around 10x
    for very small hit counts and > 100x for large arrays. This is only
    possible because the inner loop cannot be put together by calls to
    numpy directly and has to contain custom python code. Using Cython
    and completely eliminating all interaction with the interpreter
    within the body of this loop allows for such a massive increase in
    performance then.
    '''

    cdef unsigned char* img_ptr = <unsigned char*>data_img_bits
    cdef unsigned char scaled_value, max_value = prev_max_value
    cdef int height_complement = size_y - 1
    cdef int x, y

    # This loop body is completely free of calls to Python
    for i in range(pos.shape[0]):
        x = pos[i, 0]
        y = pos[i, 1]

        mtx[y, x] += 1

        # 0.005 defines the intensity of non-linear scaling
        scaled_value = <unsigned char>(255 - 255/(1 + 0.005 * mtx[y, x]))
        max_value = max(scaled_value, max_value)

        img_ptr[(height_complement - y) * size_x + x] = scaled_value

    return max_value

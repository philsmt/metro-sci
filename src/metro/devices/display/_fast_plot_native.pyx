# cython: boundscheck=False, wraparound=False, cdivision=True

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from libc.stdio cimport printf
from libc.stdlib cimport abs
from libc.stdint cimport uintptr_t
from libc.string cimport memset
from libc.math cimport fabs, log10, ceil, floor, pow
from cpython.mem cimport PyMem_Malloc, PyMem_Free

cimport numpy


ctypedef fused x_t:
    char
    unsigned char
    short
    unsigned short
    int
    unsigned int
    long
    unsigned long
    long long
    unsigned long long
    float
    double


ctypedef fused y_t:
    char
    unsigned char
    short
    unsigned short
    int
    unsigned int
    long
    unsigned long
    long long
    unsigned long long
    float
    double


cdef struct surface:
    # Image buffer properties
    unsigned char* ptr
    int line_length
    int height_complement  # height reduced by 1

    # Position and size of the plot within the image
    int offset_x
    int offset_y
    int plot_width
    int plot_height

    # Axis limits in image space
    int min_x
    int max_x
    int min_y
    int max_y

    # Axis limits in data space
    double start_x
    double end_x
    double start_y
    double end_y

    # Transformation factors between data and image space
    double div_x
    double div_y


cdef inline void draw_pixel(surface* s, int x, int y, int c) nogil:
    # We currently do pixel-level culling since we lose so little
    # performance here. Sorting the set beforehand will probably
    # only scale for very high data sets.

    if x >= s.min_x and x <= s.max_x and y >= s.min_y and y <= s.max_y:
        s.ptr[(s.height_complement - y) * s.line_length + x] = c


cdef void draw_rect(surface* s, int x1, int y1, int w, int h, int c) nogil:
    # Draw a rectangle with x1/y1 as its upper-left edge and size w/h in
    # color c

    cdef int x2 = x1 + w - 1
    cdef int y2 = y1 + h - 1

    for x from x1 <= x <= x2 by 1:
        draw_pixel(s, x, y1, c)
        draw_pixel(s, x, y2, c)

    for y from y1 < y < y2 by 1:
        draw_pixel(s, x1, y, c)
        draw_pixel(s, x2, y, c)


cdef void fill_rect(surface* s, int x1, int y1, int w, int h, int c) nogil:
    # Draw a filled rectangle with x1/y1 as its upper-left edge and size w/h in
    # color c

    cdef int x2 = x1 + w - 1
    cdef int y2 = y1 + h - 1

    for x from x1 <= x <= x2 by 1:
        for y from y1 < y < y2 by 1:
            draw_pixel(s, x, y, c)


cdef inline void draw_square(surface* s, int x, int y, int l, int c) nogil:
    # Draw a square centered around x/y with length l in color c

    draw_rect(s, x - ((l - 1) >> 1), y - ((l - 1) >> 1), l, l, c)


cdef void draw_line(surface* s, int x1, int y1, int x2, int y2, int c) nogil:
    cdef int x, y, dx, dy, ix, iy

    # Swap the coordinates in case x1/y1 is bigger than x2/y2.

    if x2 >= x1:
        dx = x2 - x1
        ix = +1
    elif x2 < x1:
        dx = x1 - x2
        ix = -1

    if y2 >= y1:
        dy = y2 - y1
        iy = +1
    elif y2 < y1:
        dy = y1 - y2
        iy = -1

    # If we have a vertical or horizontal line, we can directly draw
    # them by a simple loop.

    if dx == 0:
        if iy < 0:
            x2 = y1  # Use x2 as swap variable
            y1 = y2
            y2 = x2

        for y from y1 <= y <= y2 by 1:
            draw_pixel(s, x1, y, c)

        return
    elif dy == 0:
        if ix < 0:
            y2 = x1  # Use y2 as swap variable
            x1 = x2
            x2 = y2

        for x from x1 <= x <= x2 by 1:
            draw_pixel(s, x, y1, c)

        return

    # For non-straight lines, apply Bresenham's algorithm. Always loop
    # over the axis with the shorter coordinate difference.

    cdef int error
    x = x1
    y = y1

    if dx >= dy:
        dy <<= 1
        error = dy - dx
        dx <<= 1

        while x != x2:
            draw_pixel(s, x, y, c)

            if error >= 0:
                y += iy
                error -= dx

            x += ix
            error += dy

        draw_pixel(s, x, y, c)
    else:
        dx <<= 1
        error = dx - dy
        dy <<= 1

        while y != y2:
            draw_pixel(s, x, y, c);

            if error >= 0:
                x += ix
                error -= dy

            y += iy
            error += dx

        draw_pixel(s, x, y, c)


def stack(numpy.ndarray[y_t, ndim=2, mode="c"] inp,
          numpy.ndarray[y_t, ndim=2, mode="c"] outp, double stacking):

    cdef int inp_len = inp.shape[1], outp_len = min(inp_len, <int>stacking), \
             stack_height = <int>(inp_len / stacking)
    cdef int i, j, k
    cdef y_t datum

    for i in range(inp.shape[0]):
        for j in range(outp_len):
            datum = <y_t>0

            for k in range(stack_height):
                datum += inp[i, <int>(j + k * stacking)]

            outp[i, j] = datum


def surface_new():
    return <uintptr_t>PyMem_Malloc(sizeof(surface))


def surface_delete(uintptr_t s_bits):
    PyMem_Free(<surface*>s_bits)


def surface_set_geometry(uintptr_t s_bits, uintptr_t image_bits,
                         int line_length, int image_height,
                         numpy.ndarray[int, ndim=1, mode="c"] geometry):
    cdef surface* s = <surface*>s_bits

    s.ptr = <unsigned char*>image_bits
    s.line_length = line_length
    s.height_complement = image_height - 1

    s.offset_x = geometry[0]
    s.offset_y = geometry[1]
    s.plot_width = geometry[2]
    s.plot_height = geometry[3]

    s.min_x = s.offset_x
    s.max_x = s.offset_x + s.plot_width
    s.min_y = s.offset_y
    s.max_y = s.offset_y + s.plot_height


def surface_set_view(uintptr_t s_bits,
                     numpy.ndarray[double, ndim=1, mode="c"] axes,
                     numpy.ndarray[double, ndim=1, mode="c"] transform):
    cdef surface* s = <surface*>s_bits

    s.start_x = axes[0]
    s.end_x = axes[1]
    s.start_y = axes[2]
    s.end_y = axes[3]

    s.div_x = transform[0]
    s.div_y = transform[1]


def surface_clear(uintptr_t s_bits):
    cdef surface* s = <surface*>s_bits

    memset(s.ptr, 0, s.line_length * (s.height_complement+1))


def plot(uintptr_t s_bits,
         numpy.ndarray[x_t, ndim=1, mode="c"] data_x,
         numpy.ndarray[y_t, ndim=1, mode="c"] data_y,
         int color_idx, bint marker):

    if len(data_x) != len(data_y):
        raise ValueError('len(x) != len(y)')

    cdef surface* s = <surface*>s_bits
    cdef int N = data_y.shape[0], i, cur_x, cur_y, last_x, last_y

    cdef int line_color = (color_idx + 1) * 10 + 1
    cdef int symbol_color = line_color + 1

    # Clean up names in here: x/y in terms of data or render coordinates
    # is very misleading! Then we can also stop using s.x_max down there

    with nogil:
        last_x = <int>((<double>data_x[0] - s.start_x) * s.div_x) + s.offset_x
        last_y = <int>((<double>data_y[0] - s.start_y) * s.div_y) + s.offset_y

        if marker and last_x >= s.offset_x and last_x <= s.max_x:
            draw_square(s, last_x, last_y, 5, symbol_color)

        if marker:
            for i in range(1, N):
                cur_x = <int>((<double>data_x[i] - s.start_x) * s.div_x) \
                    + s.offset_x
                cur_y = <int>((<double>data_y[i] - s.start_y) * s.div_y) \
                    + s.offset_y

                if not ((last_x < s.offset_x and cur_x < s.offset_x) or
                        (last_x > s.max_x and cur_x > s.max_x)):
                    draw_line(s, last_x, last_y, cur_x, cur_y, line_color)
                    draw_square(s, cur_x, cur_y, 5, symbol_color)

                last_x = cur_x
                last_y = cur_y

        else:
            for i in range(1, N):
                cur_x = <int>((<double>data_x[i] - s.start_x) * s.div_x) \
                    + s.offset_x
                cur_y = <int>((<double>data_y[i] - s.start_y) * s.div_y) \
                    + s.offset_y

                if not ((last_x < s.offset_x and cur_x < s.offset_x) or
                        (last_x > s.max_x and cur_x > s.max_x)):
                    draw_line(s, last_x, last_y, cur_x, cur_y, line_color)

                last_x = cur_x
                last_y = cur_y


def bars(uintptr_t s_bits,
         numpy.ndarray[x_t, ndim=1, mode="c"] data_x,
         numpy.ndarray[y_t, ndim=1, mode="c"] data_y,
         int color_idx, int width):

    if len(data_x) != len(data_y):
        raise ValueError('len(x) != len(y)')

    cdef surface* s = <surface*>s_bits
    cdef int N = data_y.shape[0], i, cur_x, cur_y, last_x, last_y, y0
    cdef double datum

    cdef int color = (color_idx + 1) * 10 + 1

    with nogil:
        y0 = <int>((<double>0.0 - s.start_y) * s.div_y) + s.offset_y

        for i in range(N):
            datum = <double>data_y[i]

            cur_x = <int>((<double>data_x[i] - s.start_x) * s.div_x) \
                + s.offset_x
            cur_y = <int>((datum - s.start_y) * s.div_y) + s.offset_y

            if cur_x >= s.offset_x and cur_x <= s.max_x:
                if cur_y == y0:
                    draw_line(s, cur_x - width//2, y0, cur_x + width//2, y0,
                              color)
                else:
                    fill_rect(s, cur_x - width//2, min(y0, cur_y), width,
                              abs(cur_y - y0), color)

            last_x = cur_x

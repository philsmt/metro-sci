# flake8: noqa

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import ctypes
from time import time

import numpy
from OpenGL import GL
from PyQt5 import QtCore, QtGui, QtWidgets

import metro


class PlotWidget(QtWidgets.QOpenGLWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.mode = 1

        sf = self.format()
        sf.setRenderableType(1)
        sf.setVersion(2, 1)
        sf.setSamples(0)
        self.setFormat(sf)

        self.dirty = False
        self.data = None

    def sizeHint(self):
        return QtCore.QSize(520, 200)

    def setData(self, d):
        self.data = d
        self.dirty = True
        self.update()

    def initializeGL(self):
        # create a shader for coloring the texture
        vertex_src = '''
attribute vec2 coord2d;
varying vec4 f_color;
uniform float offset_x;
uniform float scale_x;
uniform lowp float sprite;

void main(void) {
    gl_Position = vec4((coord2d.x + offset_x) * scale_x, coord2d.y, 0, 1);
    //f_color = vec4(coord2d.xy / 2.0 + 0.5, 1, 1);
    f_color = vec4(0.0, 0.0, 1.0, 1.0);
    gl_PointSize = 5.0;
}
        '''

        fragment_src = '''
uniform sampler2D mytexture;
varying vec4 f_color;
uniform float sprite;
uniform int color;


void main(void) {
    //gl_FragColor = texture2D(mytexture, gl_PointCoord) * f_color;
    if(color == 0) {
        gl_FragColor = vec4(0.71, 0.71, 1.0, 1.0);
    }
    else {
        gl_FragColor = vec4(0.0, 0.0, 0.78, 1.0);
    }
}
        '''

        self.shader = QtGui.QOpenGLShaderProgram()
        self.shader.addShaderFromSourceCode(QtGui.QOpenGLShader.Vertex,
                                            vertex_src)
        self.shader.addShaderFromSourceCode(QtGui.QOpenGLShader.Fragment,
                                            fragment_src)
        print(self.shader.link())

        self.attr_coord2d = self.shader.attributeLocation('coord2d')
        self.unif_mytexture = self.shader.uniformLocation('mytexture')
        self.unif_sprite = self.shader.uniformLocation('sprite')
        self.unif_color = self.shader.uniformLocation('color')
        self.unif_offset_x = self.shader.uniformLocation('offset_x')
        self.unif_scale_x = self.shader.uniformLocation('scale_x')

        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

        GL.glEnable(GL.GL_POINT_SPRITE)
        GL.glEnable(GL.GL_VERTEX_PROGRAM_POINT_SIZE)

        self.vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

        GL.glLineWidth(1.0)

    def paintGL(self):
        if self.data is None:
            return

        start = time()

        self.shader.bind()
        self.shader.setUniformValue(self.unif_offset_x, 0.1)
        self.shader.setUniformValue(self.unif_scale_x, 0.1)

        GL.glClearColor(0.0, 0.0, 0.0, 0.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)

        if self.dirty:
            #graph = numpy.zeros((N, 2), dtype='<f4')
            #x = numpy.linspace(-10, 10, N)
            #graph[:, 0] = x
            #graph[:, 1] = numpy.sin(x * 10.0) / (1.0 + x * x)

            start = time()
            d = self.data
            d[:, 1] -= d[:, 1].min()
            d[:, 1] /= 0.5*d[:, 1].max()
            d[:, 1] -= 1

            size = d.shape[0] * d.shape[1] * d.itemsize

            GL.glBufferData(GL.GL_ARRAY_BUFFER, size, d, GL.GL_STATIC_DRAW)
            end = time()
            print('buffering', round((end-start), 3), 'ms')

            self.dirty = False

        GL.glEnableVertexAttribArray(self.attr_coord2d)
        GL.glVertexAttribPointer(self.attr_coord2d, 2, GL.GL_FLOAT, False, 0,
                                 None)  # Last argument NOT 0!

        self.shader.setUniformValue(self.unif_color, 0)

        if self.mode == 0:
            self.shader.setUniformValue(self.unif_sprite, 0.0)
            GL.glDrawArrays(GL.GL_LINE_STRIP, 0, self.data.shape[0])
        elif self.mode == 1:
            self.shader.setUniformValue(self.unif_sprite, 2.0)

            self.shader.setUniformValue(self.unif_color, 1)
            GL.glDrawArrays(GL.GL_POINTS, 0, self.data.shape[0])

            self.shader.setUniformValue(self.unif_color, 0)
            GL.glDrawArrays(GL.GL_LINE_STRIP, 0, self.data.shape[0])

        elif self.mode == 2:
            self.shader.setUniformValue(self.unif_sprite, 15.0)
            GL.glDrawArrays(GL.GL_LINE_STRIP, 0, self.data.shape[0])
            self.shader.setUniformValue(self.unif_color, 1)
            GL.glDrawArrays(GL.GL_POINTS, 0, self.data.shape[0])

        end = time()
        diff = end - start

        if diff > 0.0:
            print('draw', round(diff*1000, 3), 'ms')

    def resizeGL(self, w, h):
        GL.glViewport(0, 0, w, h)



class Device(metro.WidgetDevice, metro.DisplayDevice):
    arguments = {
        'channel': metro.ChannelArgument(),
        'index': metro.IndexArgument()
    }

    def prepare(self, args, state):
        self.channel = args['channel']
        self.index = args['index']

        self.plotData = PlotWidget(self)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plotData)

        self.setLayout(layout)

        self.channel.subscribe(self)

    @classmethod
    def isChannelSupported(self, ch):
        return True

    def finalize(self):
        self.channel.unsubscribe(self)

    def dataSet(self, d):
        pass

    def dataAdded(self, d):
        d = d[self.index]
        new_d = numpy.vstack((numpy.linspace(-10, 10, d.shape[0]),
                              d)).astype('<f4').T

        self.plotData.setData(new_d)

    def dataCleared(self):
        pass

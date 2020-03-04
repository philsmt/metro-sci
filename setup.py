#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import subprocess

import numpy
from setuptools import setup, find_packages
from setuptools.extension import Extension
from setuptools.command.build_ext import build_ext
from Cython.Build import cythonize


class build_ext_compiler_specifics(build_ext):
    extra_compile_args = {
        'unix': ['-g0', '-Wno-unused-function', '-Wno-cpp']
    }

    def build_extensions(self):
        compiler = self.compiler.compiler_type

        try:
            extra_compile_args = self.extra_compile_args[compiler].copy()
        except KeyError:
            extra_compile_args = []

        for ext in self.extensions:
            if isinstance(ext.extra_compile_args, dict):
                try:
                    extra_compile_args += ext.extra_compile_args[compiler]
                except KeyError:
                    pass

            ext.extra_compile_args = extra_compile_args

        super().build_extensions()


def find_version():
    try:
        short_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            stderr=subprocess.STDOUT
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    else:
        if short_hash.startswith(b'fatal'):
            return None
        else:
            return short_hash.decode('ascii').strip()


extensions = [
    Extension(
        name, ['src/' + name.replace('.', '/') + '.pyx'],
        include_dirs=[numpy.get_include()],
        language='c',
        extra_compile_args={
            'unix': ['-O3', '-march=native', '-ftree-vectorize',
                     '-frename-registers'],
            'mscv': ['/O2']
        }
    )
    for name in [
        'metro.devices.analyze._seq_cov_native',
        'metro.devices.display._hist2d_native',
        'metro.devices.display._fast_plot_native',
    ]
]


setup(
    name='metro-sci',
    version=find_version() or 'dev',
    author='Philipp Schmidt',
    author_email='philipp.schmidt@xfel.eu',
    description='Framework for experimental control, data acquisition and '
                'online analysis of scientific experiments',
    package_dir={'': 'src'},
    packages=find_packages('src'),
    package_data={
        '': ['*.ui', '*.qml'],
        'metro.frontend': ['logo.png', 'Symbola.ttf']
    },
    entry_points={
        'console_scripts': [
            'metro = metro.main:start_regular',
            'metro2hdf = metro.metro2hdf:main'
        ],
        'metro.device': [
            f'{entry_point} = metro.devices.{entry_point}:Device'
            for entry_point
            in [
                'analyze.fit1d', 'analyze.moving_avg','analyze.scan_matrix',
                'analyze.seq_cov',
                    
                'display.fast_plot', 'display.hist1d', 'display.hist2d',
                'display.image', 'display.ogl_plot', 'display.plot',
                'display.polar_plot', 'display.sorted', 'display.value',
                'display.waveform',

                'project.generic2d', 'project.window',

                'util.measure_blocks', 'util.memory',
                'util.serial_scan_server', 'util.ui_web_proxy',
                
                'util.debug.arguments', 'util.debug.dependencies',
                'util.debug.exception', 'util.debug.fail',
                'util.debug.simple_device',
                
                'util.simulate.camera', 'util.simulate.indicators',
                'util.simulate.logging', 'util.simulate.manual_operators',
                'util.simulate.point_pos', 'util.simulate.random_vector',
                'util.simulate.scalar_abstract', 'util.simulate.scalar_manual',
                'util.simulate.simple_detector',
                'util.simulate.static_waveform', 'util.simulate.vbeamline',
                'util.simulate.vdetector_abstract',
                'util.simulate.vdetector_manual'
            ]
        ],
        'metro.display_device': [
            f'display.{entry_point} = devices.display.{entry_point}:Device'
            for entry_point
            in [
                'fast_plot', 'hist1d', 'hist2d', 'image', 'plot',
                'polar_plot', 'sorted', 'value', 'waveform'
            ]
        ]
    },
    cmdclass={'build_ext': build_ext_compiler_specifics},
    ext_modules=cythonize(extensions, language_level=3, build_dir='build'),

    python_requires='>=3.6',
    install_requires=['typing', 'PyQt5', 'numpy', 'scipy', 'h5py'],

    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'Environment :: Console',
        'Environment :: Win32 (MS Windows)'
        'Environment :: X11 Applications :: Qt',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'Programming Language :: Python :: 3.6',
        'Topic :: Scientific/Engineering :: Information Analysis',
        'Topic :: Scientific/Engineering :: Physics',
    ]
)


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import hashlib
import os
import subprocess
import sys
import time
import traceback
from importlib import resources

import numpy  # noqa

import metro
from metro.services import profiles

if not metro.core_mode:
    from metro.frontend import controller
    from metro.frontend import dialogs
    from metro.devices import display as display_devices

QtCore = metro.QtCore
QtGui = metro.QtGui
QtWidgets = metro.QtWidgets


def _on_exception(*args):
    with open(metro.LOCAL_PATH + '/exceptions.log', 'a') as logfile:
        logfile.write('----------------------------'
                      '----------------------------\n')
        logfile.write('- Unchecked exception caught on {0} -\n'.format(
            time.strftime('%Y/%m/%d at %H:%M:%S'))
        )
        logfile.write('----------------------------'
                      '----------------------------\n')
        traceback.print_exception(*args, file=logfile)
        logfile.write('\n')

    traceback.print_exception(*args)


class AbstractApplication(object):
    statistics_channel_kernel_sources = {
        'sum': 'numpy.sum(x, axis=0)',
        'mean': 'numpy.average(x, axis=0)',
        'median': 'numpy.median(x, axis=0)',
        'range': 'numpy.amax(x, axis=0) - numpy.amin(x, axis=0)',
        'variance': 'numpy.variance(x, axis=0)',
        'stdev': 'numpy.std(x, axis=0)'
    }

    def _bootstrap(self, args, version=None, version_short=None):
        # Install an exception hook to keep the python interpreter on
        # executing after unchecked exceptions. Some platforms will kill
        # a PyQt5 application in this case.
        sys.excepthook = _on_exception

        # Set AppUserModelID for Windows 7 and later so that Metro uses
        # its assigned taskbar icon instead of grabbing the one with the
        # same AppUserModelID (would probably result in no icon at all)
        if os.name == 'nt':
            try:
                myappid = u"{}.{}".format(metro.SRC_ROOT, metro.WINDOW_TITLE)
                from ctypes import windll
                windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except AttributeError:
                pass

        metro.app = self
        metro.experimental = args.experimental

        if args.gc_debug:
            import gc
            gc.set_debug(args.gc_debug)

        self.args = args
        self.last_used_profile = None
        self.indicators = {}

        self.current_meas = None

        self.device_groups = []

        self._channel_loaders = {}

        if version is not None and version_short is None:
            version_short = version

        elif version is None:
            try:
                version_hash = subprocess.check_output(
                    ['git', 'rev-parse', 'HEAD'], stderr=subprocess.STDOUT
                )
            except FileNotFoundError:
                version = None
                version_short = None
            except subprocess.CalledProcessError:
                version = None
                version_short = None
            else:
                if version_hash.startswith(b'fatal'):
                    version = None
                    version_short = None
                else:
                    short_hash = subprocess.check_output(
                        ['git', 'rev-parse', '--short', 'HEAD'],
                        stderr=subprocess.STDOUT
                    )

                    version = version_hash.decode('ascii').strip()
                    version_short = short_hash.decode('ascii').strip()

        metro.version = version
        metro.version_short = version_short

    def _loadProfileDelayed(self, profile):
        # Loading the profile directly before starting the event
        # loop can cause strange bugs and UI freezing. All device
        # code is also written with the assumption that it is
        # already running. So we just fire off an immediate timer
        # that will be executed the moment we started it.
        @QtCore.pyqtSlot()
        def timeout_slot():
            try:
                self.loadProfile(profile)
            except Exception as e:
                self.showException('An error occured on loading a profile:', e)

            self.profile_load_timer = None
            del self.profile_load_timer

        self.profile_load_timer = QtCore.QTimer()
        self.profile_load_timer.setSingleShot(True)
        self.profile_load_timer.setInterval(0)
        self.profile_load_timer.timeout.connect(timeout_slot)
        self.profile_load_timer.start()

    def _loadDevice(self, entry_point, device_class, name, state):
        args = state['arguments']
        abstract_args = {}

        try:
            for key, value in device_class.arguments.items():
                if isinstance(value, metro.AbstractArgument):
                    abstract_args[key] = value.restore(args[key])

        except Exception:
            return False

        # Integrate the computed values of abstract arguments into our
        # arguments dict. Note we may not overwrite the values in the
        # loop above already, since then on any subsequent pass we may
        # fail by passing computed value to the restore() method!
        args.update(abstract_args)

        try:
            metro.createDevice(entry_point, name, args=args, state=state)
        except Exception as e:
            self.showException('An error occured on creating a device:', e)

        return True

    def _loadNormalizedChannel(self, name, state):
        normalize_by = []

        try:
            to_normalize = metro.getChannel(state['to_normalize'])

            for dep_name in state['normalize_by']:
                dep_ch = metro.getChannel(dep_name)
                normalize_by.append(dep_ch)
        except KeyError:
            return False

        arg_channels = normalize_by.copy()
        arg_channels.insert(0, to_normalize)

        by_strs = ['n'+str(i) for i in range(len(normalize_by))]
        kernel_func = eval('lambda x,{0}: x/({1})'.format(','.join(by_strs),
                                                          '*'.join(by_strs)))

        channel = metro.NumericChannel(name, hint='waveform',
                                       freq=state['freq'],
                                       shape=state['shape'])
        channel.setComputing(kernel_func, arg_channels)

        channel._custom = True
        channel._custom_to_normalize = state['to_normalize']
        channel._custom_normalize_by = state['normalize_by']

        return True

    def _loadStatisticsChannel(self, name, state):
        try:
            to_integrate = metro.getChannel(state['to_integrate'])
        except KeyError:
            return False

        kernel_func = eval(
            'lambda x: ' +
            self.statistics_channel_kernel_sources[state['func']]
        )

        channel = metro.NumericChannel(name, hint=state['hint'], freq='step',
                                       shape=state['shape'])
        channel.setIntegrating(kernel_func, [to_integrate])

        channel._custom = True
        channel._custom_to_integrate = state['to_integrate']
        channel._custom_func = state['func']

        return True

    def _loadScriptedChannel(self, name, state):
        act_channels = []

        try:
            for dep_name in state['arg_channels']:
                dep_ch = metro.getChannel(dep_name)
                act_channels.append(dep_ch)
        except KeyError:
            return False

        kernel_object = compile(
            self._wrapScriptedChannelKernel(
                state['arg_variables'], state['kernel_source']
            ), '<kernel>', 'exec'
        )

        if state['init_source']:
            init_object = compile(state['init_source'], '<init>', 'exec')
        else:
            init_object = None

        linked_kernel = self._linkScriptedChannelKernel(
            init_object, kernel_object
        )

        channel = metro.NumericChannel(name, hint=state['hint'],
                                       freq=state['freq'],
                                       shape=state['shape'],
                                       buffing=state['buffering'],
                                       transient=state['transient'])

        if state['mode'] == metro.NumericChannel.COMPUTING_MODE:
            channel.setComputing(linked_kernel, act_channels)
        elif state['mode'] == metro.NumericChannel.INTEGRATING_MODE:
            channel.setIntegrating(linked_kernel, act_channels)
        else:
            # error!
            pass

        channel._custom = True
        channel._custom_arg_variables = state['arg_variables']
        channel._custom_kernel_source = state['kernel_source']
        channel._custom_init_enabled = state['init_enabled']
        channel._custom_init_source = state['init_source']
        channel._custom_init_object = init_object

        return True

    def _loadReplayedChannel(self, name, state):
        # Will fail in core mode

        if state['path'].endswith('.txt'):
            return self._loadReplayedStreamChannel(name, state)

        elif state['path'].endswith('.h5'):
            return self._loadReplayedDatagramChannel(name, state)

        else:
            raise ValueError('unsupported file format for replay')

    def _loadReplayedStreamChannel(self, name, state):
        if state['freq'] != metro.NumericChannel.CONTINUOUS_SAMPLES:
            # Unsupported for now
            return

        from metro.frontend.dialogs import ReplayStreamChannelDialog

        display_arguments = {}

        with open(state['path'], 'r') as fp:
            cur_offset = 0

            # First we read in the header
            for line in fp:
                if line.startswith('# DISPLAY'):
                    key = line[10:line.find(':')]
                    value = line[line.find(':')+2:-1]

                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass

                    display_arguments[key] = value

                elif not line.startswith('#'):
                    body_offset = cur_offset
                    break

                cur_offset += len(line)

        try:
            chan = metro.NumericChannel(
                name, hint=state['hint'], freq=state['freq'],
                shape=state['shape'], static=True
            )
        except ValueError as e:
            metro.app.showError('An occured on creating the channel', str(e))
            return

        chan.display_arguments = display_arguments
        chan._replayed = True
        chan._replayed_path = state['path']

        loader = ReplayStreamChannelDialog.MetroFileLoader(
            state['path'], state['shape'], body_offset
        )

        loader.finished.connect(metro.QSlot()(
            lambda: self.on_stream_loader_finished(name, chan, state)
        ))
        loader.start()

        self._channel_loaders[name] = loader

        return True

    def _loadReplayedDatagramChannel(self, name, state):
        if state['freq'] != metro.DatagramChannel.STEP_SAMPLES:
            # Unsupported for now
            return

        from metro.frontend.dialogs import ReplayDatagramChannelDialog

        try:
            chan = metro.DatagramChannel(
                name, hint=state['hint'], freq=state['freq'], static=True
            )
        except ValueError as e:
            metro.app.showError('An occured on creating the channel', str(e))
            return

        chan._replayed = True
        chan._replayed_path = state['path']

        loader = ReplayDatagramChannelDialog.MetroFileLoader(state['path'])
        loader.finished.connect(metro.QSlot()(
            lambda: self.on_datagram_loader_finished(name, chan, state)
        ))
        loader.start()

        self._channel_loaders[name] = loader

        return True

    def on_stream_loader_finished(self, name, chan, state):
        # projection unsupported for now

        loader = self._channel_loaders[name]
        del self._channel_loaders[name]

        if state['freq'] == metro.NumericChannel.CONTINUOUS_SAMPLES:
            chan.data = [[]] * len(loader.data)

            for i in range(len(loader.data)):
                chan.setData(loader.data[i][0], step_index=i)

            # All other frequencies unsupported for now

    def on_datagram_loader_finished(self, name, chan, state):
        loader = self._channel_loaders[name]
        del self._channel_loaders[name]

        chan.display_arguments = loader.display_arguments
        chan.step_values = loader.step_values
        chan.addData(loader.data[-1])

    def _loadChannel(self, name, state):
        if 'to_normalize' in state:
            return self._loadNormalizedChannel(name, state)
        elif 'to_integrate' in state:
            return self._loadStatisticsChannel(name, state)
        elif 'kernel_source' in state:
            return self._loadScriptedChannel(name, state)
        elif 'path' in state:
            return self._loadReplayedChannel(name, state)

    def loadProfile(self, path):
        actual_path = path if os.path.isfile(path) \
            else '{0}/{1}.json'.format(metro.PROFILE_PATH, path)

        profile = profiles.load(actual_path)

        self.last_used_profile = [path, actual_path, profile]

        use_geometry = True

        if profile['platform'] != sys.platform:
            use_geometry = False

        if profile['geometry_hash'] != self._getGeometryHash():
            use_geometry = False

        # Create a list combining all devices and custom channels to
        # properly resolve the dependencies between them.

        p_devices = profile['devices']
        p_channels = profile['channels']

        if not use_geometry:
            for state in p_devices.values():
                state['geometry'] = None

        names = []
        device_classes = {}

        for key, value in p_devices.items():
            names.append('d' + key)

            try:
                device_classes[value['entry_point']] = \
                    metro.loadDevice(value['entry_point'])
            except KeyError:
                if 'path' in value or 'module' in value:
                    return self.showError(
                        'An error occured on loading the profile:',
                        'This profile was created using an older, '
                        'experimental version of EXtra-metro and is not '
                        'compatible with the current, stable format. Please '
                        'use the module EXtra-metro/compat to continue using '
                        'it, see details for more information',
                        'You may switch your EXtra-metro version by typing:'
                        '\nmodule unload EXtra-metro/<version>'
                        '\nmodule load EXtra-metro/compat'
                        '\n\nTo see which version is currenty loaded, type:'
                        '\nmodule list'
                    )

        for key in p_channels.keys():
            names.append('c' + key)

        previous_count = len(names)

        while True:
            for name in names:
                if name[0] == 'd':
                    state = p_devices[name[1:]]
                    ep = state['entry_point']

                    if self._loadDevice(ep, device_classes[ep], name[1:],
                                        state):
                        names.remove(name)
                else:
                    if self._loadChannel(name[1:], p_channels[name[1:]]):
                        names.remove(name)

            new_count = len(names)

            if new_count == 0:
                break
            elif new_count == previous_count:
                self.showError(
                    'An error occured on loading the profile:',
                    'One or more devices or custom channels could not be '
                    'restored due to unsatisfiable dependencies.\nThis '
                    'usually occurs if such a depender remains open while the '
                    'dependency has already been closed and is then saved '
                    'into a profile. One example for this can be a display '
                    'device to a channel belonging to a closed device.'
                )
                break

            previous_count = new_count

        # compatibility for pre-7c4d5218
        if 'device_groups' not in profile:
            profile['device_groups'] = {}

        for state in profile['device_groups']:
            dev_grp = getattr(devices, state['class'])(state['title'],
                                                       state['custom'])

            dev_grp.restoreGeometry_(state['geometry'])
            self.addDeviceGroup(dev_grp)

        return profile, use_geometry

    def saveProfile(self, path, device_list=None, channel_list=None,
                    use_meas_params=True, use_ctrlw_geometry=True,
                    use_devw_geometries=True):
        profile = {
            'platform': sys.platform,
            'geometry_hash': self._getGeometryHash(),
            'control_window': {
                'geometry': (self.main_window.dumpGeometry()
                             if use_ctrlw_geometry else None),
                'meas_params': (self.main_window.serializeMeasParams()
                                if use_meas_params else None),
            },
            'devices': {},
            'device_groups': [],
            'channels': {},
        }

        if device_list is None:
            device_list = [d.getDeviceName() for d in metro.getAllDevices()]

        for name in device_list:
            device = metro.getDevice(name)

            if device._parent is not None:
                continue

            profile['devices'][name] = {}
            device._serialize(profile['devices'][name])

        if not use_devw_geometries:
            for name, state in profile['devices'].items():
                del state['geometry']

        for dev_grp in self.device_groups:
            profile['device_groups'].append({
                'class': dev_grp.__class__.__name__,
                'title': dev_grp.windowTitle()[:-8],
                'custom': dev_grp.serialize(),
                'geometry': dev_grp.dumpGeometry()
            })

        if channel_list is None:
            channel_list = [c.name for c in metro.getAllChannels()]

        for channel_name in channel_list:
            channel = metro.getChannel(channel_name)

            if hasattr(channel, '_custom_to_normalize'):
                custom = {
                    'to_normalize': channel._custom_to_normalize,
                    'normalize_by': channel._custom_normalize_by
                }

            elif hasattr(channel, '_custom_to_integrate'):
                custom = {
                    'to_integrate': channel._custom_to_integrate,
                    'func': channel._custom_func
                }

            elif hasattr(channel, '_custom_kernel_source'):
                custom = {
                    'mode': channel.mode,
                    'kernel_source': channel._custom_kernel_source,
                    'init_enabled': channel._custom_init_enabled,
                    'init_source': channel._custom_init_source,
                    'arg_variables': channel._custom_arg_variables,
                    'arg_channels': [x.name for x in channel.input_channels]
                }

            elif hasattr(channel, '_replayed_path'):
                custom = {
                    'path': channel._replayed_path,
                }

            else:
                continue

            profile['channels'][channel_name] = {
                'freq': channel.freq,
                'hint': channel.hint,
                'transient': channel.transient
            }

            try:
                profile['channels'][channel_name].update(
                    shape=channel.shape,
                    buffering=channel.buffering
                )
            except AttributeError:
                pass

            profile['channels'][channel_name].update(custom)

        profiles.save(path, profile)

        return profile

    def setIndicator(self, key, value):
        if value is None or not value:
            try:
                del self.indicators[key]
            except KeyError:
                pass
        else:
            self.indicators[key] = value

    def addDeviceGroup(self, dev_grp: metro.DeviceGroup):
        self.device_groups.append(dev_grp)

    def removeDeviceGroup(self, dev_grp: metro.DeviceGroup):
        self.device_groups.remove(dev_grp)

    @staticmethod
    def _wrapScriptedChannelKernel(arguments, body):
        return 'def func({0}):\n    {1}'.format(
            ','.join(arguments),
            body.replace("\n", "\n    ").replace("\t", "    ")
        )

    @staticmethod
    def _linkScriptedChannelKernel(init_object, kernel_object,
                                   kernel_name='func'):
        locals_ = {}
        globals_ = globals().copy()

        if init_object is not None:
            exec(init_object, globals_, locals_)

            globals_.update(locals_)
            locals_.clear()

        exec(kernel_object, globals_, locals_)

        return locals_[kernel_name]


class CoreApplication(QtCore.QCoreApplication, AbstractApplication):
    def __init__(self, args, argv_left, **kwargs):
        self._bootstrap(args, **kwargs)

        # Properly handle CTRL+C on the console
        import signal
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        super().__init__(argv_left)
        self.setApplicationName(metro.WINDOW_TITLE)

        if args.profile:
            self._loadProfileDelayed(args.profile)

    def quit(self):
        super().quit()

    def deviceCreated(self, d):
        pass

    def deviceKilled(self, d):
        pass

    def deviceShown(self, d):
        pass

    def deviceHidden(self, d):
        pass

    def deviceOperatorsChanged(self):
        pass

    # details may be an exception, producing a stack trace
    def showError(self, title, text, details=None):
        print('!ERROR\t{0}\n\t{1}'.format(title, text))

        if details is not None and not isinstance(details, Exception):
            print('\t({0})'.format(details))

    # Helper function to directly show an exception, using str(e) as
    # text. For exceptions other than RuntimeError it will also prefix
    # the exception type
    def showException(self, title, e):
        if isinstance(e, RuntimeError):
            text = str(e)
        else:
            text = '{0}: {1}'.format(e.__class__.__name__, str(e))

        self.showError(title, text, details=e)

    def _getGeometryHash(self):
        geometry_hash = hashlib.md5()
        geometry_hash.update(b'core mode')

        return geometry_hash.hexdigest()

    def _loadDevice(self, entry_point, device_class, name, state):
        if issubclass(device_class, metro.WidgetDevice):
            raise NotImplementedError('WidgetDevice not supported in core '
                                      'mode')

        return super()._loadDevice(entry_point, device_class, name, state)

    def findChannelByDialog(self, selected_channel=None, excluded_channels=[],
                            hint=None, freq=None, type_=None, shape=None):
        raise RuntimeError('not supported in core mode')

    def displayRawChannel(self, channel):
        raise RuntimeError('not supported in core mode')

    def editCustomChannel(self, channel):
        raise RuntimeError('not supported in core mode')

    def editNormalizedChannel(self, channel=None):
        raise RuntimeError('not supported in core mode')

    def editStatisticsChannel(self, channel=None):
        raise RuntimeError('not supported in core mode')

    def editScriptedChannel(self, channel=None):
        raise RuntimeError('not supported in core mode')

    def createNewDevice(self, entry_point, name=None, args={}):
        try:
            device_class = metro.loadDevice(entry_point)
        except ImportError as e:
            self.showError('An error occured when loading the device entry '
                           'point "{}":'.format(entry_point),
                           'The device failed to import a module or package '
                           'during initialisation. This will usually be an '
                           'essential dependecy, for example to allow '
                           'hardware access. The original exception detailing '
                           'the import error can be found in the details.\n\n',
                           details=e)
            return
        except Exception as e:
            self.showException('An error occured when loading the device '
                               'entry point "{0}":'.format(entry_point), e)
            return

        # Allow the class to configure itself
        try:
            device_class.configure()
        except Exception as e:
            self.showException('An error occured on configuring the device '
                               'class "{0}":'.format(device_class), e)
            return

        if name is None:
            name = metro.getDefaultDeviceName(entry_point)

        if not issubclass(device_class, metro.TransientDevice):
            dialog = dialogs.NewDeviceDialog(name, device_class, args)
            dialog.exec_()

            if dialog.result() != QtWidgets.QDialog.Accepted:
                return

            final_name = dialog.getName()
            final_args = dialog.getArgs()
        else:
            final_name = name
            final_args = {}

        try:
            d = metro.createDevice(final_name, entry_point, args=final_args)
        except Exception as e:
            self.showException('An error occured on constructing device '
                               '"{0}":'.format(final_name), e)
            return

        return d

    def createDisplayDevice(self, channel, entry_point=None,
                            show_dialog=False, args={}):
        raise RuntimeError('not supported in core mode')

    def screenshot(self, base_path, devices_list=None):
        raise RuntimeError('not supported in core mode')


class GuiApplication(QtWidgets.QApplication, AbstractApplication):
    def __init__(self, args, argv_left, **kwargs):
        self._bootstrap(args, **kwargs)

        # Now actually construct the QApplication instance
        super().__init__(argv_left)

        # Create and show the splash screen during loading
        logo_source = resources.files(__name__).joinpath('logo.png')
        with resources.as_file(logo_source) as logo_path:
            splash = QtWidgets.QSplashScreen(QtGui.QPixmap(str(logo_path)))
            splash.show()

        # Ensure that the splash screen gets painted immediately, since the
        # event loop is not yet running
        self.processEvents()

        self.setApplicationName(metro.WINDOW_TITLE)
        with resources.as_file(logo_source) as logo_path:
            self.setWindowIcon(QtGui.QIcon(str(logo_path)))

        self.dialogs = []

        globals().update({
            'controller': controller,
            'dialogs': dialogs,
            'display_devices': display_devices
        })

        self.main_window = controller.MainWindow()

        if not metro.kiosk_mode:
            self.main_window.show()

            # Close the splash screen if the main window is visible by now
            splash.finish(self.main_window)
        else:
            splash.close()

            if not args.profile:
                self.startKioskDefault()

        if args.profile:
            self._loadProfileDelayed(args.profile)

    def quit(self):
        self.dialogs.clear()

        super().quit()

    def deviceCreated(self, d):
        self.main_window.deviceCreated(d)

    def deviceKilled(self, d):
        self.main_window.deviceKilled(d)

    def deviceShown(self, d):
        self.main_window.deviceShown(d)

    def deviceHidden(self, d):
        self.main_window.deviceHidden(d)

    def deviceOperatorsChanged(self):
        self.main_window.deviceOperatorsChanged()

    def startKioskDefault(self):
        raise RuntimeError('profile is required in kiosk mode')

    # details may be an exception, producing a stack trace
    def showError(self, title, text, details=None):
        msgBox = QtWidgets.QMessageBox()

        msgBox.setWindowTitle(f'Error - {metro.WINDOW_TITLE}')
        msgBox.setText(title)
        msgBox.setIcon(QtWidgets.QMessageBox.Critical)

        msgBox.setInformativeText(text)

        if details is not None:
            if isinstance(details, Exception):
                details = ''.join(traceback.format_exception(
                    type(details), details, details.__traceback__
                ))

            msgBox.setDetailedText(details)

        # Dirty hack from qt-project.org to increase the MessageBox
        # width by adding a spacer to its QGridLayout
        spacer = QtWidgets.QSpacerItem(500, 0,
                                       QtWidgets.QSizePolicy.Minimum,
                                       QtWidgets.QSizePolicy.Expanding)

        layout = msgBox.layout()
        layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())

        msgBox.exec_()

    # Helper function to directly show an exception, using str(e) as
    # text. For exceptions other than RuntimeError it will also prefix
    # the exception type
    def showException(self, title, e):
        if isinstance(e, RuntimeError):
            text = str(e)
        else:
            text = '{0}: {1}'.format(e.__class__.__name__, str(e))

        self.showError(title, text, details=e)

    def _getGeometryHash(self):
        desktop_widget = self.desktop()
        geometry_hash = hashlib.md5()

        for i in range(desktop_widget.screenCount()):
            screen_geometry = desktop_widget.screenGeometry(i)

            geometry_hash.update(str(screen_geometry.top()).encode('ascii'))
            geometry_hash.update(str(screen_geometry.left()).encode('ascii'))
            geometry_hash.update(str(screen_geometry.x()).encode('ascii'))
            geometry_hash.update(str(screen_geometry.y()).encode('ascii'))

        return geometry_hash.hexdigest()

    def loadProfile(self, path):
        try:
            profile, use_geometry = super().loadProfile(path)
        except TypeError:
            return

        if profile['control_window']['geometry'] is not None and use_geometry:
            self.main_window.restoreGeometry(
                profile['control_window']['geometry']
            )

        pcw = profile['control_window']

        # Convert older profile format
        if 'quick_meas_params' in pcw:
            # Special case for compatibility with older profiles
            pcw['meas_params'] = pcw['quick_meas_params']
            pcw['meas_params']['full'] = None

        # Do this last since it may depend on devices
        if pcw['meas_params'] is not None:
            self.main_window.restoreMeasParams(pcw['meas_params'])

    def _createDialog(self, diag):
        diag.accepted.connect(QtCore.pyqtSlot()(
            lambda: metro.app.dialogs.remove(diag)
        ))
        self.dialogs.append(diag)

        return diag

    def findChannelByDialog(self, selected_channel=None, excluded_channels=[],
                            hint=None, freq=None, type_=None, shape=None):
        diag = self._createDialog(dialogs.SelectChannelDialog(
            selected_channel, excluded_channels, hint, freq, type_, shape
        ))

        if diag.exec_() == QtWidgets.QDialog.Rejected:
            return None

        return metro.getChannel(diag.getSelectedChannel())

    def displayRawChannel(self, channel):
        diag = self._createDialog(dialogs.DisplayChannelDialog(channel))
        diag.show()

    def editCustomChannel(self, channel):
        if hasattr(channel, '_custom_to_normalize'):
            self.editNormalizedChannel(channel)
        elif hasattr(channel, '_custom_to_integrate'):
            self.editStatisticsChannel(channel)
        elif hasattr(channel, '_custom_kernel_source'):
            self.editScriptedChannel(channel)
        else:
            metro.app.showError('A conflicting channel parameter was '
                                'encountered:', 'Could not find any custom '
                                'properties on this channel.')

    def editNormalizedChannel(self, channel=None):
        diag = self._createDialog(dialogs.EditNormalizedChannelDialog(channel))
        diag.show()

    def editStatisticsChannel(self, channel=None):
        diag = self._createDialog(dialogs.EditStatisticsChannelDialog(channel))
        diag.show()

    def editScriptedChannel(self, channel=None):
        diag = self._createDialog(dialogs.EditScriptedChannelDialog(channel))
        diag.show()

    def createNewDevice(self, entry_point, name=None, args={}):
        try:
            device_class = metro.loadDevice(entry_point)
        except ImportError as e:
            self.showError('An error occured when loading the device entry '
                           'point "{}":'.format(entry_point),
                           'The device failed to import a module or package '
                           'during initialisation. This will usually be an '
                           'essential dependecy, for example to allow '
                           'hardware access. The original exception '
                           'detailing the import error can be found in the '
                           'details.', details=e)
            return
        except Exception as e:
            self.showException('An error occured when loading the device '
                               'entry point "{0}":'.format(entry_point), e)
            return

        # Allow the class to configure itself
        try:
            device_class.configure()
        except Exception as e:
            self.showException('An error occured on configuring the device '
                               'class "{0}":'.format(device_class), e)
            return

        if name is None:
            name = metro.getDefaultDeviceName(entry_point)

        if not issubclass(device_class, metro.TransientDevice):
            dialog = dialogs.NewDeviceDialog(name, device_class, args)
            dialog.exec_()

            if dialog.result() != QtWidgets.QDialog.Accepted:
                return

            final_name = dialog.getName()
            final_args = dialog.getArgs()
        else:
            final_name = name
            final_args = {}

        try:
            d = metro.createDevice(entry_point, final_name, args=final_args)
        except Exception as e:
            self.showException('An error occured on constructing device '
                               '"{0}":'.format(final_name), e)
            return

        return d

    def createDisplayDevice(self, channel, entry_point=None, show_dialog=False,
                            args={}):
        channel_name = channel.name

        if entry_point is None:
            try:
                entry_point = channel.display_arguments['__default__']
            except KeyError:
                entry_point = display_devices.getDefault(channel)

            if entry_point is None:
                self.showError(
                    'An error occured on creating a display device:',
                    'No default device entry point found to display channel '
                    '"{0}".\n\nThis may happen because this channel does not '
                    'have an obvious presentation based on its properties '
                    'such as in the case of raw detector channels.\nIf you '
                    'know which display device to use, you can open it '
                    'manually or use "Display by" in its context menu. If '
                    'not, you can use "Display raw" to get generic '
                    'information about its properties and content if '
                    'applicable.'.format(channel_name)
                )
                return

        device_class = metro.loadDevice(entry_point)

        try:
            if not device_class.isChannelSupported(channel):
                raise ValueError('channel not supported')
        except ValueError as e:
            self.showError('An error occured on constructing a display '
                           'device:', str(e))
            return None

        device_name = metro.getAvailableDeviceName('{0}[{1}]'.format(
            channel_name, entry_point[entry_point.rfind('.')+1:])
        )

        final_args = {'channel': channel}

        for key, value in channel.display_arguments.items():
            if key.startswith(entry_point):
                final_args[key[len(entry_point)+1:]] = value

        final_args.update(args)

        if show_dialog:
            display_device = self.createNewDevice(entry_point, device_name,
                                                  final_args)
        else:
            display_device = metro.createDevice(entry_point, device_name,
                                                args=final_args)

        return display_device

    def screenshot(self, base_path, devices_list=None):
        IMAGE_FORMAT = QtGui.QImage.Format_RGB32
        IMAGE_BACKGROUND = QtGui.QColor.fromRgb(35, 35, 35)

        # Screenshots are divided into an upper and a lower region. The
        # upper region contains the controller window as well as the
        # regular devices, that is all non-display devices that have
        # been created manually by the user or are child devices
        # thereof. The controller is always in the upper left corner
        # and the devices are laid out to the right in columns. The
        # height of this region is determined by the tallest singular
        # widget, usually the controller. The smaller devices are
        # sorted alphabetically, but may be reordered to use the space
        # in each column as efficient as possible. This ordering will
        # stay constant in between screenshots of identical device
        # configurations by using first an alphabetical order and then
        # the mentioned reorderung for efficiency.
        # The display devices in the lower region are grouped by the
        # device their displayed channels are created by as well as
        # sorted alphabetically. The height of this region is up to
        # 500px but may be increased by a taller single device.

        # For the moment we rely on proper naming for the distinction
        # between regular devices and display devices as well as the
        # grouping of display devices.
        # It is probably better (especially for manual display devices)
        # to keep track of this state in the application object.

        if devices_list is None:
            devices_list = metro.getAllDevices()

        controller_pixmap = self.main_window.grab()
        regular_device_pixmaps = []
        display_device_pixmaps = []
        displayed_device_names = set()

        for d in devices_list:
            if not isinstance(d, QtWidgets.QWidget):
                continue

            pixmap = d.grab()
            pixmap._name = d._name

            cur_size = pixmap.size()
            pixmap._height = cur_size.height() + 20
            pixmap._width = cur_size.width() + 15

            if '[' in d._name:
                display_device_pixmaps.append(pixmap)
                displayed_device_names.add(d._name[:d._name.find('#')])
            else:
                regular_device_pixmaps.append(pixmap)

        # Sort the devices by name alphabetically
        regular_device_pixmaps.sort(key=lambda pixmap: pixmap._name)
        display_device_pixmaps.sort(key=lambda pixmap: pixmap._name)
        displayed_device_names = sorted(displayed_device_names)

        # First we have to figure out the minimum height required
        upper_height = controller_pixmap.size().height()
        for pixmap in regular_device_pixmaps:
            upper_height = max(upper_height, pixmap._height)

        # And now we check how we can arrange them horizontally
        pixmap_queue = list(reversed(regular_device_pixmaps))

        upper_width = controller_pixmap.size().width()
        col_width = 0

        pixmap = None
        cur_x = upper_width
        cur_y = 0
        cur_idx = -1
        while pixmap_queue:
            pixmap = pixmap_queue[cur_idx]

            if cur_y + pixmap._height > upper_height:
                if -cur_idx == len(pixmap_queue):
                    cur_x += col_width
                    cur_y = 0

                    upper_width += col_width
                    cur_idx = -1
                else:
                    cur_idx -= 1

                # Technically this could result in an infinite loop,
                # but since we calculated the upper_height based on the
                # individual heights of each element, there has to be
                # enough space for each.
                continue

            col_width = max(col_width, pixmap._width)

            pixmap._x = cur_x
            pixmap._y = cur_y

            cur_y += pixmap._height

            pixmap_queue.pop(cur_idx)
            cur_idx = -1

        # Add the last column as well!
        upper_width += col_width

        upper_image = QtGui.QImage(upper_width, upper_height, IMAGE_FORMAT)
        upper_image.fill(IMAGE_BACKGROUND)
        painter = QtGui.QPainter(upper_image)
        painter.setPen(QtCore.Qt.white)

        painter.drawPixmap(0, 0, controller_pixmap)
        for pixmap in regular_device_pixmaps:
            painter.drawText(pixmap._x+18, pixmap._y+15, pixmap._name)
            painter.drawPixmap(pixmap._x+15, pixmap._y+18, pixmap)

        painter.end()

        # For the lower part, we create individual images for each
        # device whose channels have display devices attached.
        displayed_device_images = []
        lower_height = 500  # Enough for 2x waveform

        for device_name in displayed_device_names:
            cur_height = 0
            cur_width = 0

            cur_pixmaps = []

            channel_start = device_name + '#'

            for pixmap in display_device_pixmaps:
                if not pixmap._name.startswith(channel_start):
                    continue

                cur_width = max(cur_width, pixmap._width)
                cur_height += pixmap._height
                cur_pixmaps.append(pixmap)

            lower_height = max(lower_height, cur_height)

            cur_image = QtGui.QImage(cur_width, cur_height, IMAGE_FORMAT)
            cur_image.fill(IMAGE_BACKGROUND)

            cur_image._width = cur_width
            cur_image._height = cur_height

            painter = QtGui.QPainter(cur_image)
            painter.setPen(QtCore.Qt.white)

            cur_y = 0
            for pixmap in cur_pixmaps:
                painter.drawText(3, cur_y+15, pixmap._name)
                painter.drawPixmap(0, cur_y+18, pixmap)
                cur_y += pixmap._height

            displayed_device_images.append(cur_image)

            painter.end()

        # Make a copy of the our reversed list
        images_queue = list(reversed(displayed_device_images))

        lower_width = 0
        col_width = 0
        actual_lower_height = 0

        image = None
        cur_x = 0
        cur_y = 0
        cur_idx = -1
        while images_queue:
            image = images_queue[cur_idx]

            if cur_y + image._height > lower_height:
                if -cur_idx == len(images_queue):
                    # Start a new column
                    # But first save the previous column's height
                    actual_lower_height = max(actual_lower_height, cur_y)

                    cur_x += col_width
                    cur_y = 0

                    lower_width += col_width
                    cur_idx = -1
                else:
                    cur_idx -= 1

                # See remark for upper region concerning infinite loops
                continue

            col_width = max(col_width, image._width)

            image._x = cur_x
            image._y = cur_y

            cur_y += image._height

            images_queue.pop(cur_idx)
            cur_idx = -1

        # Add the last column as well, but substract the outer margin
        lower_width += col_width - 15
        actual_lower_height = max(actual_lower_height, cur_y)

        # Check if the actual height of the lower region is less than
        # the allowed 500px.
        lower_height = min(lower_height, actual_lower_height)

        lower_image = QtGui.QImage(lower_width, lower_height, IMAGE_FORMAT)
        lower_image.fill(IMAGE_BACKGROUND)

        if displayed_device_images:
            # We might have no display devices and hence create a
            # QPainter on a zero-size image.
            painter = QtGui.QPainter(lower_image)
            for image in displayed_device_images:
                painter.drawImage(image._x, image._y, image)
            painter.end()

        total_image = QtGui.QImage(max(upper_width, lower_width),
                                   upper_height + lower_height + 50,
                                   IMAGE_FORMAT)
        total_image.fill(IMAGE_BACKGROUND)

        painter = QtGui.QPainter(total_image)
        painter.drawImage(0, 0, upper_image)
        painter.drawImage(0, upper_height, lower_image)

        font = painter.font()
        font.setStretch(QtGui.QFont.SemiCondensed)
        painter.setFont(font)
        painter.setPen(QtCore.Qt.white)

        footer_y = upper_height + lower_height
        painter.drawText(3, footer_y + 15, os.path.basename(base_path))
        painter.drawText(3, footer_y + 30, str(metro.version))
        painter.drawText(3, footer_y + 45,
                         'Python {0[0]}.{0[1]}.{0[2]}-{0[3]}{0[4]} '
                         'on {1}'.format(sys.version_info, sys.platform))

        painter.end()

        total_image.save(base_path + '.jpg', 'jpg', 100)

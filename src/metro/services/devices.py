
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# This module implements all core functionality for a Metro device. Every
# actual device should inherit from one of the complete implementations
# provided here, CoreDevice (no UI) and WidgetDevice (Qt Widgets).

# It also possible to inherit from GenericDevice directly, but several
# abstract methods have to implemented in this case.


from collections import namedtuple
from functools import partial
from pkg_resources import iter_entry_points
from typing import Optional

import metro
from metro.services import channels

QtCore = metro.QtCore
QtWidgets = metro.QtWidgets
QtUic = metro.QtUic


_device_entry_points = {ep.name: ep for ep
                        in iter_entry_points('metro.device')}

_devices = {}
_morgue = []

MeasureOperators = namedtuple('MeasureOperators',
                              ['point', 'scan', 'trigger', 'limit', 'status'])
_operators = MeasureOperators({}, {}, {}, {}, {})

_unconfirmed_kills_counter = 0


def load(ep_name):
    """
    Import the given device entry point and return the device class.

    Args:
        ep_name (str): Entry point name

    Returns:
        Device class object.
    """

    try:
        ep = _device_entry_points[ep_name]
        cls = ep.load()
    except KeyError:
        raise ValueError('unknown device entry point') from None

    return cls


def create(entry_point, name, parent=None, args=None, state=None):
    """
    Create a new device.

    Creates a new device with given name and device class (or path to
    module file).

    Args:
        name: A string with the name of the new device.
        entry_point: Entry point name
        parent: Optional parent device object.
        args: Optional dict containing arguments to overwrite any of the
            default values
        state: Optional dict which state informations supplied to the
            newly created device.

    Returns:
        The newly created device object.

    Raises:
        ValueError: Name already in use.
        ValueError: Neither device class nor module path given.
        Any exception raised by import
    """

    if parent is not None:
        name = '{0}!{1}'.format(parent._name, name)

    if name in _devices:
        raise ValueError('device with name "{0}" exists already'.format(name))

    device_class = load(entry_point)

    # Check if the device defines any arguments and replace the default
    # values with custom ones given in args, replace lists/tuples by
    # their first element as well as remove abstract argument types.
    try:
        default_args = device_class.arguments
    except AttributeError:
        default_args = {}

    final_args = {}

    for arg_name, default_value in default_args.items():
        try:
            final_value = args[arg_name]
        except (KeyError, TypeError):
            if (isinstance(default_value, list) or
                    isinstance(default_value, tuple)):
                final_value = default_value[0]
            elif isinstance(default_value, metro.AbstractArgument):
                final_value = default_value.dialog_bypass()
            else:
                final_value = default_value

        final_args[arg_name] = final_value

    # Now apply any new value if given
    if args is not None:
        for k, v in args.items():
            final_args[k] = v

    if state is None:
        state = {'visible': True}

    dev = device_class()

    if not dev._prepare(name, parent, final_args, state, entry_point):
        raise RuntimeError('device preparation failed')

    if parent is not None:
        parent._child_count += 1

    return dev


def killAll():
    """
    Kill all current devices.
    """

    all_parent_devices = []

    for name in _devices:
        if _devices[name]._parent is None:
            all_parent_devices.append(_devices[name])

    for device in all_parent_devices:
        device.kill()

    _devices.clear()


def checkForLeaks():
    for title in _morgue:
        print('WARNING: leak detected of device',
              title[:-len(metro.WINDOW_TITLE)-3])


def get(name):
    """
    Get a device by name.

    Args:
        name: A string with the device name requested.

    Returns:
        The device object.

    Raises:
        KeyError: Device with given name not found.
    """

    return _devices[name]


def getAll():
    """
    Get all loaded devices.

    Returns:
        A list with all device objects.
    """

    return _devices.values()


def getAvailableName(name):
    """
    Get the shortest possible name for a device.

    Based on the supplied name, find the shortest valid name for a
    device. In case the name itself is already taken, attach the lowest
    possible integer with an underscore.

    Args:
        name: String to use as requested name.

    Returns:
        Shortest possible valid device name based on supplied string.
    """

    if name not in _devices:
        return name

    i = 1

    while '{0}_{1}'.format(name, i) in _devices:
        i = i + 1

    return '{0}_{1}'.format(name, i)


def getDefaultName(entry_point):
    return getAvailableName(entry_point[entry_point.rfind('.')+1:])


def findDeviceForChannel(channel_name):
    try:
        device_name, channel_tag = channel_name.rsplit('#', maxsplit=1)
        device = get(device_name)
    except ValueError:
        # May be thrown by rsplit
        return None
    except KeyError:
        # May be thrown by get
        return None
    else:
        return device


def getOperator(type_, name):
    if isinstance(type_, str):
        return getattr(_operators, type_)[name]
    elif isinstance(type_, int):
        return _operators[type_][name]


def getAllOperators(type_):
    if isinstance(type_, str):
        return getattr(_operators, type_)
    elif isinstance(type_, int):
        return _operators[type_]


@QtCore.pyqtSlot(QtCore.QObject)
def _on_device_destroyed(obj):
    try:
        name = obj.windowTitle()
    except AttributeError:
        pass
    else:
        _morgue.remove(name)


class OperatorThread(QtCore.QThread):
    """
    Customized thread to run operators.

    The operator pattern is used throughout Metro to allow a self
    contained object controlling an IO-intensive workflow to run in a
    separate context such as a thread or process. Typically these
    operators contain a "prepare" and a "finalize" method that are
    connected to the started and finished signals of a QThread
    respectively.
    """

    def __init__(self, parent, operator):
        super().__init__(parent)

        operator.moveToThread(self)
        self.started.connect(operator.prepare)
        self.finished.connect(operator.finalize)


class GenericDevice(metro.measure.Node):
    """
    Base class for all devices.

    This class contains all the fundamental logic and functionality
    required by the framework for a device. A device should not inherit
    directly from this class but rather one of the more concrete device
    base classes that implement a presentation scheme (for example
    CoreDevice or WidgetDevice). The abstract methods in this class are
    needed to implement the concept of device visibility:

    setVisible(flag): set the visibility to flag
    isVisible: check the visibility
    show: always switch the visibilty to shown, equivalent to
        setVisible(True)
    hide: always switch the visibilty to hidden, equivalent to
        setVisible(False)
    maximize: bring the window to the foreground if possible

    These are not defined as stub methods, so they can be overwritten by
    multiple inheritance. Note that these methods contain the public
    frontend interface, not the public user interface.

    There are four stub methods in this class that a concrete device
    implementor should overwrite:

    prepare: called whenever a new device is created from this class.
    finalize: called when a device is killed.
    serialize: called when a device is asked to save its state.

    A device should make no assumptions about its state when restore()
    is called! It can either be called after a prepare or at any other
    arbitrary point in time.

    All these methods are optional and have empty stubs. There is an
    additional method which is implemented as a class method, which is
    not guaranteed to be called depending upon the way of device
    creation.

    configure: may be called before device creation to initialize the
        default arguments.

    Note that due to possibly also extending QObject, this class does
    NOT have an __init__ method, and no child class should use one! This
    prevents any problems related to different arguments of __init__
    methods of the respective superclasses (QObject vs AbstractDevice).

    If you are extending this class on the framework level
    (like GraphicalDevice), also overwrite (and in turn call on the
    superclass) the _prepare() method.
    """

    arguments = {}
    descriptions = {}

    def _prepare(self, name, parent, args, state, entry_point):
        """
        Prepare this device object.

        Note that this method will call the prepare() method on the
        device implementation. If you are overwriting this method on the
        framework level, you will probably want to initialize your own
        state before calling it in this superclass.

        Args:
            name: The name for this new device.
            parent: Parent device object or None.
            args: A dict with startup arguments.
            state: A dict with state information.
            entry_point: Entry point used to load this device.
        """

        self._name = name
        self._parent = parent
        self._args = args
        self._state = state
        self._entry_point = entry_point

        self._child_count = 0

        self._measuring_slots = []
        self._operators = []

        _devices[name] = self

        metro.app.deviceCreated(self)

        try:
            custom_state = state['custom']
        except KeyError:
            custom_state = None

        try:
            prepare_result = self.prepare(args, custom_state)
        except Exception as e:
            prepare_result = e

        if prepare_result is not True and prepare_result is not None:
            metro.app.deviceKilled(self)
            self._measuring_slots.clear()
            del _devices[self._name]

            if prepare_result is False:
                return False
            else:
                raise prepare_result

        if isinstance(self, QtCore.QObject):
            self.destroyed.connect(_on_device_destroyed)

        # for correct/full initialization set as visible first
        self.setVisible(True)
        if 'visible' in state:
            self.setVisible(state['visible'])

        return True

    def _serialize(self, state):
        """
        Serialize this device's state.

        Serializes any private state information of this object and in
        turn calls the serialize() method on the device implementation.

        Args:
            state: A dict the state should be saved into.
        """

        state['entry_point'] = self._entry_point
        state['arguments'] = self._args.copy()

        try:
            raw_arguments = self.__class__.arguments
        except AttributeError:
            pass
        else:
            for key, value in raw_arguments.items():
                if not isinstance(value, metro.AbstractArgument):
                    continue

                try:
                    serialized_value = value.serialize(self._args[key])
                except Exception:
                    state['arguments'][key] = None
                else:
                    state['arguments'][key] = serialized_value

        state['visible'] = self.isVisible()

        custom_state = self.serialize()

        if custom_state is not None:
            state['custom'] = custom_state

    def __str__(self):
        return self._name

    def kill(self):
        """
        Kill this device.

        Causes this device and all its child devices to be killed. It
        will first call this method on all its child devices, then call
        the finalize() method on the device implementation and finally
        delete it from the global device dict.
        """

        if self._child_count > 0:
            children = []

            for name in _devices:
                if _devices[name]._parent == self:
                    children.append(_devices[name])

            if self._child_count != len(children):
                print('WARNING: Killing device with child_count = {0}, but '
                      'found {1}').format(self._child_count, len(children))

            for child in children:
                child.kill()

            children.clear()

        if self._parent is not None:
            self._parent._child_count -= 1
            self._parent = None  # Prevents memory leak!

        # Call abstract finalize method
        self.finalize()

        if len(self._operators) > 0:
            # Make a copy to allow modification of self._operators
            ops = self._operators[:]

            for op in ops:
                self.measure_removeOperator(*op)
                print('WARNING: Removed operator automatically:', op[1])

        try:
            if self.measurement_control_override:
                self.measure_releaseControl()
                print('WARNING: Released measurement control automatically')
        except AttributeError:
            pass

        metro.app.deviceKilled(self)

        self._measuring_slots.clear()

        del _devices[self._name]

        try:
            name = self.windowTitle()
        except AttributeError:
            pass
        else:
            _morgue.append(name)

    def getDeviceName(self):
        """
        Get the name of this device.

        Returns:
            A string containing the device name.
        """
        return self._name

    @staticmethod
    def getByName(name):
        return get(name)

    @classmethod
    def isSubDevice(cls, other_cls):
        if isinstance(other_cls, str):
            other_cls = load(other_cls)

        return issubclass(cls, other_cls)

    def isChildDevice(self):
        """
        Query whether this device is a root device or child device
        created by another root device.

        Returns:
            A boolean indicating whether this device is a child device.
        """

        return self._parent is not None

    def createChildDevice(self, entry_point, name, args=None, state=None):
        """
        Create a new child device.

        This method is equivalent to create(entry_point, name,
                                            parent=self, ...).

        Args:
            entry_point: Entry point for device.
            name: A string with the name for this new child device. This
                name will only be attached to the parent's device name.
            args: Optional arguments to overwrite any of the default
                values.
            state: Optional dict which state informations supplied to
                the newly created device.

        Returns:
            The newly created device object.

        Raises:
            Same as create(entry_point, name, parent=self, ...)
        """

        return create(entry_point, name, parent=self,
                      args=args, state=state)

    def measure_setIndicator(self, key, value):
        metro.app.setIndicator('d.{0}.{1}'.format(self._name, key), value)

    def measure_getCurrent(self) -> Optional[metro.Measurement]:
        return metro.app.current_meas

    def measure_setCurrent(self, meas: Optional[metro.Measurement]) -> None:
        """
        Set the global measurement object.

        When a device overrides the measurement control, it needs to
        report the created measurement object while it is active.

        IMPORTANT: The measurement object is assumed to be registered
        in the prepared event and STILL registered in the finalized
        event. An overriding device should therefore not call this
        method in either of these event handlers. The call to register
        the object should occur between creating the measurement object
        and running it. The best opportunity to unregister it after the
        measurement finished is when the StatusOperator switches back
        to STANDBY. The controller window will follow this principle
        when used as a StatusOperator.
        """

        if not self.measurement_control_override:
            raise RuntimeError('device has not overriden measurement control')

        metro.app.current_meas = meas

    def measure_getStorageBase(self) -> Optional[str]:
        if metro.app.current_meas is not None:
            return metro.app.current_meas.storage_base

        return None

    def measure_connect(self, started=None, stopped=None, prepared=None,
                        finalized=None):
        """
        Connect (actually register) measuring slots for this device.

        A device can register as many slots for each of the available
        signals as required and in any combination of calls. The signals
        are, in the order they are emitted:

        prepared: when the controller finished preparing the measuring
            process and is about to initiate the first step
        started: whenever a step starts
        stopped: whenever a step stops
        finalized: when the complete measuring process is finished or was
            aborted by the user. No more started signals will be emitted
            at this point.

        All arguments are optional and can be None (their default value)
        on any call, the following calls are therefore equivalent:

        self.measure_connect(started=self.myStartedSlot)
        self.measure_connect(prepared=self.myPreparedSlot)

        and

        self.measure_connect(started=self.myStartedSlot,
                             prepared=self.myPreparedSlot)

        Args:
            started: Slot to be connected to the started signal.
            stopped:  Slot to be connected to the stopped signal.
            prepared: Slot to be connected to the prepared signal.
            finalized: Slot to be connected to the finalized signal.
        """

        self._measuring_slots.append((prepared, started, stopped, finalized))

    def measure_addOperator(self, type_, tag, op):
        """
        Add a measurement operator.
        """

        name = '{0} ({1})'.format(tag, self._name)
        op_dict = getattr(_operators, type_)

        if name in op_dict:
            raise ValueError('operator tag already in use for this device.')

        op_dict[name] = op
        self._operators.append((type_, tag))

        metro.app.deviceOperatorsChanged()

    def measure_addTaggedOperator(self, type_, tag, op):
        """
        Add a measurement operator with callback tags.

        This method is provided when a single operator wants to provide
        several tags. Instead of having to construct an object for each
        tag by himself, this method will instead construct a proxy
        object and adds the tag string to its callback methods as an
        arguments. The calling signature hence changes to (e.g. for the
        ScanOperator):

            prepareScan(self, tag)
            finalizeScan(self, tag)

        Args:
            type_:
            tag:
            op:
        """
        if type_ == 'point':
            proxy_op = metro.PointOperator()
        elif type_ == 'scan':
            proxy_op = metro.ScanOperator()
        elif type_ == 'trigger':
            proxy_op = metro.TriggerOperator()
        elif type_ == 'limit':
            proxy_op = metro.LimitOperator()
        elif type_ == 'status':
            proxy_op = metro.StatusOperator
        else:
            raise ValueError('unknown operator type specified')

        prepare_method = 'prepare{0}'.format(type_.title())
        finalize_method = 'finalize{0}'.format(type_.title())

        if type_ == 'point':
            prepare_method += 's'
            finalize_method += 's'

        setattr(proxy_op, prepare_method,
                partial(getattr(op, prepare_method), tag))
        setattr(proxy_op, finalize_method,
                partial(getattr(op, finalize_method), tag))

        self.measure_addOperator(type_, tag, proxy_op)

    def measure_removeOperator(self, type_, tag):
        name = '{0} ({1})'.format(tag, self._name)
        op_dict = getattr(_operators, type_)

        if name not in op_dict:
            raise ValueError('no operator with this tag in use for this '
                             'device')

        self._operators.remove((type_, tag))
        del op_dict[name]

        metro.app.deviceOperatorsChanged()

    def measure_overrideControl(self) -> None:
        # Do not forget to register the measurement object via
        # measure_setCurrent and remove it upon finalization

        metro.app.main_window.overrideMeasurementControl(self._name)

        self.measurement_control_override = True

    def measure_releaseControl(self) -> None:
        metro.app.main_window.releaseMeasurementControl()

        self.measurement_control_override = False

    def measure_create(self, point_op, scan_op, trigger_op, limit_op,
                       status_op=None, scan_count=1, storage_base=None):
        cur_channels = [chan for chan
                        in channels.sortByDependency(channels.getAll())
                        if not chan.isStatic()]

        if status_op is None:
            status_op = metro.app.main_window

        return metro.Measurement(
            list(getAll()), cur_channels, point_op, scan_op, trigger_op,
            limit_op, status_op, scan_count, storage_base
        )

    def connectToMeasurement(self, prepared, started, stopped, finalized):
        for slots in self._measuring_slots:
            if slots[0] is not None:
                prepared.connect(slots[0])

            if slots[1] is not None:
                started.connect(slots[1])

            if slots[2] is not None:
                stopped.connect(slots[2])

            if slots[3] is not None:
                finalized.connect(slots[3])

    def showError(self, text, details=None):
        """
        Display an error dialog.

        A wrapper for devices to display an error by the frontend
        controller.

        Args:
            text: A string describing the error
            details: An optional object that provides more details about
                the error. May be a string OR an Exception object. In
                the latter case, the complete stack trace will be used
                in the details.
        """

        metro.app.showError(
            'An error has occured in device <i>{0}</i>:'.format(self._name),
            text, details
        )

    def showException(self, e):
        """
        Display an error dialog for an exception.

        This call is simply a shortcut for using the exception message
        as the error text and the exception itself as details.

        This method is equivalent to
        GraphicalDevice.showError(str(e), e).

        Args:
            e: The exception to be displayed.
        """

        self.showError(str(e), e)

    # def show(self)
    # def hide(self)
    # def setVisible(self, flag)
    # def isVisible(self)
    # def isHidden(self)
    # def maximize(self)

    @classmethod
    def configure(cls):
        """
        Configure the device implementation.

        Stub for the device implementation for when the device class
        should be configured prior to creation of the actual device
        object. It is not guaranteed that this class method will be
        called and this depends on the way of device creation. It should
        be used to intialize the default arguments to some sensible
        value which can only be determined at runtime.
        """

        pass

    def prepare(self, args, state):
        """
        Prepare the device implementation.

        Stub for the device implementation for when a new device is
        created from this class.
        """

        pass

    def finalize(self):
        """
        Finalize the device implementation.

        Stub for the device implementation for when a device created
        from this class is killed.
        """

        pass

    def serialize(self):
        """
        Serialize the device implementation's state.

        Stub for the device implementation for when the device should
        save its state.

        Returns:
            Any python object to be stored as the state for the
            implementation of this device or None.
        """

        return None


def _searchParentUi(cls):
    """
    Search a suitable UI file for a device class.

    Searches the list of parent classes for a suitable .ui file. The
    order is determined by the order of appearance in the __bases__
    property of said class object.

    Args:
        cls: Class object for the device.

    Returns:
        A string containing the UI file to load or None
    """

    for parent in cls.__bases__:
        if parent.__name__ == 'Device':
            resource_args = (
                parent.__module__,
                parent.__module__[parent.__module__.rfind('.')+1:] + '.ui'
            )

            if metro.resource_exists(*resource_args):
                return metro.resource_filename(*resource_args)
            else:
                return _searchParentUi(parent)

    return None


class DisplayDevice(GenericDevice):
    @staticmethod
    def isChannelSupported(channel):
        return True


class CoreDevice(GenericDevice, QtCore.QObject):
    def show(self):
        pass

    def hide(self):
        pass

    def setVisible(self, flag):
        pass

    def isVisible(self):
        return False

    def isHidden(self):
        return True

    def maximize(self):
        pass


class TransientDevice(CoreDevice):
    pass


class WidgetDevice(GenericDevice, QtWidgets.QWidget):
    """
    Base class for all graphical Qt devices.

    Any device which wants to show a graphical interface based on Qt
    should inherit from this class. It connects the basic device
    functionality and lifecycle management with a QWidget. It is highly
    recommended that devices to not open further windows that the one
    provided by this widget itself.

    This class will try to load a UI file and use this as the prototype
    for the QWidget. If the ui_file attribute is not set, it will search
    for a .ui file with the same name as the device module itself. If
    none is found, this search propagates along the class inheritance.
    To disable automatic this behaviour, simply set the ui_file
    attribute to None.

    The abstract methods of AbstractDevice are here implemented by
    QtWidgets.QWidget.

    Attributes:
        ui_file: Optional string containing the UI file to load or None.
    """

    def _prepare(self, name, parent, args, state, entry_point):
        """
        Prepare this device object.

        This method extends AbstractDevice by trying to load a UI file
        into this QWidget. See the general class description for more
        details.

        See AbstractDevice._prepare(name, parent, args, state,
                                    entry_point).
        """

        self._device_group = None

        ui_file = None

        # Either use the attribute or search for ui files with the same
        # name as this module

        # FIX USAGE OF ._path
        try:
            ui_file = self.ui_file
        except AttributeError:
            res_args = (self.__module__,
                        f'{self.__module__[self.__module__.rfind(".")+1:]}.ui')

            if metro.resource_exists(*res_args):
                ui_file = metro.resource_filename(*res_args)
            else:
                ui_file = _searchParentUi(self.__class__)

        # uic.loadUi requires a working __str__() for debug messages.
        self._name = name

        if ui_file is not None:
            QtUic.loadUi(ui_file, self)
            self.resize(self.sizeHint())

        self.setWindowTitle(name)

        if 'geometry' in state and state['geometry'] is not None:
            self.setGeometry(*state['geometry'])

        # Now we call _prepare() on our superclass. We delayed this first
        # so the UI is already initialized by the time we call prepare()
        # of the device implementation.
        if not super()._prepare(name, parent, args, state, entry_point):
            return False

        return True

    def _serialize(self, state):
        """
        Serialize this device's state.

        This method extends AbstractDevice by including the geometry in
        the private state information.

        See AbstractDevice._serialize(state).
        """

        geometry = self.geometry()

        state['geometry'] = (geometry.left(), geometry.top(),
                             geometry.width(), geometry.height())

        super()._serialize(state)

    def kill(self):
        """
        Kill this device.

        This method extends AbstractDevice by also sending a Qt close
        event if it has not been triggered by said event.

        See AbstractDevice.kill().
        """

        # This flag is set by closeEvent() if the unload process was
        # initiated by Qt. In this case we do not want to propagate it
        # again.
        if not hasattr(self, 'close_signaled'):
            self.kill_called = True
            self.close()

        super().kill()

        if metro.kiosk_mode:
            for widget in metro.app.allWidgets():
                if widget.isVisible():
                    return

            metro.app.quit()

    def showEvent(self, event):
        """
        Qt event handler for show events.

        Called when this QWidget receives a QShowEvent from the window
        system and forwards this to the front end controller. Ignored
        if the device is in a device group.

        Args:
            event: The QShowEvent object belonging to this event
        """

        if self._device_group is not None:
            return

        metro.app.deviceShown(self)

    def hideEvent(self, event):
        """
        Qt event handler for hide events.

        Called when this QWidget receives a QHideEvent from the window
        system and forwards this to the front end controller. Ignored
        if the device is in a device group.

        Args:
            event: The QHideEvent object belonging to this event
        """

        # In kiosk mode, this event might be triggered after the (last)
        # device has already been killed.
        if self._name not in _devices:
            return

        if self._device_group is not None:
            return

        metro.app.deviceHidden(self)

    def closeEvent(self, event):
        """
        Qt event handler for close events.

        For child devices, we only hide the window and then ignore the
        event. All other devices are killed if the kill process is not
        already in progress (and the close event was triggered in
        response to it)

        Args:
            event: The QCloseEvent object belonging to this event
        """

        if self._device_group is not None:
            self._device_group.removeDevice(self)

        # Hide first to emit the hideEvent before the device is
        # completely killed.
        self.hide()

        if self._parent is not None:
            event.ignore()
        else:
            # This flag is set if close() was called starting from
            # kill(), so in this case we do not want to set the
            # kill chain in motion ourselves again
            if not hasattr(self, 'kill_called'):
                self.close_signaled = True

                # This delayed kill fixes the weird SEGFAULTs occuring
                # randomly when closing windows.
                self.killTimer = metro.QTimer(self)
                self.killTimer.timeout.connect(self._delayed_kill)
                self.killTimer.setInterval(0)
                self.killTimer.setSingleShot(True)
                self.killTimer.start()

    @metro.QSlot()
    def _delayed_kill(self):
        self.kill()

    def maximize(self):
        """
        Bring the device interface to the foreground.
        """

        self.showNormal()
        self.activateWindow()

    def setWindowTitle(self, new_title):
        super().setWindowTitle(f'{new_title} - {metro.WINDOW_TITLE}')

    def createDialog(self, ui_name):
        dialog = QtWidgets.QDialog(self)

        ui_file = metro.resource_filename(
            self.__module__,
            f'{self.__module__[self.__module__.rfind(".")+1:]}_{ui_name}.ui'
        )

        QtUic.loadUi(ui_file, dialog)
        dialog.resize(dialog.sizeHint())

        return dialog

    def setDeviceGroup(self, grp):
        self._device_group = grp


class DeviceGroup(object):
    def __init__(self):
        if not isinstance(self, QtWidgets.QWidget):
            raise RuntimeError('DeviceGroup must be extended by a QWidget')

        self.menuAdd = QtWidgets.QMenu()
        self.menuAdd.aboutToShow.connect(self.on_menuAdd_aboutToShow)
        self.menuAdd.triggered.connect(self.on_menuAdd_triggered)

        self.buttonAdd = QtWidgets.QToolButton(self)
        self.buttonAdd.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.buttonAdd.setStyleSheet('QToolButton::menu-indicator '
                                     '{ image: url(none.jpg); }')
        self.buttonAdd.setMenu(self.menuAdd)
        self.buttonAdd.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.SP_FileDialogNewFolder
        ))

        self.show()

    def _getContainedDevices(self):
        raise NotImplementedError('_getContainedDevices')

    @metro.QSlot()
    def on_menuAdd_aboutToShow(self):
        self.menuAdd.clear()

        devs = self._getContainedDevices()

        d_list = sorted(getAll(), key=lambda x: x._name)
        for d_obj in d_list:
            if isinstance(d_obj, WidgetDevice) and d_obj not in devs:
                self.menuAdd.addAction(d_obj._name).setData(d_obj._name)

    # @metro.QSlot(QtWidgets.QAction)
    def on_menuAdd_triggered(self, action):
        dev = get(action.data())

        if dev not in self._getContainedDevices():
            self.addDevice(dev)

    def addDevice(self, d):
        pass

    def removeDevice(self, d):
        pass

    def close(self):
        pass

    def dumpGeometry(self):
        geometry = self.geometry()

        return (geometry.left(), geometry.top(),
                geometry.width(), geometry.height())

    def restoreGeometry_(self, state):
        # TODO: collides with Qt5 symbol
        self.setGeometry(QtCore.QRect(*state))

    def serialize(self):
        pass


class WindowGroupWidget(QtWidgets.QMdiArea, DeviceGroup):
    def __init__(self, title):
        super().__init__()

        self.setWindowTitle(f'{title} - {metro.WINDOW_TITLE}')

        self.devices_in_window = []

    def _getContainedDevices(self):
        return self.devices_in_window

    def addDevice(self, d):
        if not isinstance(d, QtWidgets.QWidget):
            raise TypeError('device must inherit QWidget')

        self.addSubWindow(d)
        d.show()


class TabGroupWidget(QtWidgets.QTabWidget, DeviceGroup):
    class EmptyTabWidget(QtWidgets.QWidget):
        def __init__(self, parent):
            super().__init__(parent)

            layout = QtWidgets.QHBoxLayout(self)
            self.setLayout(layout)

            layout.addItem(QtWidgets.QSpacerItem(
                1, 1, QtWidgets.QSizePolicy.MinimumExpanding,
                QtWidgets.QSizePolicy.Expanding
            ))

            self.label = QtWidgets.QLabel(
                'A tab group can contain any number of devices and each added '
                'device is then accessible by its own tab.<br><br>A device '
                'can be added by clicking the small button in the top right '
                'corner of this window.<br><br>Some devices also provide '
                'their own method of adding it to a device group, e.g. most '
                'display devices.'
            )
            self.label.setWordWrap(True)
            layout.addWidget(self.label)

            layout.addItem(QtWidgets.QSpacerItem(
                1, 1, QtWidgets.QSizePolicy.MinimumExpanding,
                QtWidgets.QSizePolicy.Expanding
            ))

    def __init__(self, title, state=None):
        super().__init__()

        self.setWindowTitle(f'{title} - {metro.WINDOW_TITLE}')

        self.tabCloseRequested.connect(self.on_tabCloseRequested)
        self.setTabsClosable(False)

        self.setCornerWidget(self.buttonAdd, QtCore.Qt.TopRightCorner)

        self.tabEmpty = TabGroupWidget.EmptyTabWidget(self)
        self.addTab(self.tabEmpty, '')

        self.devices_in_tabs = []

        if state is not None:
            for dev_name in state[0]:
                self.addDevice(get(dev_name))

            self.setCurrentIndex(state[1])

    def serialize(self):
        return [d._name for d in self.devices_in_tabs], self.currentIndex()

    def closeEvent(self, event):
        for d in self.devices_in_tabs.copy():
            self.removeDevice(d)

        metro.app.removeDeviceGroup(self)

    def _getContainedDevices(self):
        return self.devices_in_tabs

    def show(self):
        super().show()

        # Compute the extra geometry added by the QTabWidget
        own_size = self.size()
        tab0_size = (self.widget(0).size() if self.count() > 0
                     else QtCore.QSize(0, 0))

        self.extra_height = own_size.height() - tab0_size.height()
        self.extra_width = own_size.width() - tab0_size.width()

    def addDevice(self, d):
        if not isinstance(d, QtWidgets.QWidget):
            raise TypeError('device must inherit QWidget')

        d._TabGroupWidget_orig_geometry = d.geometry()
        d._TabGroupWidget_orig_visible = d.isVisible()

        orig_size = d.size()
        self.addTab(d, d._name)

        if self.widget(0) == self.tabEmpty:
            self.removeTab(0)
            self.setTabsClosable(True)
            new_size = QtCore.QSize(0, 0)
        else:
            new_size = self.size()

        if orig_size.width() + self.extra_width > new_size.width():
            new_size.setWidth(orig_size.width() + self.extra_width)

        if orig_size.height() + self.extra_height > new_size.height():
            new_size.setHeight(orig_size.height() + self.extra_height)

        self.resize(new_size)

        d.show()
        d.setDeviceGroup(self)  # Show first to ensure update

        self.devices_in_tabs.append(d)
        self.setCurrentIndex(self.count() - 1)

    def removeDevice(self, d):
        index = self.devices_in_tabs.index(d)

        self.removeTab(index)
        self.devices_in_tabs.remove(d)

        d.setParent(None)
        d.setGeometry(d._TabGroupWidget_orig_geometry)

        d.setDeviceGroup(None)  # Show last to ensure update
        d.show()

        if not d._TabGroupWidget_orig_visible:
            d.hide()

        if self.count() == 0:
            self.setTabsClosable(False)
            self.addTab(self.tabEmpty, '')
            self.resize(self.sizeHint())

    @metro.QSlot(int)
    def on_tabCloseRequested(self, index):
        self.removeDevice(self.widget(index))

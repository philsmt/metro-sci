
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# This module implements channels, which are undirectional connections
# between a provider and an arbitrary number of subscribers. The
# provider broadcasts data to all subscribers by setting (replacing the
# current content) or adding the data content of a channel.
#
# There are both complete implementations available (currently only
# NumericChannel) and it is possible to inherit from AbstractChannel and
# implement various abstract methods.
#
# In most cases related to data acquisition, NumericChannel is the
# optimal choice.


import copy
import datetime
import functools
import multiprocessing
import traceback
from time import time as time_now
from typing import Any, Callable, Iterable, List, Mapping, Union, Tuple, \
    Sequence
from typing.io import IO

import numpy
import h5py


_channels = {}
_watchers = {}


def get(name: str) -> 'AbstractChannel':
    """Get a channel by name.

    Args:
        name: A string containing the complete channel name.

    Returns:
        The requested channel object.

    Raises:
        KeyError: No channel found with that name.
    """

    return _channels[name]


def getAll() -> Iterable['AbstractChannel']:
    """Get all current channels.

    Returns:
        A dict view containing all channel objects.
    """

    return _channels.values()


def sortByDependency(all_channels: Iterable['AbstractChannel']
                     ) -> List['AbstractChannel']:
    """Sort a channel list by its dependencies.

    Some channels may depend on other channels, such as a channel in
    computing or integrating mode, depend on its arguments. This
    function takes a list of channels and sorts it in such a way that
    all dependencies are satisfied using a topological sort algorithm.
    This is for example used by the measuring controller while calling
    all channels at the beginning/end of each step/scan.

    Args:
        all_channels: list of channel objects

    Returns:
        A list containing the same channels as all_channels, but sorted
        by dependency.

    Raises:
        RuntimeError: Circular channel dependency detected
    """

    # First we build the graph for our topological sort. This is a list
    # containing a tuple with each channel object and a set containing
    # the channel objects this channel depends on.
    graph = []

    # For this we loop over every channel-channel combination and check
    # for dependency. We could omit this step if channels would deliver
    # a list with all dependencies themselves, but this is "only" O(n²)
    # keeps the interface much more clean.
    for outer_channel in all_channels:
        deps = set()

        for inner_channel in all_channels:
            if outer_channel is inner_channel:
                continue

            if outer_channel.dependsOn(inner_channel):
                deps.add(inner_channel)

        graph.append((outer_channel, deps))

    # This list contains our channels sorted by dependency.
    final_channels = []

    # This set is used in the topological sort and contains all
    # dependencies that are already satisfied.
    provided_deps = set()

    # We loop until there are no unsorted channels left
    while graph:
        # This becomes our new graph at the end of this loop iteration
        # with all channels that are not yet taken care of
        remaining_graph = []

        # This flag ensures that we emit a channel on each iteration. If
        # not we have a cyclic dependency and fail!
        emitted = False

        # Loop through all remaining channels
        for channel, deps in graph:
            # Check of all dependencies of this channel has already
            # been taken care of
            if deps.issubset(provided_deps):
                # If yes, add it to our final list and to the satisfied
                # dependencies (emit it)
                final_channels.append(channel)
                provided_deps.add(channel)
                emitted = True
            else:
                # If not, add it to our remaining graph
                remaining_graph.append((channel, deps))

        # If this flag is still false, we did not emit a single channel
        # and therefore had unsatisfiable dependencies (cycles).
        if not emitted:
            raise RuntimeError('circular channel dependency detected')

        # Switch our graph to all remaining channels.
        # This operation is equivalent of removing channels from our
        # original graph, but it is not possible to change a list being
        # iterated upon.
        graph = remaining_graph

    return final_channels


def query(hint: Union[int, str, None] = None,
          freq: Union[int, str, None] = None,
          type_: Union[type, None] = None,
          shape: Union[int, None] = None) -> List['AbstractChannel']:
    """Query channels with certain parameters.

    The query can be limited to a certain hint, freq or type.

    Args:
        hint: Data hint to query for to either as one of the magic
            constants or the respective string describing it, None as
            wildcard.
        freq: Frequency to query for to either as one of the magic
            constants or the respective string describing it, None as
            wildcard.
        type: Limits all results to a certain type of channel, None as
            wildcard.
        shape: Shape paramter to query for or None as wildcard. This
            property is actually not part of AbstractChannel, but used
            in the common implementation NumericChannel. Using this
            argument on non-compatible channels will simply exclude
            them from the results.

    Returns:
        A list of strings with the channel names complying with the
        specified query parameters.
    """

    if isinstance(hint, str):
        hint = AbstractChannel.getHintConstant(hint)

    if isinstance(freq, str):
        freq = AbstractChannel.getFrequencyConstant(freq)

    res = []

    for name in _channels:
        channel = _channels[name]
        hit = True

        if hint is not None and hint != channel.hint:
            hit = False

        if freq is not None and freq != channel.freq:
            hit = False

        if type_ is not None and not isinstance(channel, type_):
            hit = False

        if shape is not None:
            try:
                if shape != channel.shape:
                    hit = False
            except AttributeError:
                hit = False

        if hit:
            res.append(name)

    return res


def watch(watcher: object,
          hint: Union[int, str, None] = None,
          freq: Union[int, str, None] = None,
          type_: Union[type, None] = None,
          shape: Union[int, None] = None,
          channel: Union['AbstractChannel', None] = None,
          callbacks: Union[List[str], None] = None) -> None:
    """Watch the channel list for certain parameters.

    A watcher is notified whenever a channel is opened or closed. A
    watcher object may register once for a set of parameters. Any
    subsequent call will only change the parameters.

    Args:
        watcher: An object that is notified of changes to the channel
            list conforming to the parameters. The exact callbacks are
            implementation-specific for a channel, but there are generic
            ones supported by AbstractChannel.
        hint: Data hint to exclusively watch for to either as one of
            the magic constants or the respective string describing it,
            None as wildcard.
        freq: Frequency to exclusively watch for to either as one of
            the magic constants or the respective string describing it,
            None as wildcard.
        shape: Shape paramter to watch for or None as wildcard. The
            same restrictions apply here as for the shape argument of
            query().
        type: An optional type object specifying a channel type to
            exclusively watch for or None as wildcard.
        channel: An optional object specifying a specific channel to
            exclusively watch for or None as wildcard.
        callbacks: An optional list of callbacks to watch for
            exclusively.
    """

    if isinstance(hint, str):
        hint = AbstractChannel.getHintConstant(hint)

    if isinstance(freq, str):
        freq = AbstractChannel.getFrequencyConstant(freq)

    _watchers[watcher] = (hint, freq, type_, shape, channel, callbacks)


def unwatch(watcher: object) -> None:
    """Stop watching the channel list.

    Args:
        watcher: The object to stop watching the channel list.

    Raises:
        KeyError: Invalid watcher object.
    """

    del _watchers[watcher]


class Subscriber(object):
    """Interface for channel subscribers.

    A channel subscriber listens to data changes in the respective
    channel by using callbacks. Note that like the channels API in
    general, these methods are always called on the main thread!
    """

    def dataSet(self, d: Any) -> None:
        """Callback for when channel data is set.

        Setting channel data replaces all current data for the active
        step. The subscriber should therefore discard all previous
        data received through dataAdded. There is no dataCleared call
        in this case.

        Args:
            d: data the current step was set to. Do not modify this
                object as it shared across all subscribers, make a
                copy in this case.
        """

        pass

    def dataAdded(self, d: Any) -> None:
        """Callback for when channel data is added.

        Adding channel data appends this to the rows already emitted in
        the active step.

        Args:
            d: data added to the current step. Do not modify this
                object as it shared across all subscribers, make a
                copy in this case.
        """

        pass

    def dataCleared(self) -> None:
        """Callback for when channel data is cleared.

        Clearing channel data causes the buffer for the active step to
        be empty. This is also called on each step boundary to prepare
        for the new step (even for measurements with multiple scans due
        to performance considerations!).
        """

        pass


class AbstractChannel(object):
    """Abstract base class for all channels.

    This class defines the general interface and functionality common to
    all channels. It contains an implementation for subscribing/
    unsubschribing from a channel as well as handling direct/remote/
    computing/integrating mode. It is still completely independant of
    any data model for the actual data the channel will contain in the
    end.

    A new channel implementation can therefore either extend this class
    and implement this completely on its own or extend LocalChannel,
    which uses python lists and numpy arrays to hold the data.

    All methods in this class are NOT thread-safe and may NOT be called
    from any other thread but the main thread! This is a hard assumption
    for all code in this class and any extending class, since channels
    make heavy use of direct callbacks for performance reasons and have
    to guarantee to this callback code to also run on the main thread.
    Again, calling it from other threads WILL break things!

    This abstract class is incomplete and requires the implementation
    of several methods that will raise NotImplementedError by default:

        reset
        isEmpty
        getStepCount

        getData
        setData
        addData
        clearData

    All other methods that are overriden should call the super
    implementation as well.
    """

    """Channel mode constants.

    The mode of a channel specifies how samples are generated.

    DIRECT      Samples are generated directly by manual calls to the
                public API.

    COMPUTING   The channel computes samples by using samples emitted
                by one or more other channel(s), once per sample
                emitted.

    INTEGRATING Similar to the COMPUTING mode, but limited to once per
                step and scan. A channel operating in this mode will
                always use STEP as frequency property.

    REMOTE      A channel from another Metro instance is replicated over
                a socket connection.

    """
    DIRECT_MODE = 0
    COMPUTING_MODE = 1
    INTEGRATING_MODE = 2
    REMOTE_MODE = 3

    """Data hint constants.

    This optional property of a channel can be used to suggest a
    suitable presentation for this channel's data to the user.

    UNKNOWN_HINT    No hint is given, the user may have to decide on its
                    own on how to display the data.

    ARBITRARY_HINT  The channel does not necessarily contain numeric
                    data and therefore it should not be attempted to
                    be displayed with the generic devices.

    INDICATOR_HINT  Only the most recent sample should be displayed at
                    a time. This hint is useful when complete data sets
                    are added to a channel instead of point-by-point.

    WAVEFORM_HINT   The probed variable varies over time and should be
                    presented on a value by value base.

    HISTOGRAM_HINT  The distribution of a certain variable is measured
                    at possibly irregular intervals. Not the individual
                    values are of interest, but a histogram of said
                    distribution.

    """
    UNKNOWN_HINT = 0
    ARBITRARY_HINT = 1
    INDICATOR_HINT = 2
    WAVEFORM_HINT = 3
    HISTOGRAM_HINT = 4

    """Channel frequency constants.

    The frequency of a channel specifies how samples are emitted to
    subscribers and what data layout they can expect from this channel.
    It can also change the semantics of certain method calls.

    CONTINUOUS  Samples are generated at arbitrary intervals and are
                grouped in steps. For several scans, the samples are
                appended to the same step.

    STEP        There is always exactly ONE sample at the end of each
                step over all scans. This mode is used for statistics
                over one step like number of counts an average and also
                internally once a channel is switched to integrating
                mode. If used with a direct channel, the sample may be
                generated at the stopped signal.

    SCHEDULED   This mode completely ignores step boundaries and simply
                emits samples at a known interval.
    """
    CONTINUOUS_SAMPLES = 0
    STEP_SAMPLES = 1
    SCHEDULED_SAMPLES = 2

    """Magic step indices

    These magic constants are for addressing relative step indices like
    the current or all at once. Channel implementation may use the
    assumption that any index below 0 is a special index.
    """
    CURRENT_STEP = -1
    ALL_STEPS = -2

    def __init__(self, *names, **options) -> None:
        """Open the channel.

        This method uses a particular way of dealing with its
        arguments. All positional arguments are converted into strings
        and concatenated with the '#' into the name of this channel.
        The keyword parameters are used to specify various channel
        parameters:

            hint: see setHint()
            freq: see setFreqeuency()
            static: A boolean to indicate whether this channel is
                static. Such channels do not participate in
                measurements and do not change their data contents.
        """

        name = '#'.join([str(x) for x in names])

        if name in _channels:
            raise ValueError('name "{0}" already in use'.format(name))

        self.name = name

        self.locked = False
        self.subscribers = []
        self.listener = []
        self.header_tags = {}
        self.display_arguments = {}

        self.mode = AbstractChannel.DIRECT_MODE

        try:
            self.setHint(options['hint'])
        except KeyError:
            self.hint = AbstractChannel.WAVEFORM_HINT

        try:
            self.setFrequency(options['freq'])
        except KeyError:
            self.freq = AbstractChannel.CONTINUOUS_SAMPLES

        try:
            self.static = bool(options['static'])
        except KeyError:
            self.static = False

        _channels[self.name] = self

        self._notify('channelOpened')

    def __str__(self) -> None:
        return '{0}({1})'.format(self.__class__.__name__, self.name)

    # PRIVATE METHODS
    def _notify(self, callback: str) -> None:
        """Trigger a callback to channel watchers.

        This method will call a method with the supplied name on all
        channel watchers whose watch parameters are compatible with the
        name of this channel as the only argument.

        Args:
            callback: String with the method name to call on watchers
        """

        for watcher in _watchers:
            opts = _watchers[watcher]

            if opts[0] is not None and opts[0] != self.hint:
                continue
            elif opts[1] is not None and opts[1] != self.freq:
                continue
            elif opts[2] is not None and not isinstance(self, opts[3]):
                continue
            elif opts[3] is not None:
                try:
                    if opts[3] != self.shape:
                        continue
                except AttributeError:
                    continue
            elif opts[4] is not None and opts[4] != self:
                continue
            elif opts[5] is not None and callback not in opts[5]:
                continue

            try:
                method = getattr(watcher, callback)
            except AttributeError:
                pass
            else:
                method(self)

    def _computing_single_dataAdded(self, d: Any) -> None:
        """Channel callback in computing mode.

        Callback for dataAdded on the input channel in computing mode.
        Note that this version is only used if the kernel argument
        consists of exactly one argument as an optimized form of
        _computing_multiple_dataAdded.
        """

        try:
            value = self.kernel(d)
        except Exception as e:
            print('An unechecked exception was raised in the computing '
                  'kernel of {0}:'.format(self.name))

            traceback.print_exception(type(e), e, e.__traceback__)
        else:
            self.addData(value)

    def _computing_multiple_dataAdded(self, d: Any, index: int) -> None:
        """Channel callback in computing mode.

        Callback for dataAdded on the input channels in computing mode.
        It has been modified with functools to always include an index
        identifying the channel adding data.  Note that this is only
        used if the kernel argument consists of more than one channel.
        """

        self.input_stack[index] = d

        if None not in self.input_stack:
            try:
                value = self.kernel(*self.input_stack)
            except Exception as e:
                print('An unechecked exception was raised in the computing '
                      'kernel of {0}:'.format(self.name))

                traceback.print_exception(type(e), e, e.__traceback__)
            else:
                self.addData(value)

            self.input_stack = [None] * len(self.input_channels)

    def _stopComputing(self) -> None:
        """Terminate computing mode.

        The actual mode flag is not changed, but the used resources are
        properly deallocated such as channel subscriptions.
        """

        for subscr in self.input_subscriber:
            subscr.channel.unsubscribe(subscr)

        self.kernel = None
        self.input_channels = None
        self.input_subscriber = None
        self.input_stack = None

    def _stopIntegrating(self) -> None:
        """Terminate integrating mode.

        The actual mode flag is not changed, but the used resources are
        properly deallocated.
        """

        self.kernel = None
        self.input_channels = None

    # PUBLIC IMPLEMENTATION API
    def dependsOn(self, channel: 'AbstractChannel') -> bool:
        """Check for dependance on other channel.

        A channel might depend on another channel such as in computing
        mode it depends on its input channels to properly emit all
        samples before ending a step. This method is used by
        sortByDependency to sort a list of channels according to these
        dependencies.

        Args:
            channel: Channel object to test dependency for (whether this
                channel depends on the input channel).

        Returns:
            A boolean indicating dependency.
        """

        try:
            return channel in self.input_channels
        except AttributeError:
            return False

    def isStatic(self) -> bool:
        """Check if the channel is static.

        A static channel will be ignored by the measuring process. It
        may be used to store static data independant of measurements

        Returns:
            A boolean indicating whether the channel is static.
        """

        return self.static

    def beginScan(self, scan_counter: int) -> None:
        """Begin a scan.

        The measuring controller calls this method at the begin of every
        scan iteration, so that a channel can properly prepare. One
        consequence in AbstractChannel is the lockdown of this channel
        to measuring mode, which prohibits certain operations.

        Any data operation before beginScan and after the respective
        endScan should be considered offline.

        Args:
            scan_counter: The current scan iteration counter.
        """

        self.locked = True

    def beginStep(self, step_value: Any) -> None:
        """Begin a step.

        The measuring controller calls this method at the begin of every
        step, so that a channel can properly prepare.

        Args:
            step_value: A value describing this step of arbitrary type,
                which is assumed to stay constant for the same step
                across several scan iterations.
        """

        pass

    def endStep(self) -> None:
        """End a step.

        The measuring controller calls this method at the end of every
        step, so that a channel can perform cleanup work.

        In integrating mode, the result for a step is calculated in this
        method.
        """

        if self.mode == AbstractChannel.INTEGRATING_MODE:
            stack = []

            for ch in self.input_channels:
                d = ch.getData()

                if d is None:
                    stack = None
                    break

                stack.append(ch.getData())

            if stack is not None:
                try:
                    value = self.kernel(*stack)
                except Exception as e:
                    print('An unechecked exception was raised in the '
                          'integrating kernel of {0}:'.format(self.name))

                    traceback.print_exception(type(e), e, e.__traceback__)
                else:
                    self.addData(value)

    def endScan(self) -> None:
        """End a scan.

        The measuring controller calls this method at the end of every
        scan iteration, so that a channel can perform cleanup work.

        Any data operation after endScan and before the next beginScan
        should be considered offline.
        """

        self.locked = False

    def openStorage(self, base_path: str) -> None:
        """Enter storage mode.

        Args:
            base_path: A string that uniquely identifies this storage
                operation.
        """

        pass

    def closeStorage(self) -> None:
        """Leave storage mode."""

        pass

    def reset(self) -> None:
        """Reset the channel.

        This is an abstract method required to be implemented by a
        subclass.

        A resetted channel is considered completely empty with a
        similar buffer layout like after creation. It resets only its
        contents and not other properties like mode or freqeuency.
        """

        raise NotImplementedError('reset')

    def isEmpty(self) -> bool:
        """Check if the active step is empty.

        This is an abstract method required to be implemented by a
        subclass.
        """

        raise NotImplementedError('isEmpty')

    def getStepCount(self) -> int:
        """Get the number of steps in this channel's buffers.

        This is an abstract method required to be implemented by a
        subclass.

        The cound returned by this method should not include the offline
        step or any other special steps, but only those created by a
        measurement.
        """

        raise NotImplementedError('getStepCount')

    # PUBLIC USER API
    @staticmethod
    def getByName(name: str) -> 'AbstractChannel':
        """Get the object of a channel by its name.

        A shortcut for the get() function in this module.
        """

        return get(name)

    """
    Shortcuts for the watch()/unwatch() function in this module.
    """
    watch = staticmethod(watch)
    unwatch = staticmethod(unwatch)

    def listen(self, watcher, **params) -> None:
        """Listen to callbacks of this channel.

        A shortcut for watching on this very specific channel only. It
        uses internally the watch() function to register itself, it
        therefore impose the same restrictions of unique watchers. The
        equivalent call to watch() is:

        watch(watcher, channel=self, ...)

        Args:
            watcher: An object that is notified of callbacks on this
                channel.
            same keywords as watch()
        """
        watch(watcher, channel=self, **params)

    # Synonym for unwatch()
    unlisten = unwatch

    @staticmethod
    def getModeString(mode_id: int) -> str:
        """Convert a channel mode constant into a string.

        Args:
            mode_id: The magic constant specifying a channel mode.

        Returns:
            The string describing the respective channel mode.
        """

        if mode_id == AbstractChannel.DIRECT_MODE:
            mode_str = 'direct'
        elif mode_id == AbstractChannel.REMOTE_MODE:
            mode_str = 'remote'
        elif mode_id == AbstractChannel.COMPUTING_MODE:
            mode_str = 'computing'
        elif mode_id == AbstractChannel.INTEGRATING_MODE:
            mode_str = 'integrating'
        else:
            raise ValueError('unknown mode constant {0}'.format(mode_id))

        return mode_str

    @staticmethod
    def getHintConstant(hint_str: str) -> int:
        """Convert a string into a channel hint constant.

        Args:
            hint_str: A string describing the channel hint.

        Returns:
            One of the magic constants specifying the respective
            channel hint.
        """

        hint_str = hint_str.strip().lower()

        if hint_str == 'unknown':
            hint = AbstractChannel.UNKNOWN_HINT
        elif hint_str == 'arbitrary':
            hint = AbstractChannel.ARBITRARY_HINT
        elif hint_str == 'indicator':
            hint = AbstractChannel.INDICATOR_HINT
        elif hint_str == 'waveform':
            hint = AbstractChannel.WAVEFORM_HINT
        elif hint_str == 'histogram':
            hint = AbstractChannel.HISTOGRAM_HINT
        else:
            raise ValueError('unknown hint string "{0}"'.format(hint_str))

        return hint

    @staticmethod
    def getHintString(hint_id: int) -> str:
        """Convert a channel hint constant into a string.

        Args:
            mode_id: The magic constant specifying a channel hint.

        Returns:
            The string describing the respective channel hint.
        """

        if hint_id == AbstractChannel.UNKNOWN_HINT:
            hint_str = 'unknown'
        elif hint_id == AbstractChannel.ARBITRARY_HINT:
            hint_str = 'arbitrary'
        elif hint_id == AbstractChannel.INDICATOR_HINT:
            hint_str = 'indicator'
        elif hint_id == AbstractChannel.WAVEFORM_HINT:
            hint_str = 'waveform'
        elif hint_id == AbstractChannel.HISTOGRAM_HINT:
            hint_str = 'histogram'
        else:
            raise ValueError('unknown hint constant {0}'.format(hint_id))

        return hint_str

    @staticmethod
    def getFrequencyConstant(freq_str: str) -> int:
        """Convert a string into a channel frequency constant.

        Args:
            hint_str: A string describing the channel frequency.

        Returns:
            One of the magic constants specifying the respective
            channel frequency.
        """

        freq_str = freq_str.strip().lower()

        if freq_str == 'continuous' or freq_str == 'cont':
            freq = AbstractChannel.CONTINUOUS_SAMPLES
        elif freq_str == 'step':
            freq = AbstractChannel.STEP_SAMPLES
        elif freq_str == 'scheduled':
            freq = AbstractChannel.SCHEDULED_SAMPLES
        else:
            raise ValueError('unknown frequency string "{0}"'.format(freq_str))

        return freq

    @staticmethod
    def getFrequencyString(freq_id: int) -> str:
        """Convert a channel frequency constant into a string.

        Args:
            mode_id: The magic constant specifying a channel frequency.

        Returns:
            The string describing the respective channel frequency.
        """

        if freq_id == AbstractChannel.CONTINUOUS_SAMPLES:
            freq_str = 'continuous'
        elif freq_id == AbstractChannel.STEP_SAMPLES:
            freq_str = 'step'
        elif freq_id == AbstractChannel.SCHEDULED_SAMPLES:
            freq_str = 'scheduled'
        else:
            raise ValueError('unknown frequency constant {0}'.format(freq_id))

        return freq_str

    def subscribe(self, obj: Subscriber) -> None:
        """Subscribe to this channel.

        Add a subscriber object to this channel that receives callbacks.

        Args:
            obj: The Subscriber object to be added
        """

        if self.name not in _channels:
            raise RuntimeError('channel is closed')

        self.subscribers.append(obj)

        obj._channel_subscriber_step_index = AbstractChannel.CURRENT_STEP

        self._notify('subscriberAdded')

    def getSubscribedStep(self, obj: Subscriber) -> int:
        """
        Return the subscribed step for an object.

        Args:
            obj: The subscriber object the step should be returned for.

        Returns:
            An integer either describing a specific step or a special
            step index.
        """
        return obj._channel_subscriber_step_index

    def setSubscribedStep(self, obj: Subscriber, step_index: int) -> None:
        """Set the subscribed step for an object.

        Args:
            obj: The subscriber object the step should be changed for.
            step_index: An integer containing either a specific step or
                a special index.
        """

        if obj._channel_subscriber_step_index == step_index:
            return

        obj._channel_subscriber_step_index = step_index

    def unsubscribe(self, obj: Subscriber) -> None:
        """Unsubscribe from this channel.

        Removes a subscriber object from this channel to no longer
        receive any callbacks.

        Args:
            obj: The Subscriber object to be removed
        """

        self.subscribers.remove(obj)

        self._notify('subscriberRemoved')

    def hintDisplayArgument(self, key: str, value: Any) -> None:
        """Suggest a non-default value for arguments of display devices.

        Args:
            key: The argument key as a string in object notation to
                hint, e.g. display.plot.steps
            value: The value this argument should use, None to unset
        """

        if value is None:
            del self.display_arguments[key]
        else:
            self.display_arguments[key] = value

    def hintDisplayArguments(self, arg_map: Mapping[str, Any]) -> None:
        """Suggest non-default values for arguments of display devices.

        This method allows to set several arguments at once compared to
        hintDisplayArgument(key, value).

        Args:
            arg_map: A mapping of key, value pairs to set in the same
                format as corresponding calls to hintDisplayArgument.

        """

        for key, value in arg_map.items():
            self.hintDisplayArgument(key, value)

    def setDirect(self) -> None:
        """Change this channel to direct mode.

        This method may not be called during a measurement.
        """

        if self.locked:
            raise RuntimeError('channel is locked')

        if self.mode == AbstractChannel.DIRECT_MODE:
            return
        elif self.mode == AbstractChannel.COMPUTING_MODE:
            self._stopComputing()
        elif self.mode == AbstractChannel.INTEGRATING_MODE:
            self._stopIntegrating()
        elif self.mode == AbstractChannel.REMOTE_MODE:
            pass

        self.mode = AbstractChannel.DIRECT_MODE

        return self

    def setComputing(self, kernel: Callable,
                     input_channels: Sequence['AbstractChannel']) -> None:
        """Change this channel to computing mode.

        This method may not be called during a measurement.

        In computing mode a kernel is evaluated for samples emitted by a
        set of channels called inputs of the computing channel. The
        computing channel saves the last value generated by one of the
        input channels and executes the kernel once it has a value for
        each channel, passing these as arguments. The return value is
        added to this channel.

        If one input channel emits values at a higher frequency than
        another input channel, samples of the faster one will therefore
        be skipped.

        Args:
            kernel: The callable object acting as the kernel of this
                computing channel.
            input_channels: A sequence of channel objects that serve as
                inputs for the computing kernel.
        """

        if self.locked:
            raise RuntimeError('channel is locked')

        if self.mode == AbstractChannel.COMPUTING_MODE:
            return
        elif self.mode == AbstractChannel.INTEGRATING_MODE:
            self._stopIntegrating()

        self.mode = AbstractChannel.COMPUTING_MODE

        self.kernel = kernel
        self.input_channels = input_channels.copy()
        self.input_subscriber = []

        if len(input_channels) == 1:
            # We do a slight optimization for single argument kernels
            # here since this use case is very common and we can save
            # quite a few allocations for this path.
            self.input_stack = None

            subscr = Subscriber()
            subscr.channel = input_channels[0]
            subscr.dataAdded = self._computing_single_dataAdded

            input_channels[0].subscribe(subscr)
            self.input_subscriber.append(subscr)

        else:
            self.input_stack = [None] * len(self.input_channels)

            i = 0

            for ch in self.input_channels:
                subscr = Subscriber()
                subscr.channel = ch
                # This creates a new callable object that will call the
                # supplied function with the additional given argument.
                # Here this is used to supply a channel index to the
                # dataAdded callback, so that all channels can use the
                # same method while still being able to distinguish
                # between each.
                subscr.dataAdded = functools.partial(
                    self._computing_multiple_dataAdded, index=i
                )

                ch.subscribe(subscr)

                self.input_subscriber.append(subscr)
                i += 1

        return self

    def setIntegrating(self, kernel: Callable,
                       input_channels: Sequence['AbstractChannel']) -> None:
        """Change this channel to integrating mode.

        This method may not be called during a measurement.

        In integrating mode a kernel is evaluated at the end of each
        step passing all data generated by a set of channels called
        inputs as arguments. The result value is set to this channel.

        Args:
            kernel: The callable object acting as the kernel of this
                integrating channel.
            input_channels: A sequence of channel objects that serve as
                inputs for the integrating kernel.
        """

        if self.locked:
            raise RuntimeError('channel is locked')

        if self.mode == AbstractChannel.INTEGRATING_MODE:
            return
        elif self.mode == AbstractChannel.COMPUTING_MODE:
            self._stopComputing()

        self.mode = AbstractChannel.INTEGRATING_MODE

        self.kernel = kernel
        self.input_channels = input_channels.copy()

        self.setFrequency(AbstractChannel.STEP_SAMPLES)

        return self

    def setRemote(self, host: str, name: str) -> None:
        """Change this channel to remote mode."""

        self.mode = AbstractChannel.REMOTE_MODE

    def setHint(self, new_hint: Union[int, str]) -> None:
        """Change the data hint of this channel.

        Args:
            new_hint: Data hint to set to either as one of the magic
                constants or the respective string describing it

        Returns:
            The channel object itself to allow call chaining.

        Raises:
            ValueError: Unknown hint string.
        """

        if isinstance(new_hint, str):
            new_hint = AbstractChannel.getHintConstant(new_hint)

        self.hint = new_hint

        return self

    def setFrequency(self, new_freq: Union[int, str]) -> None:
        """Change the frequency of this channel.

        This method may not be called during a measurement

        Args:
            new_freq: Frequency to set to either as one of the magic
                constants or the respective string describing it

        Returns:
            The channel object itself to allow call chaining.

        Raises:
            ValueError: Unknown frequency string.
        """

        if self.locked:
            raise RuntimeError('channel is locked')

        if isinstance(new_freq, str):
            new_freq = AbstractChannel.getFrequencyConstant(new_freq)

        self.freq = new_freq

        return self

    def close(self) -> None:
        """Close this channel.

        After closing, no data should be added to a channel. It is no
        longer visible and can no longer be subscribed to.

        Channels depending on this channel will still hold a reference
        to the closed channel until closed themselves.
        """

        if self.mode == AbstractChannel.REMOTE_MODE:
            pass
        elif self.mode == AbstractChannel.COMPUTING_MODE:
            self._stopComputing()
        elif self.mode == AbstractChannel.INTEGRATING_MODE:
            self._stopIntegrating()

        self._notify('channelClosed')

        del _channels[self.name]

    def setHeaderTag(self, tag: str, value: str) -> None:
        """Set a custom header tag.

        These tags are meant to describe metadata and are saved in a
        channel-specific header in storage mode.

        Arguments:
            tag: A string containing the tag name
            value: A string containing the tag value
        """

        self.header_tags['X-' + tag] = value

    def addMarker(self, text: str) -> None:
        """Write a custom marker.

        Args;
            text: A string containing the marker to write.
        """

        pass

    def copyLayoutFrom(self, ch: 'AbstractChannel') -> None:
        """Copy step layout of another channel.

        The buffer layout requrements are replicated into this channel.
        This is most useful for static channels which may come with some
        arbitrary layout, but also useful on projections in general.
        The data in this channel is not meant to be changed, but the
        buffers are guaranteed to be able to cope with the same step
        indices.

        This is an abstract method required to be implemented by a
        subclass.

        Arguments:
            ch: The channel object to copy the structure from
        """

        raise NotImplementedError('copyLayoutFrom')

    def dump(self, step: int = CURRENT_STEP, fp: IO = None) -> None:
        """Dump channel data.

        This is an abstract method required to be implemented by a
        subclass.
        """

        pass

    def getData(self, step_index: int = CURRENT_STEP) -> Any:
        """Get channel data.

        This is an abstract method required to be implemented by a
        subclass.

        Args:
            step_index: An integer describing the step to return

        Returns:
            Requested channel data.
        """

        raise NotImplementedError('getData')

    def setData(self, value: Any) -> None:
        """Set channel data.

        This is an abstract method required to be implemented by a
        subclass.

        Args:
            value: Data the current step of this channel is set to.
        """

        raise NotImplementedError('setData')

    def addData(self, value: Any) -> None:
        """Add channel data.

        This is an abstract method required to be implemented by a
        subclass.

        Args:
            value: Data to be added to the current step of this channel.
        """

        raise NotImplementedError('addData')

    def clearData(self) -> None:
        """Clear channel data.

        This is an abstract method required to be implemented by a
        subclass.
        """

        raise NotImplementedError('clearData')


class ChannelAdapter(AbstractChannel):
    """Adapter for the channel interface.

    This class implements stubs for all abstract methods of a channel.
    It is intended for custom channel implementations that only want to
    plug into specifics of the channel framework without actually
    providing the complete feature set.

    As an example, the sources/dld_rd device uses such a channel to
    obtain the current storage location and stream the raw TDC opcode
    data there.
    """

    def reset(self) -> None:
        pass

    def isEmpty(self) -> bool:
        return True

    def getStepCount(self) -> int:
        return 0

    def getData(self, step_index: int) -> None:
        return None

    def setData(self, value: Any) -> None:
        pass

    def addData(self, value: Any) -> None:
        pass

    def clearData(self) -> None:
        pass


class StreamChannel(AbstractChannel):
    """Robust channel implementation for variable-length numpy arrays.

    This is probably the most commonly used channel throughout the
    various Metro devices. It uses numpy arrays to buffer all provided
    data for a given measurement run. It supports all possbile features
    of AbstractChannel.

    The buffer layout is optimised for frequent insertions rather than
    retrieval. Such an operation may therefore be a rather expensive
    operation (due to the need to compact various data structures) and
    should be avoided during a measurement run. Consider blocking
    between steps in this case.

    In addition to the parameters of AbstractChannel, a shape parameter
    should be provided to determine the dimensionality of the data in
    this channel, which defines the data type for the dataAdded
    callback.

        0: scalar data, addData/dataAdded uses int
        1: numpy array of shape(X,) with X being an arbitrary sample
            amount, addData/dataAdded uses array(X,)
        N(>1): numpy array of shape(X,N) with X being an arbitrary
            sample amount, addData/dataAdded uses array(X,N)

    There is also the option to provide an interval [a,b] via
    setInterval() that guarentees that for all samples x in this
    channel: a <= x <= b. Subscribers may use the rangeChanged callback
    to be notified of any changes to this interval. This range has to
    provided manually by the channel provider using setRange()!
    """

    counter_func_scalar = staticmethod(lambda x: 1)
    emptySet_func_scalar = staticmethod(lambda x: False)

    counter_func_vector = len
    emptySet_func_vector = staticmethod(lambda x: x.size == 0)

    def __init__(self, *names, **options) -> None:
        """Open the channel.

        See AbstractChannel.__init__(names, options)

        An additional keyword parameter is used:

            shape: A non-negative integer describing the dimensionality
                of data contained in this channel. Please see the
                general class documentation for details.
        """

        self.data = [[]]

        self.locked = False

        try:
            self.buffering = bool(options['buffering'])
        except KeyError:
            self.buffering = True

        try:
            self.transient = bool(options['transient'])
        except KeyError:
            self.transient = False

        self.current_index = 0
        self.step_values = []

        try:
            self.shape = int(options['shape'])
        except KeyError:
            self.shape = 0

        if self.shape == 0:
            self.counter_func = self.counter_func_scalar
            self.emptySet_func = self.emptySet_func_scalar

            self._writeData = self._writeData_scalar
            self._compactData = self._compactData_scalar

        elif self.shape > 0:
            self.counter_func = self.counter_func_vector
            self.emptySet_func = self.emptySet_func_vector

            self._writeData = self._writeData_vector
            self._compactData = self._compactData_vector

        else:
            raise ValueError('shape must be non-negative integer value')

        self.range_min = None
        self.range_max = None

        super().__init__(*names, **options)

        self.header_tags['Shape'] = self.shape

    # PRIVATE METHODS
    @staticmethod
    def _writeData_scalar(fp: IO, d: Any) -> None:
        """Write channel data to a file pointer."""

        if isinstance(d, numpy.ndarray):
            numpy.savetxt(fp, d, delimiter='\t')
        else:
            fp.write('{0}\n'.format(d).encode('utf-8'))

    @staticmethod
    def _compactData_scalar(data: Any) -> List[numpy.ndarray]:
        """Compact channel data."""

        if len(data) == 0:
            return data

        if not isinstance(data[0], numpy.ndarray):
            # The complete step is still a python list, simply wrap a
            # numpy array around it. We optimize this special case since
            # no concatenation is needed.
            return [numpy.array(data)]

        else:
            # Here the first element is already a numpy array, so we
            # compacted once in this step. Wrap the remaining elements
            # in a new array and concatenate it.

            old_array = data[0]
            new_array = numpy.array(data[1:])

            return [numpy.concatenate([old_array, new_array])]

    @staticmethod
    def _writeData_vector(fp: IO, d: Any) -> None:
        """Write channel data to a file pointer."""

        numpy.savetxt(fp, d, delimiter='\t')

    @staticmethod
    def _compactData_vector(data: Any) -> None:
        """Compact channel data."""

        return [numpy.concatenate(data)]

    @staticmethod
    def _printException(e: Exception) -> None:
        """Pretty-print an exception."""

        print('An exception was raised by a channel subscriber, which may '
              'cause other subscribers of the same channel to miss this '
              'callback. The data is still saved in the channel buffers (and '
              'written to disk in storage mode.\nThe causing exception reads:')

        traceback.print_exception(type(e), e, e.__traceback__)

    def addMarker(self, text: str) -> None:
        """Write a custom marker.

        Args;
            text: A string containing the marker to write.
        """

        try:
            fp = self.file_pointer
        except AttributeError:
            pass
        else:
            fp.write('# {0}\n'.format(text).encode('ascii'))

    # PUBLIC IMPLEMENTATION API
    def beginScan(self, scan_counter: int) -> None:
        """Begin a scan."""

        super().beginScan(scan_counter)

        self.addMarker('SCAN {0}'.format(scan_counter))

        # Gets incremented by beginStep to 0
        self.current_index = -1

    def beginStep(self, step_value: Any) -> None:
        """Begin a step."""

        try:
            self.data_file_pointer = self.file_pointer
        except AttributeError:
            pass

        super().beginStep(step_value)

        self.current_index += 1

        if step_value is None:
            step_value = str(self.current_index)

        try:
            self.step_values[self.current_index] = step_value
        except IndexError:
            self.step_values.append(step_value)

        if self.current_index > len(self.data)-1 and self.buffering:
            self.data.append([])

        if self.freq == AbstractChannel.CONTINUOUS_SAMPLES:
            self.addMarker('STEP {0}: {1}'.format(self.current_index,
                                                  step_value))

            for s in self.subscribers:
                step_index = s._channel_subscriber_step_index

                if (step_index == AbstractChannel.CURRENT_STEP
                        or step_index == self.current_index):
                    if (self.buffering and
                            len(self.data[self.current_index]) > 0):
                        s.dataSet(self.getData())
                    else:
                        s.dataCleared()
        elif self.freq == AbstractChannel.SCHEDULED_SAMPLES:
            self.addMarker('STEP {0}: {1}'.format(self.current_index,
                                                  step_value))

    def endStep(self) -> None:
        """End a step."""

        super().endStep()

        try:
            del self.data_file_pointer
        except AttributeError:
            pass

        try:
            self.file_pointer.flush()
        except AttributeError:
            pass
        except ValueError as e:
            print('ValueError on flush of', self.name, e)

    def copyDataFrom(self, chan: AbstractChannel) -> None:
        """Copy the data from another into this channel.

        Args:
            chan: Channel to copy the data from.
        """

        self.data = copy.deepcopy(chan.data)
        self.step_values = copy.deepcopy(chan.step_values)

        self.current_index = chan.current_index

    def openStorage(self, base_path: str) -> None:
        if self.transient:
            return

        # If a file pointer exists, we are already storing
        if hasattr(self, 'file_pointer'):
            return

        # The file is opened in binary mode since apparently
        # numpy.savetxt operates on byte buffers instead of strings. We
        # therefore have to encode all our own strings ourselves!
        fp = open('{0}_{1}.txt'.format(base_path, self.name), 'wb')

        fp.write('# Name: {0}\n# Hint: {1}\n# Frequency: {2}\n'.format(
            self.name, self.getHintString(self.hint),
            self.getFrequencyString(self.freq)
        ).encode('ascii'))

        for tag, value in self.header_tags.items():
            fp.write('# {0}: {1}\n'.format(tag, value).encode('ascii'))

        for key, value in self.display_arguments.items():
            fp.write('# DISPLAY {0}: {1}\n'.format(key, value).encode('ascii'))

        self.file_pointer = fp

    def closeStorage(self) -> None:
        try:
            fp = self.file_pointer
        except AttributeError:
            pass
        else:
            fp.close()
            del self.file_pointer

    def subscribe(self, obj: Subscriber, silent: bool = False) -> None:
        """Subscribe to this channel.

        Add a subscriber object to this channel that receives callbacks.

        Args:
            obj: The Subscriber object to be added
            silent: Optional boolean to indicate that no callbacks
                should be fired upon subscribing. This may include the
                added or cleared callback depending on the channel's
                data content.
        """

        super().subscribe(obj)

        if not silent and self.buffering:
            d = self.getData()

            if d is None:
                obj.dataCleared()
            else:
                obj.dataSet(d)

    def setSubscribedStep(self, obj: Subscriber, step_index: int) -> None:
        """Set the subscribed step for an object.

        Changing the subscribed step for a subscriber may trigger a
        dataSet callback if the new step contains data.

        Args:
            obj: The subscriber object the step should be changed for.
            step_index: An integer containing either a specific step or
                a special index.
        """

        super().setSubscribedStep(obj, step_index)

        if not self.buffering:
            return

        try:
            data = self.getData(step_index)
        except ValueError:
            pass
        else:
            obj.dataSet(data)

    def reset(self) -> None:
        """Reset the channel."""

        self.data.clear()

        self.data.append([])
        self.current_index = 0

        for s in self.subscribers:
            s.dataCleared()

    def isEmpty(self) -> bool:
        """Check if the active step is empty."""

        if not self.buffering:
            return True

        # UNUSED METHOD?!

        return len(self.data[self.current_index]) == 0

    def getStepCount(self) -> int:
        """Get the number of steps in this channel's buffers."""

        return len(self.data)

    def copyLayoutFrom(self, ch: AbstractChannel) -> None:
        """Copy step layout of another channel."""

        if isinstance(ch, NumericChannel):
            self.step_values = ch.step_values

        step_diff = ch.getStepCount() - len(self.data)

        if step_diff > 0:
            for i in range(step_diff):
                self.data.append([])

    # PUBLIC USER API
    def dump(self, step: int = AbstractChannel.CURRENT_STEP,
             fp: IO = None) -> None:
        """Dump channel data."""

        if fp is None:
            try:
                fp = self.file_pointer
            except AttributeError:
                raise ValueError('no file pointer supplied and channel is not '
                                 'in storage mode')

        d = self.getData(step)

        if d is not None:
            self._writeData(fp, d)

    def setAveraging(self, ch_input: AbstractChannel) -> None:
        self.setIntegrating(numpy.mean, [ch_input])

    def setAccumulating(self, ch_input: AbstractChannel) -> None:
        self.setIntegrating(numpy.sum, [ch_input])

    def getData(self, step_index: int = AbstractChannel.CURRENT_STEP
                ) -> numpy.ndarray:
        """Get channel data."""

        if not self.buffering:
            return None

        if step_index == AbstractChannel.CURRENT_STEP:
            step_index = self.current_index

        # TODO: We could optimize the data layout for non-CONTINUOUS
        # channels to use "less arrays" and not having to create new
        # ones in this method.
        if self.freq == AbstractChannel.CONTINUOUS_SAMPLES and step_index > -1:
            try:
                step = self.data[step_index]
            except IndexError:
                raise ValueError('step index out of range')

            step_len = len(step)

            if step_len == 0:
                return None
            elif step_len > 0:
                self.data[step_index] = self._compactData(step)
                step = self.data[step_index]

            return step[0]

        else:
            # Every frequency except CONTINUOUS_SAMPLES implies
            # step_index == ALL_STEPS

            buf = []

            i = 0
            for step in self.data:
                if len(step) > 0:
                    if self.freq == AbstractChannel.STEP_SAMPLES:
                        # No compacting necessary, we always take the last
                        # sample (i.e. the last performed scan).
                        buf.append(step[-1])
                    else:
                        new_step = self._compactData(step)
                        buf.append(new_step[0])

                        self.data[i] = new_step

                i += 1

            if len(buf) == 0:
                return None

            if self.freq == AbstractChannel.STEP_SAMPLES:
                return numpy.array(buf)
            else:
                return numpy.concatenate(buf)

    def setData(self, d: Any, step_index: int = AbstractChannel.CURRENT_STEP
                ) -> None:
        """Set channel data."""

        # Only necessary for scalar data
        if not isinstance(d, numpy.ndarray):
            d = numpy.array([d])

        if d is None or self.emptySet_func(d):
            self.clearData()
            return

        if step_index == AbstractChannel.CURRENT_STEP:
            step_index = self.current_index
        elif step_index >= len(self.data):
            raise ValueError('step index out of range')

        self.data[step_index] = [d]

        for s in self.subscribers:
            subscribed_index = s._channel_subscriber_step_index

            if (subscribed_index == AbstractChannel.CURRENT_STEP and
                    step_index == self.current_index):
                s.dataSet(d)
            elif subscribed_index == step_index:
                s.dataSet(d)
            elif subscribed_index == AbstractChannel.ALL_STEPS:
                s.dataSet(self.getData(AbstractChannel.ALL_STEPS))

    def addData(self, d: Any) -> None:
        """Add channel data."""

        if d is None or self.emptySet_func(d):
            return

        if self.buffering:
            self.data[self.current_index].append(d)

        for s in self.subscribers:
            step_index = s._channel_subscriber_step_index

            if step_index < 0 or step_index == self.current_index:
                s.dataAdded(d)

        try:
            fp = self.data_file_pointer
        except AttributeError:
            pass
        else:
            self._writeData(fp, d)

    def clearData(self) -> None:
        """Clear channel data."""

        self.data[self.current_index].clear()

        for s in self.subscribers:
            step_index = s._channel_subscriber_step_index

            if (step_index == AbstractChannel.CURRENT_STEP or
                    step_index == self.current_index):
                s.dataCleared()

    def isBuffering(self) -> bool:
        """Returns whether this channel is buffering.

        Returns:
            A boolean indicating the buffering state
        """

        return self.buffering

    def getRange(self) -> Tuple[float, float]:
        """Return the range of values of this channel.

        Returns:
            A tuple of floats in the form (min, max)
        """

        return self.range_min, self.range_max

    def setRange(self, new_min: float, new_max: float) -> None:
        """Set the range of values in this channel.

        Args:
            range_min: A float that is lower or equal than all other
                samples in this channel.
            range_max: A float that is greater or equal than all other
                samples in this channel.
        """

        self.range_min = new_min
        self.range_max = new_max

        self._notify('rangeChanged')


NumericChannel = StreamChannel  # previous name for compatibility


class DatagramChannel(AbstractChannel):
    def __init__(self, *names, **options) -> None:
        if 'compression' in options:
            self.compress_args = {
                'compression': 'gzip',
                'compression_opts': (4 if options['compression'] is True
                                     else int(options['compression']))
            }
        else:
            self.compress_args = {}

        try:
            self.transient = bool(options['transient'])
        except KeyError:
            self.transient = False

        self.image_idx = 0

        self.storage_base = None
        self.next_dset_name = None

        self.last_datum = None
        self.last_metadata = None

        super().__init__(*names, **options)

    def _addMetaData(self) -> None:
        attrs = self.h5file.attrs

        attrs['name'] = self.name
        attrs['freq'] = AbstractChannel.getFrequencyString(self.freq)
        attrs['hint'] = AbstractChannel.getHintString(self.hint)

        for tag, value in self.header_tags.items():
            attrs[tag] = value

        for key, value in self.display_arguments.items():
            attrs['DISPLAY ' + key] = value

    def openStorage(self, base_path: str) -> None:
        if self.transient:
            return

        self.storage_base = base_path

        if self.freq == AbstractChannel.STEP_SAMPLES:
            self.h5file = h5py.File('{0}_{1}.h5'.format(self.storage_base,
                                                        self.name), 'w')

    def closeStorage(self) -> None:
        if (self.storage_base is not None and
                self.freq == AbstractChannel.STEP_SAMPLES):
            self._addMetaData()
            self.h5file.close()
            del self.h5file

        self.storage_base = None

    def subscribe(self, obj: Subscriber, silent: bool = False) -> None:
        """Subscribe to this channel.

        Add a subscriber object to this channel that receives callbacks.

        Args:
            obj: The Subscriber object to be added
            silent: Optional boolean to indicate that no callbacks
                should be fired upon subscribing. This may include the
                added or cleared callback depending on the channel's
                data content.
        """

        super().subscribe(obj)

        if not silent:
            if self.last_datum is None:
                obj.dataCleared()
            else:
                obj.dataAdded(self.last_datum)

    def beginScan(self, scan_counter: int) -> None:
        super().beginScan(scan_counter)

        if self.storage_base is not None and \
                self.freq == AbstractChannel.STEP_SAMPLES:
            self.h5scan = self.h5file.create_group(str(scan_counter))

        self.step_idx = -1

    def beginStep(self, step_value: float) -> None:
        super().beginStep(step_value)

        self.step_idx += 1
        self.image_idx = 0

        if self.storage_base is not None:
            if self.freq == AbstractChannel.CONTINUOUS_SAMPLES:
                self.h5file = h5py.File(
                    '{0}_{1}_{2}.h5'.format(self.storage_base, self.name,
                                            self.step_idx), 'w'
                )

            elif self.freq == AbstractChannel.STEP_SAMPLES:
                self.next_dset_name = str(step_value)

    def endStep(self) -> None:
        if self.storage_base is not None:
            if self.freq == AbstractChannel.CONTINUOUS_SAMPLES:
                self._addMetaData()
                self.h5file.close()
                del self.h5file
            elif self.freq == AbstractChannel.STEP_SAMPLES:
                if self.last_datum is None:
                    return

                im_name = (self.next_dset_name
                           if self.next_dset_name is not None
                           else str(self.image_idx))

                im_dset = self.h5scan.create_dataset(
                    im_name, data=self.last_datum,
                    chunks=self.last_datum.shape,
                    **self.compress_args
                )

                self.last_datum = None

                if self.last_metadata is None:
                    return

                for key, value in self.last_metadata.items():
                    im_dset.attrs[key] = value

                self.last_metadata = None

    def reset(self) -> None:
        for s in self.subscribers:
            s.dataCleared()

    def getData(self, step_index: int = AbstractChannel.CURRENT_STEP
                ) -> numpy.ndarray:
        return self.last_datum

    def setData(self, d: Any) -> None:
        raise TypeError('setData not supported by DatagramChannel (yet!)')

    def addData(self, d: Any, **metadata: Any):
        if (self.storage_base is not None and
                self.freq == AbstractChannel.CONTINUOUS_SAMPLES):
            im_name = (self.next_dset_name
                       if self.next_dset_name is not None
                       else str(self.image_idx))

            im_dset = self.h5file.create_dataset(im_name, data=d,
                                                 chunks=d.shape,
                                                 **self.compress_args)

            for key, value in metadata.items():
                im_dset.attrs[key] = value

        for s in self.subscribers:
            step_index = s._channel_subscriber_step_index

            if step_index < 0 or step_index == self.current_index:
                s.dataAdded(d)

        self.last_datum = d
        self.last_metadata = metadata

        self.image_idx += 1


class LogChannel(AbstractChannel):
    OP_ADD_DATA = 0
    OP_OPEN_CHANNEL = 1
    OP_CLOSE_CHANNEL = 2
    OP_QUIT = 3

    storage_root = '.'
    ch_count = 0
    logger_p = None
    op_in = None
    compression_args = dict(compression='gzip', compression_opts=4)

    def __init__(self, *names,
                 interval: int = -1, fields: List[Tuple[str, str]] = [],
                 **options) -> None:
        if interval <= 0:
            raise ValueError('interval must be greater than zero')

        if fields is None:
            raise ValueError('no fields to log')

        options['static'] = True

        super().__init__(*names, **options)

        if LogChannel.ch_count == 0:
            op_out, op_in = multiprocessing.Pipe(False)

            LogChannel.logger_p = multiprocessing.Process(
                target=LogChannel.logger_main,
                args=(LogChannel.storage_root, op_out)
            )
            LogChannel.logger_p.start()

            LogChannel.op_in = op_in

        LogChannel.op_in.send((LogChannel.OP_OPEN_CHANNEL, self.name,
                               interval, fields))
        LogChannel.ch_count += 1

    def close(self) -> None:
        super().close()

        LogChannel.op_in.send((LogChannel.OP_CLOSE_CHANNEL, self.name))
        LogChannel.ch_count -= 1

        if LogChannel.ch_count == 0:
            LogChannel.op_in.send((LogChannel.OP_QUIT,))
            LogChannel.logger_p.join()

            LogChannel.logger_p = None
            LogChannel.op_in = None

    @staticmethod
    def logger_main(storage_root, pipe) -> None:
        # h5f, flush_size, dtype, empty_rec
        cur_channels = {}

        while pipe.poll(None):
            msg = pipe.recv()

            if msg[0] == LogChannel.OP_ADD_DATA:
                _, name, label, time, data = msg

                time = datetime.datetime.fromtimestamp(time)
                dset_name = '{0}/{1}'.format(label, time.strftime('%Y-%m-%d'))

                h5f, interval, dtype, empty_rec = cur_channels[name]
                h5d = None

                if dset_name in h5f:
                    h5d = h5f[dset_name]

                    if h5d.dtype != dtype:
                        # If we have a dtype mismatch, we rename the
                        # "wrong" dataset and create our own new one.

                        replacement_name = dset_name + '_DTYPE_MISMATCH'
                        i = 2

                        while replacement_name in h5f:
                            replacement_name = '{0}_DTYPE_MISMATCH{1}'.format(
                                dset_name, i
                            )
                            i += 1

                        h5f.create_dataset(replacement_name,
                                           dtype=h5d.dtype, data=h5d,
                                           **LogChannel.compression_args)
                        del h5f[dset_name]
                        h5d = None

                if h5d is None:
                    h5d = h5f.create_dataset(
                        dset_name, shape=(1,), maxshape=(None,),
                        chunks=(int(3600/interval),), dtype=dtype,
                        **LogChannel.compression_args)
                else:
                    h5d.resize(h5d.shape[0] + 1, axis=0)

                empty_rec[0][0] = time.strftime('%H%M%S').encode('ascii')
                for i in range(len(data)):
                    empty_rec[0][i+1] = data[i]

                h5d[-1] = empty_rec

                if (h5d.shape[0] % max(int(300 / interval), 1)) == 0:
                    h5f.flush()

            elif msg[0] == LogChannel.OP_OPEN_CHANNEL:
                _, channel_name, interval, fields = msg

                if channel_name in cur_channels:
                    continue

                fields.insert(0, ('time', 'S6'))
                dtype = numpy.dtype(fields, align=False)
                empty_rec = numpy.empty((1,), dtype)

                h5f = h5py.File('{0}/{1}.h5'.format(storage_root,
                                                    channel_name), 'a')

                cur_channels[channel_name] = (h5f, interval, dtype, empty_rec)

            elif msg[0] == LogChannel.OP_CLOSE_CHANNEL:
                channel_name = msg[1]

                if channel_name not in cur_channels:
                    continue

                cur_channels[channel_name][0].close()
                del cur_channels[channel_name]

            elif msg[0] == LogChannel.OP_QUIT:
                break

        for ch_entry in cur_channels.values():
            ch_entry[0].close()

        # Exit either after 60s passed without any message or we got an
        # explicit command for it

    def openStorage(self, base_path: str) -> None:
        raise NotImplementedError('non-static storage not supported by '
                                  'LogChannel')

    def closeStorage(self) -> None:
        raise NotImplementedError('non-static storage not supported by '
                                  'LogChannel')

    def setData(self, d: Any) -> None:
        raise NotImplementedError('setData not supported by LogChannel')

    def addData(self, *d, label: str = '', time: int = 0) -> None:
        if time == 0:
            time = time_now()

        LogChannel.op_in.send((LogChannel.OP_ADD_DATA, self.name, label,
                               time, d))

    def clearData(self) -> None:
        raise NotImplementedError('clearData not supported by LogChannel')


# For compatibility with older versions of Python on Windows (i.e. using
# the spawn multiprocessing method), which look for 'logger_main' in the
# module namespace
logger_main = LogChannel.logger_main

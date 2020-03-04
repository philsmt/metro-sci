
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# This module provides a flexible control mechanism for measurements. It
# is based on a central Measurement object, which can be customized by
# providing a set of operator objects each responsible for a single
# task.
#
# Please note that there are some important semantics about operators
# that should always be followed. Any assumptions that should never be
# made are explicitly stated.


import time
import threading
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple, Union

from PyQt5 import QtCore

QSlot = QtCore.pyqtSlot
QSignal = QtCore.pyqtSignal
QConnectable = Union[Callable, QSignal]


class Node(object):
    """Interface for measuring nodes.

    A node can participate in the measuring process by registering
    slots for the prepared, started, stopped and finalized signals.

    In the standard Metro frontend, devices act as measuring nodes.
    """

    def connectToMeasurement(self, prepared: QSignal, started: QSignal,
                             stopped: QSignal, finalized: QSignal) -> None:
        """Connect the measuring slots of this node.

        The Measurement object calls this method during its
        initialization phase with its respective signals for each of
        these slots.

        Args:
            prepared: A bound Qt signal that is emitted when the
                measuring process is prepared and about to begin.
            started: A bound Qt signal that is emitted on the begin of
                each measuring step.
            stopped: A bound Qt signal that is emitted on the end of
                each measuring step.
            finalized: A bound Qt signal that is emitted when the
                measuring process is finalized and about to end.
        """

        pass


class Channel(object):
    """Interface for measuring channels.

    A channel can participate in the measuring process by getting
    synchronous callbacks at scan and step boundaries as well as
    additional bookkeeping concerning logging and data storage.

    This class only contains the abstract interface required to
    inteface with the Measuring object. Usually a more complete
    implementation including a public interface from the channels module
    should be used.
    """

    def beginScan(self, scan_value: Any) -> None:
        """Begin a scan.

        The measuring controller calls this method at the begin of every
        scan iteration, so that a channel can properly prepare.

        Args:
            scan_value: A value describing this scan iteration of
                arbitrary type.
        """

        pass

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
        """

        pass

    def endScan(self) -> None:
        """End a scan.

        The measuring controller calls this method at the end of every
        scan iteration, so that a channel can perform cleanup work.
        """

        pass

    def openStorage(self, base_path: str) -> None:
        """Enter storage mode.

        In streaming mode, the channel should expect valid data to be
        generated that belongs to this measuring run.

        Args:
            base_path: A string that uniquely identifies this measuring
                run.
        """

        pass

    def closeStorage(self) -> None:
        """Leave streaming mode."""

        pass

    def addMarker(self, text: str) -> None:
        """Add a custom marker.

        Args;
            text: A string containing the marker to write.
        """

        pass

    def reset(self) -> None:
        """Reset the channel.

        This method is called once at the beginning of a measurement.
        """

        pass


class AbstractBlock(object):
    """Abstract multi-user block.

    This block uses refcount to enable multiple users to acquire it and
    release it in any order. It is considered not acquired if the
    reference count is exactly zero. It can be used to indicate whether
    a certain resource is still in use by anyone.

    The attributes of this class have to be implemented by the
    extending class.

    Attributes:
        lock: A sync.Lock() object used to synchronize access to
            the reference count.
        refcount: An integer holding the reference count. Must be
            initialized to zero.
        listener: An optional listener object with callbacks for when
            the block is acquired or released (see BlockListener) or
            None.
    """

    @classmethod
    def acquire(cls) -> None:
        """Acquire the block.

        This increases the reference count by one. If it was previously
        zero, the block is now considered acquired.
        """

        with cls.lock:
            cls.refcount += 1

            # Save the current refcount so we can release the lock
            # immediately and do not have to hold it during the
            # callback.
            l_refcount = cls.refcount

        # Do not use a try-catch here to safeguard against a None
        # listener to not catch any exception from the callback
        if cls.listener is not None and l_refcount == 1:
            cls.listener.blockAcquired()

    @classmethod
    def release(cls) -> None:
        """Release the block.

        This decreases the reference count by one. If it now zero, the
        block is now considered released.
        """

        with cls.lock:
            if cls.refcount > 0:
                cls.refcount -= 1

            # Save the current refcount so we can release the lock
            # immediately and do not have to hold it during the
            # callback.
            l_refcount = cls.refcount

        # Do not use a try-catch here to safeguard against a None
        # listener to not catch any exception from the callback
        if cls.listener is not None and l_refcount == 0:
            cls.listener.blockReleased()

    @classmethod
    def isAcquired(cls) -> None:
        """Check whether the block is acquired.

        The block is only considered acquired if the reference count is
        greater than zero.

        Returns:
            A boolean indicating whether the block is acquired.
        """

        with cls.lock:
            res = cls.refcount > 0

        return res


class BlockListener(object):
    """Interface for block listeners.

    A block listener provides callbacks for an AbstractBlock to be
    notified when it is acquired (from being in the releasted state)
    and released again (from being in the acquired state).
    """

    def blockAcquired(self) -> None:
        """Callback for when a block is acquired.

        This will only occur when the block was previously not held.
        """

        pass

    def blockReleased(self) -> None:
        """Callback for when a block is released."""

        pass


class RunBlock(AbstractBlock):
    """Block controlling the begin of a measuring process.

    An implementation of AbstractBlock to block the start of
    measurements. If used during a running measurement, it only prevents
    the button from being available again after the process finished.

    This is meant either for hardware initialization of nodes or to
    delay continuation of the measuring process after the prepared
    signal.
    """

    lock = threading.Lock()
    refcount = 0
    listener = None


class StepBlock(AbstractBlock):
    """Block controlling the end of a step.

    An implementation of AbstractBlock to block on the end of a step.
    This will cause the measuring process to wait after stopping and
    before ending the step/scan.

    This is meant to be used to ensure all data of any particular step
    has been received and written before any postprocessing is done or
    the next step started.
    """

    lock = threading.Lock()
    refcount = 0
    listener = None


class PointOperator(object):
    """Interface for point operators.

    A point operator provides a mechanism to select measurement points,
    which specify the actual values for the parameters being changed by
    the ScanOperator.
    """

    PrepareResult = Tuple[QConnectable, QSignal, QSignal,
                          Optional[Sequence[float]]]

    def preparePoints(self) -> PrepareResult:
        """Prepare a point selector.

        Returns:
            A tuple with the request_point slot, point_ready and
            point_depleted signal as well as an optional sequence of
            points if known at this time.
        """

        raise NotImplementedError('preparePoints')

    def finalizePoints(self):
        """Finalize a point selector.

        Called by the measuring controller after the last step is
        completed. The point operator can safely release any resources
        here it needed during the measurement itself.
        """

        pass


class ScanOperator(object):
    """Interface for scanning operators.

    A scanning operator provides a mechanism to perform a scan, that is
    varying a certain parameter over several steps in a measurement. For
    example, a tuneable radiation source might change the excitation
    energy for each step or a spectrometer changes the grating position.

    For this it has to provide a move_scan slot and a scan_ready signal.
    The move_scan slot is connected to a signal in the measuring
    controller and emitted when the next step is requested. The
    scan_ready signal in turn should be emitted by the scanning operator
    once the parameter requested for this step has been set up. By being
    connected to a slot in the measuring controller it will trigger the
    next step to start measuring.

    Every measurement uses a scanning operator. If no parameter is to be
    varied, the VirtualScan operator can be used that directly connects
    the measuring controller to the scan_ready signal.

    It is not guaranteed that an actual step follows after the ready
    signal is emitted! If the process has been aborted in the meantime,
    the signal will have been disconnected and be ignored. It is also
    possible that finalizeScan is called before. It is therefore HIGHLY
    recommended to not block on the main thread!

    Do not emit the signal returned by prepareScan for scan_ready before
    the corresponding finalizeScan call has occured without a call to
    the move_scan slot! The resulting behaviour is undefined, because
    the signal is connected to unknown operator code, but will usually
    cause the measuring process to desync. After the scan has been
    finalized, the signals are disconnected.
    """

    PrepareResult = Tuple[QConnectable, QSignal]

    def prepareScan(self) -> PrepareResult:
        """Prepare a scan.

        Called by the measuring controller upon initialization. Here the
        scanning operator should prepare to change the step parameter
        once the slot gets called.

        Returns:
            A tuple with the move_scan slot and scan_ready signal in the
            form of (move_scan, scan_ready)
        """

        raise NotImplementedError('prepareScan')

    def finalizeScan(self) -> None:
        """Finalize a scan.

        Called by the measuring controller after the last step is
        completed. The scanning operator can safely release any
        resources here it needed during the measurement itself.
        """

        pass


class TriggerOperator(object):
    """Interface for trigger operators.

    A trigger operator provides a mechanism to decide when to begin the
    actual measuring process for any given step. For example, a TTL
    pulse may be read out and used to trigger a step or any other remote
    signal.

    Analog to the scanning operator, a trigger operator has to provide a
    slot called arm_trigger as well as a signal called trigger_fired. As
    the names suggest, the arm_trigger slot is called when the scanning
    operator is ready and the measurement can begin at any time.
    Afterwards the trigger_fired signal can be emitted at the trigger
    operator's leisure.

    Every measurement uses a trigger operator. If no actual trigger is
    required, the ImmediateTrigger operator can be used that directly
    connects the measuring controller to the trigger_fired signal.

    It is not guaranteed that an actual step follows after the fired
    signal is emitted! If the process has been aborted in the meantime,
    the signal will have been disconnected and be ignored. It is also
    possible that finalizeTrigger is called before. It is therefore
    HIGHLY recommended to not block on the main thread!

    As with ScanOperator, do not emit the trigger_fired signal without
    a call arm_trigger.
    """

    PrepareResult = Tuple[QConnectable, QSignal]

    def prepareTrigger(self) -> PrepareResult:
        """Prepare a trigger.

        Called by the measuring controller upon initialization. Here the
        trigger operator should prepare to be armed in the future once
        the slot is called.

        Returns:
            A tuple with the arm_trigger slot and trigger_fired signal
            in the form of (arm_trigger, trigger_fired)
        """

        raise NotImplementedError('prepareTrigger')

    def finalizeTrigger(self) -> None:
        """Finalize a trigger.

        Called by the measuring controller after the last step is
        completed. The trigger operator can safely release any resources
        here it needed during the measurement itself.
        """

        pass


class LimitOperator(object):
    """Interface for limit operators.

    A limit operator provides a mechanism to decide when to stop the
    actual measuring process for any given step. For example, the
    simplest limit operator stops a step after a fixed amount of time
    or once a channel has reached an arbitrary number of counts. But it
    is also possible to operate on remote signals.

    Analog to the trigger operator, a limit operator has to provide a
    slot called start_limit as well a signal limit_reached. As names
    suggest, the start_limit slot is called when the actual measuring
    process begins (determined by the trigger operator) and the limit
    operator should begin with determining when to stop said process.
    For this, it emits the limit_reached signal.

    There is an additional and optional signal that a limit operator can
    provide in order to relay the current limit state to the status
    operator. It takes an int argument and is meant to be relative to
    the also optional integer limit_max. If no details about the limit
    are specified, these values should be None and 0 respectively.

    Every measurement uses a limit operator. As already mentioned, the
    most common limit operator is TimeLimit. Another provided one is
    ManualLimit, which has to be called from an outside source to stop
    measuring, for example clicking a button.

    The reached signal may be fired by the measuring controller itself!
    If the measuring process is aborted while the limit operator is in
    control, the controller will emit the reached signal by itself. It
    is also possible that finalizeLimit is called before. It is
    therefore HIGHLY recommended to not block on the main thread!

    As with ScanOperator, do not emit the limit_reached signal without
    a call to start_limit.
    """

    PrepareResult = Tuple[QConnectable, QSignal, Optional[QSignal], int]

    def prepareLimit(self) -> PrepareResult:
        """Prepare a limit.

        Called by the measuring controller upon initialization. Here the
        limit operator should prepare to be started in the future once
        the slot is called.

        Returns:
            A tuple with the start_limit slot, limit_reached signal as
            well as the optional limit_updated signal (may be None) and
            limit_max value (may be 0) in the form of
            (start_limit, limit_reached, limit_updated, limit_max).
        """

        raise NotImplementedError('prepareLimit')

    def finalizeLimit(self) -> None:
        """Finalize a limit.

        Called by the measuring controller after the last step is
        completed. The limit operator can safely release any resources
        here it needed during the measurement itself.
        """

        pass


class StatusOperator(object):
    """Interface for status operators.

    A status operator conveys the current status of the measurement
    process to the user. It is therefore a kind of callback interface
    for the frontend.
    """

    STANDBY = 0
    PREPARING = 1
    ENTERING_SCAN = 2
    ENTERING_STEP = 3
    CONFIGURING = 4
    TRIGGER_ARMED = 5
    RUNNING = 6
    LEAVING_STEP = 7
    LEAVING_SCAN = 8
    FINALIZING = 9
    PAUSED = 10

    PrepareResult = Tuple[QConnectable, QConnectable]

    def prepareStatus(self, max_limit: int) -> PrepareResult:
        """Prepare a status indicator.

        Called by the measuring controller upon initialization. Here the
        status operator should prepare to receive status updates.

        Args:
            max_limit: An integer describing the maximum limit that may
                occur.

        Returns:
            A tuple with the update_status and upate_limit slot in the
            form of (update_status, update_limit).
        """

        raise NotImplementedError('prepareStatus')

    def finalizeStatus(self) -> None:
        """Finalize a status indicator.

        Called by the measuring controller after the last step is
        completed and no further status updates will be emitted. The
        status operator can safely release any resources here it needed
        during the measurement itself.
        """

        pass


class ScansetProxy(QtCore.QObject, PointOperator, ScanOperator):
    """Proxy operator for multiple scansets.

    This class acts both as PointOperator and ScanOperator in order to
    allow measurements over multiple pairs of these operators, so called
    scansets. Each combination of points is visited exactly once by
    interleaved operator executions with the outer operator being
    executed the least and the inner operator the most. The order of
    operators is preserved from the iterable passed to this object.
    """

    class SignalHolder(QtCore.QObject):
        request = QtCore.pyqtSignal(int)
        move = QtCore.pyqtSignal(float)

    out_point_ready = QtCore.pyqtSignal(float)
    out_point_depleted = QtCore.pyqtSignal()
    out_scan_ready = QtCore.pyqtSignal()

    def __init__(self, operators: Iterable[Tuple[PointOperator,
                                                 ScanOperator]]):
        super().__init__()

        # List (actually iterable) of tuples with PointOperator and
        # ScanOperator respectively.
        self.operators = operators

        # List of SignalHolder objects connecting to the operator at the
        # same index as in self.operators.
        self.signals = []

        for i in range(len(self.operators)):
            self.signals.append(ScansetProxy.SignalHolder())

        # List of tuples with the return values (only the connectables)
        # of the operators at the same index as in self.operators.
        self.p_connectables = []
        self.s_connectables = []

        # List with one element per operator containing the step values
        # for the next step with None if the value for this operator
        # requires no change.
        self.point_set = [None] * len(self.operators)

        # The innermost operator that is currently modified. For the very
        # first step this obviously starts at 0 (the outermost operator).
        self.op_idx = 0

        # The global step index as given by the measurement controller.
        self.out_step_idx = 0

        # The respective step indices for each operators.
        self.in_step_idx = [0] * len(self.operators)

    def in_requestPoint(self) -> None:
        # Emit a point request for the currently innermost operator.
        self.signals[self.op_idx].request.emit(self.in_step_idx[self.op_idx])

    @QtCore.pyqtSlot(int)
    def out_point_request(self, step_index: int) -> None:
        # Slot called when the measurement controller requests the next
        # point. We reset the point set and call request on the currently
        # innermost operator.
        self.point_set[:] = [None] * len(self.operators)
        self.out_step_idx = step_index

        self.in_requestPoint()

    @QtCore.pyqtSlot(float)
    def in_point_ready(self, step_value: float) -> None:
        # Slot called when a point operator returns with a ready point.
        # Save it in the point set and increase this operator's step
        # index by one. If the current operator was the innermost, we can
        # emit the global ready signal. If not, we go one level deeper
        # and repeat.

        self.point_set[self.op_idx] = step_value
        self.in_step_idx[self.op_idx] += 1

        if self.op_idx == len(self.operators)-1:
            # We are ready!
            self.out_point_ready.emit(float(self.out_step_idx))
        else:
            # There are more operators to handle
            self.op_idx += 1
            self.in_requestPoint()

    @QtCore.pyqtSlot()
    def in_point_depleted(self) -> None:
        # Slot called when a point operator is depleted. Reset its step
        # index and either emit the global depleted signal if this
        # operator is the outermost or go one level higher and request
        # again.

        self.in_step_idx[self.op_idx] = 0

        if self.op_idx == 0:
            # All points are depleted
            self.out_point_depleted.emit()
        else:
            # Go one operator level down
            self.op_idx -= 1
            self.in_requestPoint()

    @QtCore.pyqtSlot(float)
    def out_scan_move(self, step_value: float) -> None:
        # Slot called when the measurement controller tells us to move
        # the scan. Count all scan operators that require a move (whose
        # entry in the point set is not None) and emit their respective
        # move signal.

        self.scan_ops_ready = 0
        self.scan_ops_moving = 0

        for point in self.point_set:
            if point is not None:
                self.scan_ops_moving += 1

        for op_idx in range(len(self.operators)):
            if self.point_set[op_idx] is not None:
                self.signals[op_idx].move.emit(self.point_set[op_idx])

    @QtCore.pyqtSlot()
    def in_scan_ready(self) -> None:
        # Slot called when a scan operator finished moving. Increase the
        # counter of ready operators by one and emit the global ready
        # signal when we got all.
        self.scan_ops_ready += 1

        if self.scan_ops_ready == self.scan_ops_moving:
            self.out_scan_ready.emit()

    def preparePoints(self) -> PointOperator.PrepareResult:
        n_points = 1

        for i in range(len(self.operators)):
            p_request, p_ready, p_depleted, points = \
                self.operators[i][0].preparePoints()

            self.signals[i].request.connect(p_request)
            p_ready.connect(self.in_point_ready)
            p_depleted.connect(self.in_point_depleted)

            self.p_connectables.append((p_request, p_ready, p_depleted))

            try:
                n_points *= len(points)
            except TypeError:
                n_points = -1

        return (self.out_point_request, self.out_point_ready,
                self.out_point_depleted,
                [float(x) for x in range(n_points)] if n_points > -1 else None)

    def finalizePoints(self) -> None:
        for i in range(len(self.operators)):
            p_request, p_ready, p_depleted = self.p_connectables[i]

            self.signals[i].request.disconnect(p_request)
            p_ready.disconnect(self.in_point_ready)
            p_depleted.disconnect(self.in_point_depleted)

        self.p_connectables.clear()

    def prepareScan(self) -> ScanOperator.PrepareResult:
        for i in range(len(self.operators)):
            s_move, s_ready = self.operators[i][1].prepareScan()

            self.signals[i].move.connect(s_move)
            s_ready.connect(self.in_scan_ready)

            self.s_connectables.append((s_move, s_ready))

        return self.out_scan_move, self.out_scan_ready

    def finalizeScan(self) -> None:
        for i in range(len(self.operators)):
            s_move, s_ready = self.s_connectables[i]

            self.signals[i].move.disconnect(s_move)
            s_ready.disconnect(self.in_scan_ready)

        self.s_connectables.clear()


class FixedPoints(QtCore.QObject, PointOperator):
    """Fixed point operator.

    This point operator emits each step a point from a predefined
    sequence in order.
    """

    pointReady = QtCore.pyqtSignal(float)
    pointDepleted = QtCore.pyqtSignal()

    def __init__(self, points: Sequence[float]):
        super().__init__()

        self.points = points

    def preparePoints(self) -> PointOperator.PrepareResult:
        return self.request, self.pointReady, self.pointDepleted, self.points

    @QtCore.pyqtSlot(int)
    def request(self, step_index: int) -> None:
        try:
            step_value = self.points[step_index]
        except IndexError:
            self.pointDepleted.emit()
        else:
            self.pointReady.emit(step_value)


class InfinitePoints(QtCore.QObject, PointOperator):
    """Infinite point operator.

    This point operator always emits the step index as a new point and
    will therefore never run out of points.
    """

    ready = QtCore.pyqtSignal(float)
    depleted = QtCore.pyqtSignal()

    def __init__(self) -> None:
        super().__init__()

    def preparePoints(self) -> PointOperator.PrepareResult:
        return self.request, self.ready, self.depleted, None

    @QtCore.pyqtSlot(int)
    def request(self, step_index: int) -> None:
        self.ready.emit(float(step_index))


class ExtendablePoints(QtCore.QObject, PointOperator):
    """Extendable point operator.

    This point operator simply emits the step index as new point and can
    be extended at runtime to any number of steps. If used as the point
    operator, the measurement operator will automatically extend it when
    the limit is skipped.
    """

    ready = QtCore.pyqtSignal(float)
    depleted = QtCore.pyqtSignal()

    def __init__(self) -> None:
        super().__init__()

        self.n_steps = 1
        self.cur_step = 0

    def preparePoints(self) -> PointOperator.PrepareResult:
        return self.request, self.ready, self.depleted, None

    @QtCore.pyqtSlot(int)
    def request(self, step_index: int) -> None:
        if self.cur_step == self.n_steps:
            self.depleted.emit()
        else:
            self.ready.emit(float(step_index))

        self.cur_step += 1

    def addStep(self):
        self.n_steps += 1


class VirtualScan(QtCore.QObject, ScanOperator):
    """Virtual scan operator.

    This scan operator does not actually perform any action, but simply
    connects the move_scan slot to the scan_ready signal.
    """

    ready = QtCore.pyqtSignal()

    def prepareScan(self) -> ScanOperator.PrepareResult:
        return self.ready, self.ready


class DelayedScan(QtCore.QTimer, ScanOperator):
    """Delayed scan operator.

    This scan operator simply waits for a fixed delay and then signals
    its readiness. It is mostly meant for debugging purposes.
    """

    def __init__(self, delay: int) -> None:
        super().__init__()

        self.setSingleShot(True)
        self.setInterval(delay)

    def prepareScan(self) -> ScanOperator.PrepareResult:
        return self.start, self.timeout


class ImmediateTrigger(QtCore.QObject, TriggerOperator):
    """Immediate trigger operator.

    This trigger operator does not actually perform any action, but
    simply connects the arm_trigger slot to the trigger_fired signal.
    """

    fired = QtCore.pyqtSignal()

    def prepareTrigger(self) -> TriggerOperator.PrepareResult:
        return self.fired, self.fired


class DelayedTrigger(QtCore.QTimer, TriggerOperator):
    """Delayed trigger operator.

    This trigger operator simply fires after a fixed delay after being
    armed. It is mostly meant for debugging purposes.
    """

    def __init__(self, delay: int) -> None:
        super().__init__()

        self.setSingleShot(True)
        self.setInterval(delay)

    def prepareTrigger(self) -> TriggerOperator.PrepareResult:
        return self.start, self.timeout


class ManualLimit(QtCore.QObject, LimitOperator):
    """Manual limit operator.

    This limit operator is controlled manually, that is it reaches its
    limit by either calling emitReached() or emitting a signal connected
    to its reached signal.
    """

    reached = QtCore.pyqtSignal()

    @QtCore.pyqtSlot()
    def start(self) -> None:
        pass

    def prepareLimit(self) -> LimitOperator.PrepareResult:
        return self.start, self.reached, None, 0


class TimeLimit(QtCore.QObject, LimitOperator):
    """Time limit operator.

    This limit operator uses a QTimer to reach its limit after a fixed
    amount of time has passed.
    """

    reached = QtCore.pyqtSignal()
    updated = QtCore.pyqtSignal(int)

    def __init__(self, time: int) -> None:
        super().__init__()

        self.limit = time
        self.start_time = 0

        self.timer = QtCore.QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.reached.connect(self.timer.stop)

    @QtCore.pyqtSlot()
    def start(self) -> None:
        self.start_time = time.monotonic()

        self.timer.start()

    @QtCore.pyqtSlot()
    def tick(self) -> None:
        elapsed = int(round(time.monotonic() - self.start_time, 0))

        self.updated.emit(elapsed)

        if elapsed >= self.limit:
            self.reached.emit()

    def prepareLimit(self) -> LimitOperator.PrepareResult:
        return self.start, self.reached, self.updated, self.limit


class CountLimit(QtCore.QObject, LimitOperator):
    """Count limit operator.

    This limit operator reaches its limit once a channel has emitted a
    fixed amount of rows.
    """

    reached = QtCore.pyqtSignal()
    updated = QtCore.pyqtSignal(int)

    def __init__(self, channel: Channel, limit: int) -> None:
        """Create a new CountLimit object.

        The channel required by this Operator conforms to the more
        complete interface defined by the channels module! To avoid
        introducing a dependency just for type checking, the simpler
        interface defined in this module is checked.

        Args:
            channel: The channel object for the channel to track.
            limit: An int specifying the limit in rows.
        """

        super().__init__()

        self.channel = channel
        self.limit = limit
        self.counter_func = self.channel.counter_func
        self.current_counts = 0
        self.reported_counts = 0

        self.update_timer = QtCore.QTimer()
        self.update_timer.setInterval(1000)
        self.update_timer.timeout.connect(self.updateTick)
        self.reached.connect(self.timer.stop)

    # Method for Subscriber interface to get channel count
    def dataSet(self, d: Any) -> None:
        pass

    # Method for Subscriber interface to get channel count
    def dataAdded(self, d: Any) -> None:
        self.current_counts += self.counter_func(d)

        if self.current_counts >= self.limit_counts:
            self.updated.emit(self.current_counts)

            self.current_counts = 0
            self.reached.emit()

    # Method for Subscriber interface to get channel count
    def dataCleared(self) -> None:
        self.current_counts = 0

    @QtCore.pyqtSlot()
    def start(self) -> None:
        self.current_counts = 0

        self.timer.start()

    @QtCore.pyqtSlot()
    def updateTick(self) -> None:
        if self.current_counts != self.reported_counts:
            self.updated.emit(self.current_counts)
            self.reported_counts = self.current_counts

    def prepareLimit(self) -> LimitOperator.PrepareResult:
        # Oho... this could us into deep threading issues. You should
        # only subscribe to a channel in the main thread!
        self.channel.subscribe(self)

        return self.start, self.reached, self.updated, self.limit

    def finalizeLimit(self) -> None:
        self.channel.unsubscribe(self)


class HiddenStatus(StatusOperator):
    """Hidden status operator.

    This status operator does not actually display anything, but just
    defines the abstract methods using stubs.
    """

    def prepareStatus(self, max_limit: int) -> StatusOperator.PrepareResult:
        return self.stub, self.stub

    def finalizeStatus(self) -> None:
        pass

    def stub(self) -> None:
        pass


class Measurement(QtCore.QObject):
    """Measuring Controller.

    An object of this class controls a single measuring process from
    start to end. For this, it is first configured with the specific
    parameters as well as a series of customizable objects called
    operators that control single aspects in the measuring process
    and then started.

    It will control the process until it is finished. Afterwards, it
    is not meant to be used again! The next measurement has to create
    a new Measurement object.

    The operators types ares:

    PointOperator       Chooses the experiment parameters
    ScanOperator        Controls the experiment parameters
    TriggerOperator     Decides when to begin a single measuring step
    LimitOperator       Decides when to stop a single measuring step
    StatusOperator      Reports the current status

    One of each operator is required for a measurement.
    """

    statusUpdated = QtCore.pyqtSignal(int)

    prepared = QtCore.pyqtSignal()
    chooseStep = QtCore.pyqtSignal(int)
    configureStep = QtCore.pyqtSignal(float)
    runStep = QtCore.pyqtSignal()
    stopStep = QtCore.pyqtSignal()
    finalized = QtCore.pyqtSignal()

    def __init__(self, nodes: Iterable[Node], channels: Iterable[Channel],
                 pointOp: PointOperator, scanOp: ScanOperator,
                 triggerOp: TriggerOperator, limitOp: LimitOperator,
                 statusOp: StatusOperator, scan_count: int,
                 storage_base: Optional[str] = None) -> None:
        """Initialize the measurement object.

        After initialization, all the objects are in place, but no
        actual signal/slot connections have been made.

        Args:
            nodes: An iterable containing the Node objects that are
                connected to this measuring controller.
            pointOp: The point operator object.
            scanOp: The scanning operator object.
            triggerOp: The trigger operator object.
            limitOp: The limit operator object.
            statusOp: The status operator object.
            scan_count: An integer with the number of iterations for
                the complete measurement.
            storage_base: Optional string giving the root directory to
                stream the channel data to
        """

        super().__init__()

        self.nodes = nodes
        self.channels = channels
        self.scan_count = scan_count
        self.storage_base = storage_base

        self.pointOp = pointOp
        self.scanOp = scanOp
        self.triggerOp = triggerOp
        self.limitOp = limitOp
        self.statusOp = statusOp

        self.status = StatusOperator.STANDBY

        # Will get increased to 0 by first scan/step
        self.current_step = -1
        self.current_scan = -1

        self.pausing = False
        self.aborting = False
        self.abort_on_next_status = False

        self.generated_points = []
        self.fixed_points = None

        # Set up our timer for syncronization.
        # These timer are used after each respective signal to allow
        # nodes to block the measuring pipeline. They start 500ms
        # after the signal and then check each time if a StepBlock is
        # acquired.
        self.waitAfterPrepared_timer = QtCore.QTimer(self)
        self.waitAfterPrepared_timer.setInterval(500)
        self.waitAfterPrepared_timer.timeout.connect(self.afterPrepared)

        self.waitAfterStopped_timer = QtCore.QTimer(self)
        self.waitAfterStopped_timer.setInterval(500)
        self.waitAfterStopped_timer.timeout.connect(self.afterStopped)

        self.waitAfterFinalized_timer = QtCore.QTimer(self)
        self.waitAfterFinalized_timer.setInterval(500)
        self.waitAfterFinalized_timer.timeout.connect(self.afterFinalized)

    # PUBLIC API
    def run(self) -> None:
        """Begin the measurement process.

        This begins the sequence as illustrated. After connecting all
        the necessary signals and slots, the channels are prepared and
        finally the prepared signal is emitted, yielding control to the
        asynchronous signals and slots.

        Args:
            prepared: Slot to connect to the prepared signal
            started: Slot to connect to the started signal
            stopped: Slot to connect to the stopped signal
            finalized: Slot to connect to the finalized signal

        Raises:
            RuntimeError: Run block is acquired.
        """

        # We get a RunBlock ourselves so no frontend can initiate two
        # measuring proccesses at the same time.
        if RunBlock.isAcquired():
            raise RuntimeError('run block is acquired')

        RunBlock.acquire()

        # Prepare all operators
        request_point, point_ready, point_depleted, fixed_points = \
            self.pointOp.preparePoints()
        move_scan, scan_ready = self.scanOp.prepareScan()
        arm_trigger, trigger_fired = self.triggerOp.prepareTrigger()
        start_limit, limit_reached, limit_updated, limit_max = \
            self.limitOp.prepareLimit()
        update_status, update_limit = self.statusOp.prepareStatus(limit_max)

        if fixed_points is not None:
            self.fixed_points = fixed_points

        # Wire their signals/slots as well as our own slots.
        # Note that for some connections the proper order does matter to
        # ensure getting the calls in the right order - if we make the
        # connections for the StatusOperator later on, we might get the
        # trigger_fired signal before scan_ready!
        self.statusUpdated.connect(update_status)
        self._setStatus(StatusOperator.PREPARING)

        self.chooseStep.connect(request_point)
        point_ready.connect(self.on_pointReady)
        point_depleted.connect(self.on_pointDepleted)

        self.configureStep.connect(move_scan)
        scan_ready.connect(self.on_scanReady)  # Has to come first!
        scan_ready.connect(arm_trigger)

        # The runStep signal acts as a buffer between trigger_fired and
        # start_limit / the node slots to allow disconnecting in case
        # of aborting.
        trigger_fired.connect(self.runStep)
        self.runStep.connect(self.on_triggerFired)  # Has to come first!
        self.runStep.connect(start_limit)

        limit_reached.connect(self.on_limitReached)
        limit_reached.connect(self.stopStep)

        if limit_updated is not None:
            limit_updated.connect(update_limit)

        # Next wire the nodes
        for node in self.nodes:
            node.connectToMeasurement(self.prepared, self.runStep,
                                      self.stopStep, self.finalized)

        # And finally wire our timer for syncronization
        self.prepared.connect(self.waitAfterPrepared_timer.start)
        self.stopStep.connect(self.waitAfterStopped_timer.start)
        self.finalized.connect(self.waitAfterFinalized_timer.start)

        self.pointReady = point_ready
        self.pointDepleted = point_depleted
        self.moveScan = move_scan
        self.scanReady = scan_ready
        self.armTrigger = arm_trigger
        self.triggerFired = trigger_fired
        self.limitReached = limit_reached
        self.limitUpdated = limit_updated
        self.updateLimit = update_limit

        # Reset all channels prior to a measurement
        for c in self.channels:
            c.reset()

        # Tell all channels if streaming is enabled
        if self.storage_base is not None:
            for c in self.channels:
                c.openStorage(self.storage_base)

        # And there we go!
        self.prepared.emit()

    def setPauseFlag(self, flag: bool) -> None:
        """Set the pause flag.

        When the pause flag is True at the begin of a new step, the
        measurement is paused instead until resume() is called.

        Arguments:
            flag: A boolean specifying the new flag value.
        """

        self.pausing = flag

    def resume(self) -> None:
        """Resume the measurement when paused.

        This method should only be called when the measurement has
        actually been paused. The behaviour is undefined in any other
        case.
        """

        if not self.pausing:
            raise ValueError('pause flag is false')

        self.pausing = False

        self._addChannelMarker('RESUMED')

        self.beginStep()

    def skipLimit(self) -> None:
        """Skip the limit operator once.

        This causes the emission of the limit operator's reached signal
        even without actually reaching the limit. It most often used in
        conjunction with the ExtendablePoints operator to add another
        step dynamically (which is a special case handled here!).

        The same note as for abort() applies regarding the stabilty of
        this call.
        """

        # BUG: will do strange things when called during armed trigger!

        if isinstance(self.pointOp, ExtendablePoints):
            # Special case to allow new steps to be added only when
            # skipping a limit.
            self.pointOp.addStep()

        self._addChannelMarker('SKIPPED')

        self.limitReached.emit()

    @QtCore.pyqtSlot()
    def abort(self) -> None:
        """Aborts the measurement process.

        This stop the measurement as quickly as possible without
        performing any further step. The exact action depends on the
        status the measurement is in when this method is called. This
        shutdown will always be graceful while preserving the semantics
        of all measuring signals.

        The operators in use have to be properly designed to not make
        assumptions about certain signal sequences! Please observe the
        respective comments.
        """

        if self.status == StatusOperator.STANDBY:
            # doh!

            return

        elif self.status == StatusOperator.PREPARING:
            # Here we wait for all interested parties to finish
            # preparing... just to immediately finalize when this flag
            # is set.
            self.aborting = True

        elif self.status == StatusOperator.ENTERING_SCAN:
            # This case is very rare since this status directly migrates
            # synchronously into ENTERING_STEP and exists for symmetry.
            # It is a tricky situation to abort in this state, so we set
            # a special flag to retry this on the next status.

            self.abort_on_next_status = True

        elif self.status == StatusOperator.ENTERING_STEP:
            # The point operator did not emit its ready signal yet, but
            # we actually do not know yet whether the step will happen
            # at all. We cut the connections and then directly end the
            # scan (not the step!).

            self.pointReady.disconnect(self.on_pointReady)
            self.pointDepleted.disconnect(self.on_pointDepleted)
            self.endScan()

        elif self.status == StatusOperator.CONFIGURING:
            # Here the scan device is currently moving to our desired
            # parameter. We cut the connection to us and the trigger,
            # set the abort flag and then proceed to end the step.

            self.scanReady.disconnect(self.on_scanReady)
            self.scanReady.disconnect(self.armTrigger)
            self.aborting = True
            self.endStep()

        elif self.status == StatusOperator.TRIGGER_ARMED:
            # We disconnect the fired signal from the actual trigger and
            # exit the process similar to ENTERING_STEP

            self.triggerFired.disconnect(self.runStep)
            self.aborting = True
            self.endStep()

        elif self.status == StatusOperator.RUNNING:
            # This is while we are actually measuring. We set the abort
            # flag and the skip the current limit to shortcut the step.
            # We may not directly call endStep() to ensure the blocking
            # semantics are preserved properly.

            self.aborting = True
            self.skipLimit()

        elif self.status == StatusOperator.LEAVING_STEP:
            # Here we wait for the step block to be released. We simply
            # set the abort flag.

            self.aborting = True

        elif self.status == StatusOperator.LEAVING_SCAN:
            # As with ENTERING_SCAN, this is a tricky situation, even
            # more since we might be in the middle of the measurement
            # run or at the very end. Again we postpone the abort.

            self.abort_on_next_status = True

        elif self.status == StatusOperator.FINALIZING:
            # What the hell do you want to abort?!

            pass

        elif self.status == StatusOperator.PAUSED:
            # We can directly go to finalize, since we are currently in
            # between steps.

            self.finalized.emit()

        self._addChannelMarker('ABORTED')

    def getScanCount(self) -> None:
        """Get the amount of scans to perform.

        Returns:
            An integer describing the amount of scans.
        """

        return self.scan_count

    def getPoints(self) -> Sequence[float]:
        """Get the list of measurement points.

        Returns:
            A sequence containing the step points. Depending on the
            point operator used and which scan iteration has been
            completed, this sequence may contain none or all points to
            be used. Do not modify this sequence, but create a copy
            instead!
        """

        return (self.generated_points
                if self.fixed_points is None
                else self.fixed_points)

    # PRIVATE API
    def _setStatus(self, new_status: int) -> None:
        self.status = new_status
        self.statusUpdated.emit(new_status)

        if self.abort_on_next_status:
            self.abort()

    def _addChannelMarker(self, text: str) -> None:
        if self.storage_base is not None:
            for c in self.channels:
                c.addMarker('{0} - {1}'.format(
                    time.strftime('%d.%m.%Y %H:%M:%S'), text
                ))

    @QtCore.pyqtSlot()
    def afterPrepared(self) -> None:
        if StepBlock.isAcquired():
            return

        self.waitAfterPrepared_timer.stop()

        if self.aborting:
            self.finalized.emit()
        else:
            self.beginScan()

    def beginScan(self) -> None:
        self.current_scan += 1
        self.current_step = -1

        for c in self.channels:
            c.beginScan(self.current_scan)

        self._setStatus(StatusOperator.ENTERING_SCAN)

        self.beginStep()

    def beginStep(self) -> None:
        self._setStatus(StatusOperator.ENTERING_STEP)

        if self.pausing:
            self._addChannelMarker('PAUSED')
            self._setStatus(StatusOperator.PAUSED)

            return

        self.current_step += 1

        self.chooseStep.emit(self.current_step)

    @QtCore.pyqtSlot(float)
    def on_pointReady(self, step_value: float) -> None:
        if self.aborting:
            self.endScan()
            return

        self.generated_points.append(step_value)

        for c in self.channels:
            c.beginStep(step_value)

        self._setStatus(StatusOperator.CONFIGURING)

        self.configureStep.emit(step_value)

    @QtCore.pyqtSlot()
    def on_pointDepleted(self) -> None:
        self.endScan()

    @QtCore.pyqtSlot()
    def on_scanReady(self) -> None:
        self._setStatus(StatusOperator.TRIGGER_ARMED)

    @QtCore.pyqtSlot()
    def on_triggerFired(self) -> None:
        self._setStatus(StatusOperator.RUNNING)

    @QtCore.pyqtSlot()
    def on_limitReached(self) -> None:
        self._setStatus(StatusOperator.LEAVING_STEP)

    @QtCore.pyqtSlot()
    def afterStopped(self) -> None:
        if StepBlock.isAcquired():
            return

        self.waitAfterStopped_timer.stop()

        self.endStep()

    def endStep(self) -> None:
        for c in self.channels:
            c.endStep()

        if self.aborting:
            self.endScan()
            return

        self.beginStep()

    def endScan(self) -> None:
        for c in self.channels:
            c.endScan()

        self._setStatus(StatusOperator.LEAVING_SCAN)

        if self.current_scan+1 >= self.scan_count or self.aborting:
            self._setStatus(StatusOperator.FINALIZING)

            self.finalized.emit()
        else:
            self.beginScan()

    @QtCore.pyqtSlot()
    def afterFinalized(self) -> None:
        if StepBlock.isAcquired():
            return

        self.waitAfterFinalized_timer.stop()

        # Disconnect the operator from external signals
        try:
            self.pointReady.disconnect(self.on_pointReady)
            self.pointDepleted.disconnect(self.on_pointDepleted)
        except TypeError:
            # May fail when aborting
            pass

        try:
            self.scanReady.disconnect(self.on_scanReady)
            self.scanReady.disconnect(self.armTrigger)
        except TypeError:
            # May fail when aborting
            pass

        try:
            self.triggerFired.disconnect(self.runStep)
        except TypeError:
            # May fail when aborting
            pass

        self.limitReached.disconnect(self.on_limitReached)
        self.limitReached.disconnect(self.stopStep)

        if self.limitUpdated is not None:
            self.limitUpdated.connect(self.updateLimit)

        self.pointOp.finalizePoints()
        self.scanOp.finalizeScan()
        self.triggerOp.finalizeTrigger()
        self.limitOp.finalizeLimit()

        if self.storage_base is not None:
            for c in self.channels:
                c.closeStorage()

        # postprocessing

        self._setStatus(StatusOperator.STANDBY)
        self.statusOp.finalizeStatus()

        RunBlock.release()

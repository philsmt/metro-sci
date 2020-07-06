
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# High-speed parallel operator.
#
# This device template allows offloading code to a different interpreter
# process to circumvent the GIL and implements the infrastructure to
# achieve this with minimal code.
#
# It moves an object called 'operator' to a separate process and a Qt
# thread in the main process to send commands and receive data via pipes
# from the operator. After an optional prefiltering stage in the agent
# the data is sent via Qt signals to the main thread. It is possible to
# use a separate process for each operator as well as pool operators on
# the same process by targeting an existing process.


import ctypes
import collections
import multiprocessing
import threading
import traceback

import metro
metro.init_mp_support()


_targets = {}
Target = collections.namedtuple('Target', ['name', 'process', 'active',
                                           'pipe'])


def operator_main(active, ctrl_pipe, data_pipe, operator, args):
    try:
        operator.prepare(args)
    except Exception as e:
        ctrl_pipe.send((str(e), traceback.format_exc()))
        ctrl_pipe.close()

        return
    else:
        # Send the flag the operator is ready
        ctrl_pipe.send(True)

    # Wait for next command from device (or more precisely the agent
    # thread). True starts/continues measuring while any other value
    # quits the process. Basically the process is spending its time
    # here waiting in this loop to either start measuring or break out
    # and exit
    reply = ctrl_pipe.recv()

    while reply is not False:
        if reply is True:
            operator.run(active, data_pipe)

            # The process is done measuring and sent all data,
            # signal the receiver thread to stop listening
            data_pipe.send(False)
        else:
            operator.custom(reply)

        reply = ctrl_pipe.recv()

    operator.finalize()

    ctrl_pipe.close()

    # Do not close data_pipe, since it is either identical to ctrl_pipe
    # or supplied by the user


def target_main(active, pipe):
    available_ids = list(reversed(range(len(active))))
    operators = {}

    while True:
        msg = pipe.recv()

        if msg is False:
            break
        elif isinstance(msg, int):
            if msg not in operators:
                pipe.send(None)
                continue

            operators[msg].join()

            del operators[msg]
            available_ids.append(msg)

            pipe.send(len(operators) > 0)
        else:
            if len(available_ids) == 0:
                pipe.send(None)
                continue

            new_id = available_ids.pop()

            op_thread = threading.Thread(target=operator_main,
                                         args=(active[new_id], msg[0],
                                               msg[1], msg[2], msg[3]))
            operators[new_id] = op_thread

            op_thread.start()

            pipe.send(new_id)

    for op_thread in operators.values():
        op_thread.join()

    pipe.close()


class Operator(object):
    def prepare(self, args):
        pass

    def finalize(self):
        pass

    def run(self, active, pipe):
        pass

    def custom(self, data):
        pass


class Agent(metro.QObject):
    operatorReady = metro.QSignal()
    # emitted when the operator is ready to measure

    operatorException = metro.QSignal(str, str)
    # emitted when the operator threw an exception

    newData = metro.QSignal(object)
    # emitted when there is new data

    stepDone = metro.QSignal()
    # emitted when all data was read in this step

    def __init__(self, ctrl_pipe, data_pipe, pre_filter):
        super().__init__()

        self.ctrl_pipe = ctrl_pipe
        self.data_pipe = data_pipe
        self.pre_filter = pre_filter

    # Called by thread.started signal
    @metro.QSlot()
    def waitForOperatorReady(self):
        reply = self.ctrl_pipe.recv()

        if reply is True:
            self.operatorReady.emit()

        else:
            self.operatorException.emit(reply[0], reply[1])

    # Called by measuring start
    @metro.QSlot()
    def listen(self):
        ctrl_pipe = self.ctrl_pipe
        data_pipe = self.data_pipe
        pre_filter = self.pre_filter

        ctrl_pipe.send(True)

        # The loop breaks when the process signals it stopped measuring
        # and send False over the pipe - this in turn is controlled by
        # the device with the shared variable
        while True:
            d = data_pipe.recv()

            if d is False:
                break

            d = pre_filter(d)

            if d is not None:
                self.newData.emit(d)

        self.stepDone.emit()


class Device(metro.WidgetDevice):
    def prepare(self, operator_cls, operator_args, newData, state,
                prefilter=lambda d: d, target=None, target_cap=5,
                data_pipes=None):

        local_ctrl_pipe, remote_ctrl_pipe = multiprocessing.Pipe(True)

        if data_pipes is not None:
            data_out_pipe, data_in_pipe = data_pipes
        else:
            # If no explicit data pipes are supplied, use our control
            # pipes for the this purpose as well
            data_out_pipe, data_in_pipe = local_ctrl_pipe, remote_ctrl_pipe

        self.ctrl_pipe = local_ctrl_pipe

        if operator_args is None:
            operator_args = {}

        if target is None:
            # This inter-process variable (using shared memory) is used
            # to synchronize the external process during measuring
            self.measuring_active = multiprocessing.Value(ctypes.c_bool, False)

            # Create and start the operator process
            self.process = multiprocessing.Process(
                target=operator_main,
                args=(self.measuring_active, remote_ctrl_pipe, data_in_pipe,
                      operator_cls(), operator_args)
            )

            # Start the process already while we initialise the agent
            self.process.start()

            self.target = None
        else:
            if target not in _targets:
                # Create the target process if it does not exist yet

                device_pipe, target_pipe = multiprocessing.Pipe(True)

                # We need to create the shared variables up front since
                # they have to be passed on creation time of the hosting
                # process.
                sync_active = []
                for i in range(target_cap):
                    sync_active.append(multiprocessing.Value(ctypes.c_bool,
                                                             False))

                target_process = multiprocessing.Process(
                    target=target_main,
                    args=(sync_active, target_pipe)
                )
                target_process.start()

                _targets[target] = Target(target, target_process, sync_active,
                                          device_pipe)

            self.target = _targets[target]
            self.target.pipe.send((remote_ctrl_pipe, data_in_pipe,
                                   operator_cls(), operator_args))

            res = self.target.pipe.recv()

            if res is not None:
                self.operator_id = res
                self.measuring_active = self.target.active[res]
            else:
                raise RuntimeError('target could not create operator')

        # Create the agent object, move it to a separate thread and
        # connect all signals. It first waits for the measuring process
        # to be ready and then until a measuring starts
        self.agent = Agent(local_ctrl_pipe, data_out_pipe, prefilter)

        self.thread = metro.QThread(self)
        self.agent.moveToThread(self.thread)

        self.agent.operatorReady.connect(self.operatorReady)
        self.agent.operatorException.connect(self.operatorException)
        self.agent.newData.connect(newData)
        self.agent.stepDone.connect(self.stepDone)
        self.thread.started.connect(self.agent.waitForOperatorReady)

        self.thread.start(metro.QThread.LowPriority)

        # Block measuring until the operator is ready
        metro.RunBlock.acquire()

        # The device itself also needs measuring slots to timely change
        # the shared synchronization variable since the agent thread is
        # blocking on the pipe
        self.measure_connect(started=self.measuringStarted,
                             stopped=self.measuringStopped)
        self.measure_connect(self.agent.listen)

    def finalize(self):
        # If we are still measuring, stop first!
        if self.measuring_active.value:
            self.measuring_active.value = False

        # Signal the thread to shutdown and block until completed
        self.thread.quit()
        self.thread.wait()

        # Send the operator process the signal to quit and wait for it
        self.ctrl_pipe.send(False)

        if self.target is None:
            self.process.join()
            self.process = None
        else:
            self.target.pipe.send(self.operator_id)

            res = self.target.pipe.recv()

            if res is True:
                pass
            elif res is False:
                self.target.pipe.send(False)

                self.target.process.join()
                self.target.pipe.close()

                del _targets[self.target.name]

                self.target = None
            else:
                print('target could not find my operator id')

        self.ctrl_pipe.close()
        self.ctrl_pipe = None

    def sendCustomData(self, data):
        if data is True or data is False:
            raise ValueError('custom data may not be True or False')

        # The behaviour of this method is not defined if called when
        # the operator is currently running!

        self.ctrl_pipe.send(data)

    @metro.QSlot()
    def measuringStarted(self):
        self.measuring_active.value = True

        metro.StepBlock.acquire()

    @metro.QSlot()
    def measuringStopped(self):
        self.measuring_active.value = False

        # The step block from measuringStarted is still locked until
        # after stepDone is called

    @metro.QSlot()
    def operatorReady(self):
        metro.RunBlock.release()

    @metro.QSlot(str, str)
    def operatorException(self, message, tb):
        metro.RunBlock.release()

        self.showError(message, details=tb)

        self.kill()

    @metro.QSlot()
    def stepDone(self):
        metro.StepBlock.release()

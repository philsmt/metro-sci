
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import unittest
from unittest import mock

import numpy

from .. import channels


class NumpyEqualTest(object):
    def __init__(self, array):
        self.array = array

    def __eq__(self, other):
        return (self.array == other).all()


class TestAbstractChannel(unittest.TestCase):
    # The capabilities of AbstractChannel are also tested for in
    # TestNumericChannel.
    pass


# Helper methods for numpy and channel assertions
class ChannelTestCase(unittest.TestCase):
    def assertNumpyEqual(self, arg1, arg2):
        self.assertTrue(
            numpy.equal(arg1, arg2).all(),
            msg='numpy arrays are not equal\n{0}\n{1}'.format(arg1, arg2)
        )

    def assertGetData(self, ch, data,
                      step_index=channels.NumericChannel.CURRENT_STEP):

        self.assertNumpyEqual(ch.getData(step_index=step_index),
                              numpy.array(data))


# This test only covers the details of a scalar NumericChannel.
class TestScalarChannel(ChannelTestCase):
    def setUp(self):
        self.sc = channels.NumericChannel('counts', shape=0)

    def tearDown(self):
        self.sc.close()

    def test_compactData(self):
        res = numpy.array([1, 2])

        value = self.sc._compactData([1, 2])
        self.assertNumpyEqual(value[0], res)
        self.assertEqual(len(value), 1)

        value = self.sc._compactData([numpy.array([1]), 2])
        self.assertNumpyEqual(value[0], res)
        self.assertEqual(len(value), 1)

        value = self.sc._compactData([numpy.array([1, 2])])
        self.assertNumpyEqual(value[0], res)
        self.assertEqual(len(value), 1)


# This test only covers the details of a vector NumericChannel.
class TestVectorChannel(ChannelTestCase):
    def setUp(self):
        self.vc = channels.NumericChannel('raw', shape=2)

    def tearDown(self):
        self.vc.close()

    def test_compactData(self):
        value = self.vc._compactData([
            numpy.array([[1, 2], [3, 4], [5, 6]]),
            numpy.array([[7, 8], [9, 10]]),
            numpy.array([[11, 12]])
        ])

        self.assertNumpyEqual(
            value[0],
            numpy.array([[1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11, 12]])
        )
        self.assertEqual(len(value), 1)


# This tests covers both the details of NumericChannel as well as some
# generic capabilities of AbstractChannel like dependency sorting and
# sub_currentscription.
class TestNumericChannel(ChannelTestCase):
    def setUp(self):
        sc = channels.NumericChannel('det_counts', shape=0)

        ccs = channels.NumericChannel('det_counts_single@2x', shape=0)
        ccs.setComputing(lambda a: 2*a, [sc])

        ccm = channels.NumericChannel('det_counts_multi@2x', shape=0)
        ccm.setComputing(lambda a, b: a+b, [sc, sc])

        ic = channels.NumericChannel('det_counts@sum', shape=0)
        ic.setIntegrating(lambda a: numpy.sum(a), [ccs])

        self.sc = sc
        self.ccs = ccs
        self.ccm = ccm
        self.ic = ic

    def tearDown(self):
        self.sc.close()
        self.ccs.close()
        self.ccm.close()
        self.ic.close()

    def _beginScan(self, scan_value):
        self.sc.beginScan(scan_value)
        self.ccs.beginScan(scan_value)
        self.ccm.beginScan(scan_value)
        self.ic.beginScan(scan_value)

    def _beginStep(self, step_value):
        self.sc.beginStep(step_value)
        self.ccs.beginStep(step_value)
        self.ccm.beginStep(step_value)
        self.ic.beginStep(step_value)

    def _endStep(self):
        self.sc.endStep()
        self.ccs.endStep()
        self.ccm.endStep()
        self.ic.endStep()

    def _endScan(self):
        self.sc.endScan()
        self.ccs.endScan()
        self.ccm.endScan()
        self.ic.endScan()

    def assertChannelData(self, cont_data, step_data):
        self.assertGetData(self.sc, cont_data)
        self.assertGetData(self.ccs, [2*v for v in cont_data])
        self.assertGetData(self.ccm, [2*v for v in cont_data])
        self.assertGetData(self.ic, step_data)

    def test_dependencySort(self):
        channel_list = channels.sortByDependency([self.sc, self.ccs, self.ic])

        self.assertListEqual(channel_list, [self.sc, self.ccs, self.ic])

    def test_freq(self):
        self.assertEqual(self.sc.freq,
                         channels.NumericChannel.CONTINUOUS_SAMPLES)
        self.assertEqual(self.ccs.freq,
                         channels.NumericChannel.CONTINUOUS_SAMPLES)
        self.assertEqual(self.ccm.freq,
                         channels.NumericChannel.CONTINUOUS_SAMPLES)
        self.assertEqual(self.ic.freq,
                         channels.NumericChannel.STEP_SAMPLES)

    def test_getData(self):
        self.assertIsNone(self.sc.getData())
        self.assertIsNone(self.ccs.getData())
        self.assertIsNone(self.ccm.getData())
        self.assertIsNone(self.ic.getData())

        # We tested _compactData already in TestScalarChannel
        self.sc.data = [[numpy.array([1]), 2]]
        self.assertGetData(self.sc, [1, 2])

        self.sc.data = [[1, 4], [2, 1]]
        self.assertGetData(self.sc, [1, 4])
        self.assertGetData(self.sc, [1, 4], step_index=0)
        self.assertGetData(self.sc, [2, 1], step_index=1)

    def test_addData(self):
        # measurement
        self._beginScan(0)
        self._beginStep(0)

        self.sc.addData(2)
        self.sc.addData(5)
        self.sc.addData(8)

        self._endStep()

        self.assertChannelData([2, 5, 8], [30])

        self._endScan()

    def test_setData(self):
        # measurement
        direct_ic = channels.NumericChannel('det_counts@direct-sum', 0)
        direct_ic.setIntegrating(lambda a: numpy.sum(a), [self.sc])

        self._beginScan(0)
        direct_ic.beginScan(0)
        self._beginStep(0)
        direct_ic.beginStep(0)

        self.sc.setData(numpy.array([1, 8, 4]))

        self._endStep()
        direct_ic.endStep()

        self.assertGetData(self.sc, [1, 8, 4])
        self.assertIsNone(self.ccs.getData())
        self.assertIsNone(self.ccm.getData())
        self.assertIsNone(self.ic.getData())
        self.assertGetData(direct_ic, [13])

        self._endScan()
        direct_ic.endScan()

        direct_ic.close()

    def test_measurement(self):
        self._beginScan(0)
        self._beginStep(0)

        self.sc.addData(4)
        self.sc.addData(8)
        self.sc.addData(3)
        self.sc.addData(7)

        self._endStep()

        self.assertChannelData([4, 8, 3, 7], [44])

        self._beginStep(1)

        self.sc.addData(8)
        self.sc.addData(2)

        self._endStep()

        self.assertChannelData([8, 2], [44, 20])

        self._endScan()

        self._beginScan(1)
        self._beginStep(0)

        self.sc.addData(3)
        self.sc.addData(1)

        self._endStep()

        self.assertChannelData([4, 8, 3, 7, 3, 1], [52, 20])

        self._beginStep(1)

        self.sc.addData(1)
        self.sc.addData(1)

        self._endStep()

        self.assertChannelData([8, 2, 1, 1], [52, 24])

        self._endScan()

        self.assertGetData(self.sc, [4, 8, 3, 7, 3, 1], step_index=0)
        self.assertGetData(self.sc, [8, 2, 1, 1], step_index=1)
        self.assertGetData(self.ccs, [8, 16, 6, 14, 6, 2], step_index=0)
        self.assertGetData(self.ccs, [16, 4, 2, 2], step_index=1)
        self.assertGetData(self.ccm, [8, 16, 6, 14, 6, 2], step_index=0)
        self.assertGetData(self.ccm, [16, 4, 2, 2], step_index=1)
        self.assertGetData(self.ic, [52, 24])

    def test_subscriber(self):
        sub_current = mock.Mock()
        self.sc.subscribe(sub_current)
        sub_current.dataCleared.assert_called_once_with()
        sub_current.dataCleared.reset_mock()

        sub_all = mock.Mock()
        self.sc.subscribe(sub_all)
        sub_all.dataCleared.assert_called_once_with()
        sub_all.dataCleared.reset_mock()

        self.sc.setSubscribedStep(sub_all, channels.NumericChannel.ALL_STEPS)
        sub_all.dataCleared.assert_called_once_with()
        sub_all.dataCleared.reset_mock()
        sub_all.dataSet.assert_called_with(None)
        sub_all.dataSet.reset_mock()

        self._beginScan(0)
        self._beginStep(0)
        sub_current.dataCleared.assert_called_once_with()
        sub_current.dataCleared.reset_mock()
        sub_all.dataCleared.assert_not_called()

        self.sc.addData(4)
        sub_current.dataAdded.assert_called_with(4)
        sub_all.dataAdded.assert_called_with(4)
        self.sc.addData(8)
        sub_current.dataAdded.assert_called_with(8)
        sub_all.dataAdded.assert_called_with(8)
        self.sc.addData(3)
        sub_current.dataAdded.assert_called_with(3)
        sub_all.dataAdded.assert_called_with(3)
        self.sc.addData(7)
        sub_current.dataAdded.assert_called_with(7)
        sub_all.dataAdded.assert_called_with(7)

        self._endStep()

        self._beginStep(1)
        sub_current.dataCleared.assert_called_once_with()
        sub_current.dataCleared.reset_mock()
        sub_all.dataCleared.assert_not_called()

        self.sc.addData(8)
        sub_current.dataAdded.assert_called_with(8)
        sub_all.dataAdded.assert_called_with(8)
        self.sc.addData(2)
        sub_current.dataAdded.assert_called_with(2)
        sub_all.dataAdded.assert_called_with(2)

        self._endStep()
        self._endScan()

        self._beginScan(1)
        self._beginStep(0)
        sub_current.dataCleared.assert_not_called()
        sub_current.dataSet.assert_called_with(
            NumpyEqualTest(numpy.array([4, 8, 3, 7]))
        )
        sub_all.dataCleared.assert_not_called()
        sub_all.dataSet.assert_not_called()

        self.sc.addData(3)
        sub_current.dataAdded.assert_called_with(3)
        sub_all.dataAdded.assert_called_with(3)

        sub_specific = mock.Mock()
        self.sc.subscribe(sub_specific)
        self.sc.setSubscribedStep(sub_specific, 0)
        sub_specific.dataSet.assert_called_with(
            NumpyEqualTest(numpy.array([4, 8, 3, 7, 3]))
        )

        self.sc.addData(1)
        sub_current.dataAdded.assert_called_with(1)
        sub_all.dataAdded.assert_called_with(1)
        sub_specific.dataAdded.assert_called_with(1)

        self._endStep()

        sub_specific.dataCleared.reset_mock()
        sub_specific.dataSet.reset_mock()
        sub_specific.dataAdded.reset_mock()

        self._beginStep(1)
        sub_current.dataSet.assert_called_with(
            NumpyEqualTest(numpy.array([8, 2]))
        )
        sub_all.dataCleared.assert_not_called()
        sub_all.dataSet.assert_not_called()
        sub_specific.dataCleared.assert_not_called()
        sub_specific.dataSet.assert_not_called()

        self.sc.addData(1)
        sub_current.dataAdded.assert_called_with(1)
        sub_all.dataAdded.assert_called_with(1)
        sub_specific.dataAdded.assert_not_called()
        self.sc.addData(2)
        sub_current.dataAdded.assert_called_with(2)
        sub_all.dataAdded.assert_called_with(2)
        sub_specific.dataAdded.assert_not_called()

        self._endStep()
        self._endScan()

        self.sc.unsubscribe(sub_current)
        self.sc.unsubscribe(sub_all)
        self.sc.unsubscribe(sub_specific)

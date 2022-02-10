
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import collections
import glob
import os
import struct
import sys
import time

import numpy
import h5py


# -----------------------------------------------------------------------------


MetroRun = collections.namedtuple('MetroRun', ['number', 'name', 'root',
                                               'path', 'time', 'date',
                                               'channels'])

HptdcRawWord = numpy.dtype('<u4')
HptdcDecodedWord = numpy.dtype([('type', 'S2'), ('arg1', '<i1'),
                                ('arg2', '<i1'), ('arg3', '<i4')], align=True)
HptdcHit = numpy.dtype([('time', '<i8'), ('channel', '<u1'), ('type', '<u1'),
                        ('bin', '<u2'), ('align', '<i4')])
HptdcStepEntry32 = numpy.dtype([('value', 'a32'), ('data_offset', '<i4'),
                                ('data_size', '<i4')])
HptdcStepEntry64 = numpy.dtype([('value', 'a32'), ('data_offset', '<i8'),
                                ('data_size', '<i8')])

HptdcWordDefinitions = {
    b'FL': {'type_len': 2, 'type_val': 2, 'arg1': (29, 24), 'arg3': (23, 0)},
    b'RS': {'type_len': 2, 'type_val': 3, 'arg1': (29, 24), 'arg3': (23, 0)},
    b'ER': {'type_len': 2, 'type_val': 1, 'arg1': (29, 24), 'arg2': (23, 16),
            'arg3': (15, 0)},
    b'GR': {'type_len': 4, 'type_val': 0, 'arg1': (27, 24), 'arg3': (23, 0)},
    b'RL': {'type_len': 8, 'type_val': 16, 'arg3': (23, 0)},
    b'LV': {'type_len': 5, 'type_val': 3, 'arg1': (26, 21), 'arg3': (20, 0)}
}


def _bitmask(start, end):
    return ((1 << (start - end)) - 1) << end


def parse_run_root(filename):
    root = os.path.basename(filename)
    parts = root.split('_')

    try:
        int(parts[0])
    except ValueError:
        number = ''
        name_idx = 0
    else:
        number = parts[0]
        name_idx = 1

    time = parts[-1]
    date = parts[-2]

    return MetroRun(
        number=number,
        name='_'.join(parts[name_idx:-2]),
        root=root,
        path=filename,
        time='{0}:{1}:{2}'.format(time[:2], time[2:4], time[4:]),
        date='{0}.{1}.{2}'.format(date[:2], date[2:4], date[4:]),
        channels=[]
    )


def remove_extra_marker(data_str):
    while '#' in data_str:
        marker_start = data_str.find('#')
        marker_end = (marker_start + data_str[marker_start:].find('\n'))
        data_str = (data_str[:marker_start] +
                    data_str[marker_end+1:])

        print('removed extra marker...', end='', flush=True)

    return data_str


def convert_ascii_file(channel_file, h5ch, compress_args={}, **kwargs):
    with open(channel_file, 'r') as fp:
        body_offset = 0
        headers = {}
        column_count = 0
        scan_markers = True

        for line in fp:
            if line[:6] == '# SCAN':
                break
            elif line[:6] == '# STEP':
                # STEP marker but no SCAN marker
                print('WARNING: It appears this channel file contains no scan '
                      'markers, assuming one scan...', end='', flush=True)

                scan_markers = False
                break

            elif line[0] != '#':
                # No marker at all! Either we have the bugged ROI header
                # or data appeared before SCAN/STEP tags

                if line[0] == 'Y':
                    # I really screwed up once and included newlines in
                    # a header value... and now it haunts me! So we have
                    # to catch this occurence, add the ROI string and
                    # then just continue as if nothing happened.
                    headers['X-roi'] = '{0} - {1}'.format(headers['X-roi'],
                                                          line.strip())

                    continue
                else:
                    # We have data before
                    print('WARNING: Data appeared in this channel file before '
                          'any scan or step marker, ignoring row...', end='',
                          flush=True)

                    continue

                break

            key = line[2:line.find(':')]
            value = line[4+len(key):].strip()

            headers[key] = value

            body_offset += len(line)

        if 'Type' in headers:
            # old style file
            type_detail = headers['Type'][headers['Type'].find('(')+1:-1]

            if type_detail == 'STEP':
                headers['Shape'] = '0'
                headers['Frequency'] = 'step'
            elif type_detail == 'CONT':
                headers['Shape'] = '0'
                headers['Frequency'] = 'continuous'
            else:
                headers['Shape'] = type_detail
                headers['Frequency'] = 'continuous'

        if 'Shape' not in headers:
            print('WARNING: No shape information, skipping!')
            return False
        else:
            shape = int(headers['Shape'])

        if 'Frequency' not in headers:
            print('WARNING: No frequency information, assuming continuous...',
                  end='', flush=True)
            freq = 'continuous'
        else:
            freq = headers['Frequency']

            if freq not in ('continuous', 'step'):
                print('WARNING: Unknown or unsupported frequency \'{0}\', '
                      'skipping!'.format(freq))
                return False

        # Obtain the column count
        for line in fp:
            if line[0] != '#':
                column_count = len(line.rstrip().split('\t'))
                break

        for key, value in headers.items():
            h5ch.attrs[key] = value

        # Obtain the number of scans and steps per scan
        if scan_markers:
            scan_offsets = []
            step_offsets = []
            scan_idx = -1
        else:
            step_offsets = [[]]
            scan_idx = 0

        cur_offset = body_offset
        fp.seek(body_offset)

        for line in fp:
            if line[:6] == '# SCAN':
                scan_idx += 1

                scan_offsets.append(cur_offset)
                step_offsets.append([])

            elif line[:6] == '# STEP':
                step_offsets[scan_idx].append(cur_offset)

            cur_offset += len(line)

        if not scan_markers:
            scan_offsets = [body_offset]

        if freq == 'step' and shape == 0:
            for scan_idx in range(len(scan_offsets)):
                fp.seek(scan_offsets[scan_idx])

                marker_line = fp.readline() if scan_markers else ''

                try:
                    read_len = (scan_offsets[scan_idx+1] -
                                scan_offsets[scan_idx] - len(marker_line))
                except IndexError:
                    read_len = None

                data_str = remove_extra_marker(fp.read(read_len))

                h5ch.create_dataset(str(scan_idx), data=numpy.fromstring(
                    data_str, count=data_str.count('\n'), sep='\n',
                ))

        else:
            for scan_idx in range(len(step_offsets)):
                h5scan = h5ch.create_group(str(scan_idx))

                for step_idx in range(len(step_offsets[scan_idx])):
                    cur_pos = step_offsets[scan_idx][step_idx]

                    fp.seek(cur_pos)
                    marker_line = fp.readline()
                    step_value = marker_line[marker_line.find(':')+1:].strip()

                    try:
                        read_len = (step_offsets[scan_idx][step_idx+1] -
                                    cur_pos - len(marker_line))
                    except IndexError:
                        if scan_idx == len(step_offsets)-1:
                            # This the very last step
                            read_len = None
                        else:
                            # There is a scan ahead
                            read_len = (step_offsets[scan_idx+1][0] -
                                        cur_pos - len(marker_line))

                    data_str = remove_extra_marker(fp.read(read_len))
                    data_len = len(data_str)

                    if data_len > 0:
                        local_compress_args = (compress_args
                                               if data_len > 1024
                                               else {})

                        try:
                            data = numpy.fromstring(
                                data_str, sep=' ',
                                count=data_str.count('\n')*column_count
                            ).reshape(-1, column_count)
                        except ValueError:
                            pass
                        else:
                            h5scan.create_dataset(step_value.strip(),
                                                  data=data,
                                                  **local_compress_args)
                    else:
                        h5scan.create_dataset(step_value.strip(),
                                              shape=(0, column_count))

    return True


def convert_hdf_file(channel_file, h5ch, compress_args={}, **kwargs):
    # Check first whether we can open the file. We still want to use a
    # resource manager later on, so we close it immediately
    try:
        h5in = h5py.File(channel_file, 'r')
    except Exception as e:
        print('WARNING: {0}, skipping!'.format(str(e)))
        return False
    else:
        h5in.close()

    with h5py.File(channel_file, 'r') as h5in:
        try:
            freq = h5in.attrs['freq']
        except KeyError:
            print('WARNING: No frequeny attribute found, skipping!')
            return False

        # Frequency and hint were saved with their constant rather than
        # their string for a while, so accept both.
        if freq == 0 or freq == 'cont':
            print('INFO: Part of a continuous multi-file channel, skipping!')
            return False

        for key in h5in.attrs:
            h5ch.attrs[key] = h5in.attrs[key]

        for k in h5in:
            # Scan groups may be missing, so create them now.
            if isinstance(h5in[k], h5py.Dataset):
                dest_name = '0/' + k
            else:
                dest_name = k

            h5in.copy(k, h5ch, dest_name)

    return True


def rebuild_hptdc_tables(fp, scan_marker, step_marker, data_end, read_length,
                         HptdcStepEntry=HptdcStepEntry64):

    print('scanning for markers...', end='')

    # First we have to get "aligned" to the begin of this file's
    # data section, which always consists of a scan marker. So
    # we skip the magic code and search for this marker in the
    # two kiB of the file.

    fp.seek(5)
    buf = fp.read(2048)

    data_begin = -1
    scan_marker_length = len(scan_marker)

    for i in range(2048 - scan_marker_length):
        if buf[i:i+scan_marker_length] == scan_marker:
            data_begin = 5 + i
            break

    if data_begin < 0:
        print('WARNING: Could not find first scan marker, skipping!')
        return False

    fp.seek(data_begin)

    eof = False
    buf = b''

    offset = fp.tell()
    marker_pos = []

    # The outer loop reads a chunk of our file, while the inner
    # loop searches for markers.

    while not eof:
        new_buf = fp.read(read_length)

        if len(new_buf) < read_length:
            eof = True

        buf += new_buf

        buf_len = len(buf)
        buf_pos = 0

        while buf_pos < buf_len:
            next_scan_pos = buf[buf_pos:].find(scan_marker)
            next_step_pos = buf[buf_pos:].find(step_marker)

            if next_scan_pos < 0 and next_step_pos < 0:
                # Nothing anymore in this block, truncate to the
                # last checked position or the length of a
                # marker

                margin_pos = max(
                    buf_pos,
                    len(buf) - max(len(scan_marker), len(step_marker))
                )
                buf = buf[margin_pos:]
                offset += margin_pos

                break

            if next_scan_pos > -1:
                if next_scan_pos < next_step_pos or next_step_pos < 0:
                    marker_pos.append(offset + buf_pos + next_scan_pos)
                    marker_pos[-1] = -marker_pos[-1]
                    buf_pos += next_scan_pos + len(scan_marker)

            if next_step_pos > -1:
                if next_step_pos < next_scan_pos or next_scan_pos < 0:
                    marker_pos.append(offset + buf_pos + next_step_pos)
                    buf_pos += next_step_pos + len(step_marker)

    n_markers = len(marker_pos)
    scan_idx = -1
    step_idx = 0
    step_tables = []

    for i in range(n_markers):
        if marker_pos[i] < 0:
            scan_idx += 1
            step_count = 0
            step_idx = 0

            for j in range(i+1, n_markers):
                if marker_pos[j] < 0:
                    break

                step_count += 1

            step_tables.append(numpy.zeros((step_count,),
                                           dtype=HptdcStepEntry))

        else:
            entry = step_tables[scan_idx][step_idx]

            entry['value'] = str(float(step_idx)).encode('ascii')
            entry['data_offset'] = marker_pos[i]

            try:
                next_marker = marker_pos[i+1]
            except IndexError:
                next_marker = data_end

            entry['data_size'] = next_marker - entry['data_offset']

            step_idx += 1

    return scan_idx + 1, step_tables


def convert_hptdc_group_data_raw(data):
    return data


def convert_hptdc_group_data_decoded(inp):
    outp = numpy.zeros_like(inp, dtype=HptdcDecodedWord)
    known_mask = numpy.zeros_like(inp, dtype=bool)

    for type_str, type_def in HptdcWordDefinitions.items():
        type_mask = numpy.equal(inp >> (32 - type_def['type_len']),
                                type_def['type_val'])

        if not type_mask.any():
            continue

        known_mask |= type_mask

        numpy.place(outp[:]['type'], type_mask, type_str)

        for arg_name in ('arg1', 'arg2', 'arg3'):
            if arg_name not in type_def:
                continue

            arg_def = type_def[arg_name]

            numpy.place(outp[:][arg_name], type_mask, (
                (inp[type_mask] & _bitmask(*arg_def)) >> arg_def[1]
            ).astype(HptdcDecodedWord.fields[arg_name][0]))

    unknown_mask = ~known_mask

    if unknown_mask.any():
        numpy.place(outp[:]['type'], unknown_mask, b'??')
        numpy.place(outp[:]['arg3'], unknown_mask,
                    inp[unknown_mask].astype('i4'))

    return outp


def convert_hptdc_hits_data(data):
    return data[['time', 'channel', 'type', 'bin']]


def convert_hptdc_file(channel_file, h5ch, compress_args={},
                       hptdc_chunk_size=10000, hptdc_word_format='raw',
                       hptdc_ignore_tables=False, **kwargs):
    h5ch.attrs['Type'] = 'hptdc'

    with open(channel_file, 'rb') as fp:
        # First check for the magic code
        if fp.read(5) != b'HPTDC':
            print('WARNING: Invalid magic code, skipping!')
            return False

        # Starting in around October 2017, a reworked (and extendable)
        # header format was introduced. We try to distinguish by the
        # DATA marker that should be directly behind the header. So read
        # the file as if it's the new format and fall back if not.
        old_style = False

        header_size, version = struct.unpack('<ii', fp.read(8))
        mode = fp.read(4)
        scan_table_offset, scan_count, param_table_offset, \
            param_table_size = struct.unpack('<qiqi', fp.read(24))

        # A header above 4096 bytes in size is highly unlikely, so we
        # only continue if it is smaller
        if header_size > 4096:
            old_style = True
        else:
            # Skip extra header
            fp.read(header_size - 32)

            if fp.read(4) != b'DATA':
                old_style = True

        if old_style:
            # Reset to header directly after magic code and re-read
            fp.seek(5)
            scan_table_offset, scan_count, param_table_offset, \
                param_table_size, mode = struct.unpack('<iiiic', fp.read(17))

            # Always assume HITS mode without a mode marker
            mode = b'GRPS' if mode == b'G' else b'HITS'

            HptdcStepEntry = HptdcStepEntry32

        else:
            HptdcStepEntry = HptdcStepEntry64

        if mode == b'GRPS':
            if hptdc_word_format == 'raw':
                out_dtype = HptdcRawWord
                convert_data_func = convert_hptdc_group_data_raw
            elif hptdc_word_format == 'decoded':
                out_dtype = HptdcDecodedWord
                convert_data_func = convert_hptdc_group_data_decoded

            in_dtype = HptdcRawWord
            scan_marker = b'\x00\x00\x00\x00\xA0\x00\x00\x00'
            step_marker = b'\x00\x00\x00\x00\xB0\x00\x00\x00'

        elif mode == b'HITS':
            convert_data_func = convert_hptdc_hits_data
            in_dtype = HptdcHit
            out_dtype = HptdcHit
            scan_marker = b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xA0\x00\x00' \
                          b'\x00\x00\x00\x00'
            step_marker = b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xB0\x00\x00' \
                          b'\x00\x00\x00\x00'

        else:
            print('FATAL: Unknown TDC mode encountered, skipping!')
            return False

        h5ch.attrs['Mode'] = mode

        if scan_table_offset > 0 and not hptdc_ignore_tables:
            fp.seek(scan_table_offset)

            step_tables = []

            for scan_idx in range(scan_count):
                step_count, step_table_size = struct.unpack('<ii', fp.read(8))

                step_table = numpy.fromstring(fp.read(step_table_size),
                                              dtype=HptdcStepEntry)

                for step_idx in range(step_count):
                    data_size = step_table[step_idx]['data_size']

                    if data_size < 0 or data_size % in_dtype.itemsize != 0:
                        print('WARNING: Invalid data_size entry {0} for step '
                              '{1}, ignoring '
                              'tables...'.format(data_size, step_idx), end='')

                        step_table = None
                        break

                if step_table is None:
                    step_tables = None
                    break

                step_tables.append(step_table)
        else:
            step_tables = None

            if scan_table_offset == 0 and not hptdc_ignore_tables:
                print('WARNING: Tables are probably corrupted, trying to '
                      'rebuild...', end='')

        if step_tables is None:
            # If the scan_table_offset is zero, the file was not closed
            # properly (at which point the offset is written), so the
            # data continues until the end. We can therefore use the
            # total file size as an effective scan_table_offset

            if scan_table_offset == 0:
                scan_table_offset = os.path.getsize(channel_file)

            scan_count, step_tables = rebuild_hptdc_tables(
                fp, scan_marker, step_marker, scan_table_offset,
                max(len(scan_marker), len(step_marker)) * hptdc_chunk_size,
                HptdcStepEntry
            )

        for scan_idx in range(scan_count):
            h5scan = h5ch.create_group(str(scan_idx))

            for step_idx in range(step_tables[scan_idx].shape[0]):
                step_entry = step_tables[scan_idx][step_idx]

                try:
                    step_value = step_entry['value'].decode('ascii')
                except ValueError:
                    print('WARNING: Corrupted step table, skipping!')
                    return False

                fp.seek(step_entry['data_offset'])
                fp.read(len(step_marker))  # marker

                data_len = step_entry['data_size'] - len(step_marker)

                if data_len < 0:
                    print('WARNING: Corrupted step table, skipping!')
                    return False

                elif data_len == 0:
                    try:
                        column_count = len(out_dtype.names)
                    except TypeError:
                        column_count = 1

                    h5scan.create_dataset(step_value, shape=(0, column_count),
                                          dtype=out_dtype)
                    continue

                elif data_len < 1024:
                    local_compress_args = {}

                else:
                    local_compress_args = compress_args

                h5step = h5scan.create_dataset(
                    step_value, shape=(data_len // in_dtype.itemsize,),
                    dtype=out_dtype, **local_compress_args
                )

                chunk_len = int(in_dtype.itemsize * hptdc_chunk_size)
                start_idx = 0

                for offset in range(0, data_len, chunk_len):
                    data = convert_data_func(numpy.fromstring(
                        fp.read(min(chunk_len, data_len - offset)),
                        dtype=in_dtype
                    ))

                    h5step[start_idx:start_idx+data.shape[0]] = data
                    start_idx += data.shape[0]

        try:
            fp.seek(param_table_offset)
        except OSError:
            # Usually the header is damaged, so skip the param table
            print('WARNING: Invalid offset for parameters table in header, '
                  'probably not present in dataset...', end='')
            return True

        # We read one byte less to omit the last newline character
        try:
            param_lines = fp.read(param_table_size - 1).decode('ascii') \
                            .split('\n')
        except Exception:
            print('WARNING: Corrupted parameters table, not present in '
                  'dataset...', end='')
            return True
        else:
            if param_lines and param_lines[0]:
                for line in param_lines:
                    key, value = line.split(' ')
                    h5ch.attrs[key] = value
            else:
                print('WARNING: Empty parameters table...', end='')

    return True


def convert_legacy_hptdc_file(channel_file, h5ch, compress_args={}, **kwargs):
    body_offset = 0x29  # offset for hint and frequency line

    h5ch.attrs['Type'] = 'hptdc_legacy'

    with open(channel_file, 'rb') as fp:
        while True:
            c = fp.read(1)
            body_offset += 1

            if c[0] == 0xA:
                break

        marker = [body_offset-16]
        cur_offset = body_offset

        fp.seek(cur_offset)

        while True:
            hit = fp.read(16)

            if not hit:
                break

            if hit[9] == 3 and hit[:8] == b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF':
                marker.append(cur_offset)

            cur_offset += 16

        n_steps = len(marker)-1

        for step_idx in range(n_steps):
            fp.seek(marker[step_idx])
            fp.read(16)

            try:
                read_len = marker[step_idx+1] - marker[step_idx] - 16
            except IndexError:
                # Shouldn't happen!
                break

            data_str = fp.read(read_len)
            data_len = len(data_str)

            if data_len % 16 != 0:
                print('WARNING: Invalid data string length {0} on step '
                      '{1}, skipping!'.format(step_idx, data_len))
                return False

            if data_len > 0:
                local_compress_args = (compress_args
                                       if data_len > 1024
                                       else {})

                data = numpy.fromstring(data_str, dtype=HptdcHit,
                                        count=(data_len // 16))
                h5ch.create_dataset(
                    str(step_idx),
                    data=data[['time', 'channel', 'type', 'bin']],
                    **local_compress_args
                )
            else:
                h5ch.create_dataset(str(step_idx), shape=(0, 4))

    return True


def convert_file(channel_name, channel_file, h5f, compress_args={}, **kwargs):
    print('* {0}...'.format(channel_name), end='', flush=True)

    convert_func = None
    ext = channel_file[channel_file.rfind('.'):]

    if ext == '.txt':
        convert_func = convert_ascii_file

    elif ext == '.h5':
        convert_func = convert_hdf_file

    elif ext == '.tdc':
        convert_func = convert_hptdc_file

    elif ext == '.bin' or channel_name in kwargs['hptdc_legacy_channels']:
        convert_func = convert_legacy_hptdc_file

    if convert_func is not None:
        h5ch = h5f.create_group(channel_name)

        if convert_func(channel_file, h5ch, compress_args, **kwargs):
            print('done')
        else:
            if len(h5ch) == 0:
                del h5ch

    else:
        print('WARNING: Unknown file format, skipping!')


def run(glob_str='*', output_dir=None, output_format='{root}', driver=None,
        compress_args={}, replace=False, **kwargs):
    if output_dir is None:
        output_dir = os.getcwd()

    runs = []
    glob_list = glob.glob(glob_str)

    # First we sort out the screenshot as markers
    for entry in glob_list:
        if entry[-4:] != '.jpg' and entry[-4:] != '.png':
            continue

        runs.append(parse_run_root(entry[:-4]))

    # Now add the channels
    for entry in glob_list:
        if entry[-4:] == '.jpg' or entry[-4:] == '.png':
            continue

        for run in runs:
            if (entry.startswith(run.path) and
                    entry[:entry.rfind('.')] != run.path):
                run.channels.append(entry)

    # Filter out runs without any channels
    filtered_runs = []
    for run in runs:
        if len(run.channels) > 0:
            run.channels.sort()
            filtered_runs.append(run)

    runs = sorted(filtered_runs, key=lambda x: x.number)
    filtered_runs.clear()

    # Fail if we have no channels
    if not runs:
        raise ValueError('No runs with channels found using glob pattern: '
                         '{0}'.format(glob_str))

    print('Found {0} measurement runs with {1:.1f} channels on average'.format(
        len(runs), sum([len(x.channels) for x in runs])/len(runs)
    ))

    # And let's begin!
    for run in runs:
        print('Starting {0} with {1} channels'.format(run.root,
                                                      len(run.channels)))
        start_time = time.time()

        out_path = '{0}/{1}.h5'.format(output_dir,
                                       output_format.format(**run._asdict()))

        if os.path.isfile(out_path) and not replace:
            print('Found existing file, skipping!')
            continue

        h5f = h5py.File(out_path, 'w', driver=driver)

        h5f.attrs['number'] = run.number
        h5f.attrs['name'] = run.name
        h5f.attrs['root'] = run.root
        h5f.attrs['path'] = run.path
        h5f.attrs['time'] = run.time
        h5f.attrs['date'] = run.date

        for channel_file in run.channels:
            convert_file(channel_file[len(run.path)+1:channel_file.rfind('.')],
                         channel_file, h5f, compress_args, **kwargs)

        h5f.close()

        end_time = time.time()
        print('Completed in {0:.1f} s'.format(end_time - start_time))


# -----------------------------------------------------------------------------


def main():
    import argparse

    # Define command line arguments
    cli = argparse.ArgumentParser(
        prog='metro2hdf.py',
        description='Converts METRO data files to hdf5'
    )

    cli.add_argument(
        '--glob', dest='glob_str', action='store', type=str,
        metavar='pattern', default='*',
        help='specify a pattern to glob for to narrow down conversion '
             '(default: *)'
    )

    cli.add_argument(
        '--output-dir', dest='output_dir', action='store', type=str,
        metavar='path', default=os.getcwd(),
        help='output directory for hdf5 files'
    )

    cli.add_argument(
        '--replace', dest='replace', action='store_true',
        help='replace already existing output files'
    )

    cli.add_argument(
        '--verbose', dest='verbose', action='store_true',
        help='give more detailed messages if possible'
    )

    shortening_group = cli.add_mutually_exclusive_group()

    shortening_group.add_argument(
        '--shorter-name', dest='shorter_name', action='store_true',
        help='use only number and name as filename for the output files'
    )

    shortening_group.add_argument(
        '--shortest-name', dest='shortest_name', action='store_true',
        help='use only the number as filename for the output files'
    )

    hdf_group = cli.add_argument_group('HDF5 options')

    hdf_group.add_argument(
        '--driver', dest='driver', action='store', type=str,
        metavar='name', choices=['sec2', 'stdio', 'core', 'family'],
        help='specify a particular low-level driver for HDF5 to use'
    )

    hdf_group.add_argument(
        '--compress', dest='compression', action='store', type=int,
        metavar='level', const=4, default=-1, nargs='?',
        help='use gzip compression with optionally specified level '
             '(default: 4) for datasets above 1024 bytes'
    )

    hptdc_group = cli.add_argument_group('HPTDC options')

    hptdc_group.add_argument(
        '--hptdc-chunk-size', dest='hptdc_chunk_size', action='store',
        type=int, metavar='size', default=10000,
        help='the number of data elements to read, convert and store at a '
             'time (default: 1e5).'
    )

    hptdc_group.add_argument(
        '--hptdc-ignore-tables', dest='hptdc_ignore_tables',
        action='store_true',
        help='ignore the scan and step tables in a TDC file and try to '
             'rebuild them by searching for its markers.'
    )

    hptdc_group.add_argument(
        '--hptdc-word-format', dest='hptdc_word_format', action='store',
        type=str, choices=['raw', 'decoded'], default='raw',
        help='store the words generated in certain operation modes directly '
             'in raw form (4 byte per word, default) or decoded into its type '
             'and argument (8 byte per word).'
    )

    hptdc_group.add_argument(
        '--hptdc-with-legacy', dest='hptdc_legacy_channels', action='store',
        type=str, metavar='channel', nargs='+', default=[],
        help='treat these channels as legacy RoentDek HPTDC raw hit stream '
             'files (recorded before February 2017) if they were not '
             'identified automatically'
    )

    # Parse them!
    args, argv_left = cli.parse_known_args()

    if args.shorter_name:
        output_format = '{number}_{name}'
    elif args.shortest_name:
        output_format = '{number}'
    else:
        output_format = '{root}'

    if args.driver == 'family':
        print('FATAL: family driver is currently not supported')
        sys.exit(0)

    compress_args = {}
    if args.compression > -1:
        compress_args['compression'] = 'gzip'
        compress_args['compression_opts'] = args.compression

    try:
        run(compress_args=compress_args, output_format=output_format,
            **vars(args))
    except Exception as e:
        if args.verbose:
            print('FATAL EXCEPTION')
            raise e
        else:
            print('FATAL:', str(e))

        sys.exit(0)

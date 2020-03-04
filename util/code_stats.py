#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import os

# Testing around with static type checking
try:
    from typing import List, Tuple  # noqa
except ImportError:
    pass

ignore_directories = ['__pycache__', 'external', '.git']

n_src_files = 0
n_ui_files = 0
all_total_lines = 0
all_true_lines = 0
all_text_lines = 0
all_size = 0
all_ui = 0

entries = []  # type: List[Tuple[str, int, int, int, int]]

for root, dirs, files in os.walk('../'):
    # Skip some directories
    # We use a try-except and raise a ValueError if we want to
    # skip this directory
    try:
        # Skip ignored directories
        for v in ignore_directories:
            if v in root:
                raise ValueError

    except ValueError:
        continue

    total_lines = 0
    true_lines = 0
    text_lines = 0
    size = 0
    ui = 0

    for file_name in files:
        _, file_ext = os.path.splitext(file_name)

        path = os.path.join(root, file_name)

        if file_ext not in ('.py', '.pyx', '.qml'):
            if file_ext in ('.ui'):
                n_ui_files += 1
                ui += os.path.getsize(path)

            continue

        in_comment = False

        n_src_files += 1

        with open(path, 'r', encoding='utf-8') as fp:
            try:
                for line in fp:
                    total_lines += 1

                    stripped_line = line.strip()

                    if not stripped_line:
                        continue

                    true_lines += 1

                    if in_comment:
                        text_lines += 1

                        if (stripped_line.startswith("'''") or
                                stripped_line.startswith('"""') or
                                stripped_line.startswith('*/')):
                            in_comment = False
                    else:
                        if (stripped_line.startswith("'''") or
                                stripped_line.startswith('"""') or
                                stripped_line.startswith('/*')):
                            text_lines += 1
                            in_comment = True

                        elif (stripped_line.startswith('#') or
                                stripped_line.startswith('//')):
                            text_lines += 1
            except UnicodeDecodeError:
                print('UnicodeDecodeError:', path)

        size += os.path.getsize(path)

    if total_lines > 0:
        dir_name = root.lstrip('..' + os.sep)

        if not dir_name:
            dir_name = '.'

        entries.append((dir_name, total_lines, true_lines, text_lines,
                        size, ui))

    all_total_lines += total_lines
    all_true_lines += true_lines
    all_text_lines += text_lines
    all_size += size
    all_ui += ui

# Sort by name
entries.sort(key=lambda x: x[0])

print(n_src_files, 'source files and', n_ui_files, 'ui files found')

print('total', 'true', 'code', 'text', 'blank', 'size', 'ui', 'directory',
      sep='\t')
print('----------------------------------------------------------------------')

for (dir_name, total_lines, true_lines, text_lines, size, ui) in entries:
    print(total_lines, true_lines, true_lines - text_lines, text_lines,
          total_lines - true_lines, size, ui, dir_name, sep='\t')

print('----------------------------------------------------------------------')

print(all_total_lines, all_true_lines, all_true_lines - all_text_lines,
      all_text_lines, all_total_lines - all_true_lines, all_size, all_ui,
      sep='\t')

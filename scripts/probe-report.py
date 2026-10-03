#!/usr/bin/env python3
"""Summarize app probes collected from Dolphin SD sync or a physical Wii."""
import argparse
import csv
import sys
from collections import defaultdict
p = argparse.ArgumentParser()
p.add_argument('csv')
a = p.parse_args()
stats = defaultdict(lambda: [0, 0, 0, 0, 0])
with open(a.csv, newline='') as f:
    reader = csv.DictReader(f)
    if reader.fieldnames != ['window','group','level','count','timed_count','total_us','max_us','value']:
        sys.exit('Unexpected probe CSV header; use the matching build/report script.')
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            sys.exit('Incomplete probe row; finish guest teardown/SD flush before collecting the report.')
        s = stats[row['group'], int(row['level'])]
        s[0] += int(row['count'])
        s[1] += int(row['timed_count'])
        s[2] += int(row['total_us'])
        s[3] = max(s[3], int(row['max_us']))
        s[4] += int(row['value'])
print('group level count timed_count mean_us max_us value')
for (group, level), (count, timed, total, maximum, value) in sorted(stats.items()):
    print(group, level, count, timed, f'{total/timed:.1f}' if timed else '-', maximum, value)

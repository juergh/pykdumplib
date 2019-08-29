#!/usr/bin/env python
# -*- coding: utf-8 -*-
# module LinuxDump.Time
#
# --------------------------------------------------------------------
# (C) Copyright 2006-2019 Hewlett Packard Enterprise Development LP
#
# Author: Alex Sidorenko <asid@hpe.com>
#
# --------------------------------------------------------------------
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.


__doc__ = '''
This is a package providing subroutines for time manipulation.
Many subroutines are still experimental as time keeping is very
different on different kernels
'''

__all__ = ['j_delay', 'seconds_since_boot',
           'get_uptime_fromcrash', 'sched_clock']

# Some of this code used to be in Tasks.py, but it makes sense
# to put all time-related subroutines here

from pykdump.API import *
import crash
from collections import namedtuple
import re


def j_delay(ts, jiffies,maxhours = 24):
    v = (jiffies - ts) & INT_MASK
    if (v > INT_MAX):
        v = "     n/a"
    elif (v > HZ*3600*maxhours):
        v = ">{}hours".format(maxhours)
    elif (v > HZ*3600*10):
        v = "%d hours" % (v/HZ/3600)
    else:
        v = "%3.2f s" % (float(v)/HZ)
    return v

class _readSymbol():
    def __init__(self, topsymbol = None):
        self.topsymbol = topsymbol
    def __getattr__(self, attr):
        if (self.topsymbol):
            return getattr(readSymbol(self.topsymbol), attr)
        else:
            return readSymbol(attr)

timespec = namedtuple("timespec", ['tv_sec', 'tv_nsec'])

NSEC_PER_SEC = 1000000000
def set_normalized_timespec(sec, nsec):
    while (nsec >= NSEC_PER_SEC):
        nsec -= NSEC_PER_SEC
        sec += 1

    while (nsec < 0):
        nsec += NSEC_PER_SEC
        sec -= 1

    return timespec(sec, nsec)



def getboottime():
    tv_sec = tk.wall_to_monotonic.tv_sec +  tk.total_sleep_time.tv_sec
    tv_nsec = tk.wall_to_monotonic.tv_nsec + tk.total_sleep_time.tv_nsec
    return set_normalized_timespec(-tv_sec, -tv_nsec)


def seconds_since_boot():
    boot = getboottime()
    return get_seconds() - boot.tv_sec

# Kernel-dependent subroutines. In older kernels, we have a global
# 'struct timespec wall_to_monotonic' and 'xtime', on newer kernels they
# are members, 'timekeeper.wall_to_monotonic' and 'timekeeper.xtime'
#


if (symbol_exists("wall_to_monotonic")):
    tk = _readSymbol()
    def get_seconds():
        return tk.xtime.tv_sec
    # In old (e.g. RHEL5) kernels, there is no seconds_since_boot().
    # In this case, refage calculations in
    # use just get_seconds() -> xtime.tv_sec;
    if (not symbol_exists("total_sleep_time")):
        seconds_since_boot = None
else:
    tk = _readSymbol("timekeeper")
    def get_seconds():
        return tk.xtime_sec


def get_uptime_fromproc():
    with open('/proc/uptime', 'r') as f:
        uptime_seconds = int(float((f.readline().split()[0])))
    return uptime_seconds


def get_uptime_fromcrash():
    return crash.get_uptime()/HZ

# Get ktime_get() value as saved in last_jiffies_update. Precision is
# limited by HZ as this specifies how often jiffies are updated
# A better value can be probable extracted from timer bases
@memoize_cond(CU_LIVE)
def get_ktime_j():
    try:
        value = readSymbol("last_jiffies_update").tv64
    except:
        value = None
    return value

# Parse 'timer -r' output until we provide a proper implementation
# We are interested in lines like that:
# CLOCK: 1  HRTIMER_CLOCK_BASE: ffff880123410628  [ktime_get]
#     CURRENT
# 671354073000000

# WARNING: this does not work for recent kernels anymore!
__re_ktime = re.compile(r'^.*\[ktime_get].*\n\s+CURRENT\s*\n\s*(\d+)\s*$',
                        re.M)

@memoize_cond(CU_LIVE)
def get_ktime_t():
    s = exec_crash_command("timer -r")
    for v in __re_ktime.findall(s):
        print(v)

# ========================================================
#
# On new kernels, we have tk_core
#
# ktime_t ktime_get(void)
# {
# 	struct timekeeper *tk = &tk_core.timekeeper;
# 	unsigned int seq;
# 	ktime_t base;
# 	u64 nsecs;

# 	WARN_ON(timekeeping_suspended);

# 	do {
# 		seq = read_seqcount_begin(&tk_core.seq);
# 		base = tk->tkr_mono.base;
# 		nsecs = timekeeping_get_ns(&tk->tkr_mono);

# 	} while (read_seqcount_retry(&tk_core.seq, seq));

# 	return ktime_add_ns(base, nsecs);
# }

# Some kernels use a simple integer and some use ktime_t wrapper
# This subroutine returns a.counter if argument is atomic_t or
# just argument without any changes otherwise
def ktime_t(t):
    try:
        return t.tv64
    except AttributeError:
        return t


def tkr_time():
    try:
        tkr = PYKD.tk_core.timekeeper.tkr_mono
    except:
        return None
    base = tkr.base
    nsec = tkr.xtime_nsec
    nsec >>= tkr.shift
    return base+nsec

# This is a good estimate if available as when HZ=1000 this should be
# usually accurate enough
def sched_clock_j():
    return ktime_t(PYKD.last_jiffies_update)

sched_clock = sched_clock_j

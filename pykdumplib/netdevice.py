#!/usr/bin/env python
#
# Copyright (c) 2016 Hewlett-Packard Development Company, L.P.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

#
# Net device functions
#

from __future__ import print_function

from pykdump.API import *
from pykdump.linux import kernel
from pykdump import utils


@utils.singleton
class Device(object):
    '''
    Net device class
    '''
    struct_type = 'struct net_device'

    def __init__(self, obj):
        self.struct = obj
        self.name = obj.name

    def refcnt(self, cpu=None):
        '''
        Return the (per-cpu) reference count
        '''
        if cpu is None:
            # Return the sum of all ref counts
            refcnt = 0
            for cpu in kernel.for_each_possible_cpu():
                p = kernel.per_cpu_ptr(self.struct.pcpu_refcnt, cpu)
                refcnt += readS32(p)
            return refcnt
        else:
            p = kernel.per_cpu_ptr(self.struct.pcpu_refcnt, cpu)
            return readS32(p)

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
# Low-level kernel functions
#
# - arch/x86/include/asm/bitops.h
# - arch/x86/kernel/setup_percpu.c
# - include/linux/cpumask.h
# - include/linux/kernel.h
#

# TODO(juergh): Read kernel config file

from __future__ import print_function

from pykdump.API import *

NR_CPUS = 512
nr_cpumask_bits = NR_CPUS

BITS_PER_LONG = 64

cpu_possible_mask = readSymbol('cpu_possible_mask')
nr_cpu_ids = readSymbol('nr_cpu_ids')


def BITMAP_FIRST_WORD_MASK(start):
    return (~0 << (start & (BITS_PER_LONG - 1)))


def per_cpu_offset(cpu):
    return readSymbol('__per_cpu_offset')[cpu]


def per_cpu_ptr(ptr, cpu):
    return ptr + per_cpu_offset(cpu)


def cpumask_check(cpu):
    if cpu >= nr_cpumask_bits:
        print('Warning: cpu >= nr_cpumask_bits')


def round_down(x, y):
    return x & ~(y - 1)


def __ffs(word):
    '''
    __ffs - find first set bit in word
    @word: The word to search

    Undefined if no bit exists, so code should check against 0 first.
    '''
    if word == 0:
        print('Warning: word == 0')
    for i in range(0, BITS_PER_LONG):
        if (word >> i) & 0x1:
            return i


def _find_next_bit(addr, nbits, start, invert):
    '''
    This is a common helper function for find_next_bit and
    find_next_zero_bit.  The difference is the "invert" argument, which
    is XORed with each fetched word before searching it for one bits.
    '''
    if nbits == 0 or start >= nbits:
        return nbits

    tmp = addr[int(start / BITS_PER_LONG)] ^ invert

    # Handle 1st word
    tmp &= BITMAP_FIRST_WORD_MASK(start)
    start = round_down(start, BITS_PER_LONG)

    while tmp == 0:
        start += BITS_PER_LONG
        if (start >= nbits):
            return nbits

        tmp = addr[int(start / BITS_PER_LONG)] ^ invert

    return min(start + __ffs(tmp), nbits)


def find_next_bit(addr, size, offset):
    return _find_next_bit(addr, size, offset, 0)


def cpumask_next(n, srcp):
    '''
    cpumask_next - get the next cpu in a cpumask
    @n: the cpu prior to the place to search (ie. return will be > @n)
    @srcp: the cpumask pointer

    Returns >= nr_cpu_ids if no further cpus set.
    '''
    if n != -1:
        cpumask_check(n)
    return find_next_bit(srcp.bits, nr_cpumask_bits, n + 1)


def for_each_cpu(mask):
    '''
    for_each_cpu - iterate over every cpu in a mask
    @cpu: the (optionally unsigned) integer iterator
    @mask: the cpumask pointer
    '''
    cpu = -1
    while True:
        cpu = cpumask_next(cpu, mask)
        if cpu >= nr_cpu_ids:
            break
        yield cpu


def for_each_possible_cpu():
    return for_each_cpu(cpu_possible_mask)

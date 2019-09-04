#!/usr/bin/env python3
#
# Copyright (c) 2019 Canonical Ltd.
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

# File: arch/s390/include/asm/page.h

_PAGE_SHIFT = 12
_PAGE_SIZE  = (1 << _PAGE_SHIFT)

PAGE_SHIFT = _PAGE_SHIFT
PAGE_SIZE  = _PAGE_SIZE

def pte_val(x): return ((x).pte)
def pmd_val(x): return ((x).pmd)
def pud_val(x): return ((x).pud)
def p4d_val(x): return ((x).p4d)
def pgd_val(x): return ((x).pgd)

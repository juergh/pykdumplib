#!/usr/bin/env python3
#
# Copyright (c) 2019 Canonical Ltd.
# Copyright (c) 2016 Hewlett Packard Enterprise Development, L.P.
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

# File: /arch/s390/include/asm/pgtable.h

_PAGE_NOEXEC  = 0x100
_PAGE_PROTECT = 0x200
_PAGE_INVALID = 0x400
_PAGE_LARGE   = 0x800

_REGION_ENTRY_ORIGIN    = ~0xfff
_REGION_ENTRY_PROTECT	= 0x200
_REGION_ENTRY_NOEXEC    = 0x100
_REGION_ENTRY_INVALID   = 0x20
_REGION_ENTRY_TYPE_MASK = 0x0c
_REGION_ENTRY_TYPE_R1   = 0x0c
_REGION_ENTRY_TYPE_R2   = 0x08
_REGION_ENTRY_TYPE_R3   = 0x04

_REGION2_ENTRY_EMPTY = (_REGION_ENTRY_TYPE_R2 | _REGION_ENTRY_INVALID)
_REGION3_ENTRY_EMPTY = (_REGION_ENTRY_TYPE_R3 | _REGION_ENTRY_INVALID)

_REGION3_ENTRY_LARGE = 0x0400

_SEGMENT_ENTRY_ORIGIN  = ~0x7ff
_SEGMENT_ENTRY_PROTECT = 0x200
_SEGMENT_ENTRY_NOEXEC  = 0x100
_SEGMENT_ENTRY_INVALID = 0x20

_SEGMENT_ENTRY       = (0)
_SEGMENT_ENTRY_EMPTY = (_SEGMENT_ENTRY_INVALID)

_SEGMENT_ENTRY_LARGE = 0x0400

_CRST_ENTRIES = 2048
_PAGE_ENTRIES = 256

_REGION1_SHIFT = 53
_REGION2_SHIFT = 42
_REGION3_SHIFT = 31
_SEGMENT_SHIFT = 20

_REGION1_SIZE = (1 << _REGION1_SHIFT)
_REGION2_SIZE = (1 << _REGION2_SHIFT)
_REGION3_SIZE = (1 << _REGION3_SHIFT)
_SEGMENT_SIZE = (1 << _SEGMENT_SHIFT)

PMD_SHIFT   = _SEGMENT_SHIFT
PUD_SHIFT   = _REGION3_SHIFT
P4D_SHIFT   = _REGION2_SHIFT
PGDIR_SHIFT = _REGION1_SHIFT

PMD_SIZE   = _SEGMENT_SIZE
PUD_SIZE   = _REGION3_SIZE
P4D_SIZE   = _REGION2_SIZE
PGDIR_SIZE = _REGION1_SIZE

PTRS_PER_PTE = _PAGE_ENTRIES
PTRS_PER_PMD = _CRST_ENTRIES
PTRS_PER_PUD = _CRST_ENTRIES
PTRS_PER_P4D = _CRST_ENTRIES
PTRS_PER_PGD = _CRST_ENTRIES

def pgd_folded(pgd):
    return (pgd_val(pgd) & _REGION_ENTRY_TYPE_MASK) < _REGION_ENTRY_TYPE_R1

def pgd_none(pgd):
    if (pgd_folded(pgd)):
        return 0
    return (pgd_val(pgd) & _REGION_ENTRY_INVALID) != 0

def p4d_folded(p4d):
    return (p4d_val(p4d) & _REGION_ENTRY_TYPE_MASK) < _REGION_ENTRY_TYPE_R2

def p4d_none(p4d):
    if (p4d_folded(p4d)):
        return 0
    return p4d_val(p4d) == _REGION2_ENTRY_EMPTY

def pud_folded(pud):
    return (pud_val(pud) & _REGION_ENTRY_TYPE_MASK) < _REGION_ENTRY_TYPE_R3

def pud_none(pud):
    if (pud_folded(pud)):
        return 0
    return pud_val(pud) == _REGION3_ENTRY_EMPTY

def pud_large(pud):
    if ((pud_val(pud) & _REGION_ENTRY_TYPE_MASK) != _REGION_ENTRY_TYPE_R3):
        return 0
    return (pud_val(pud) & _REGION3_ENTRY_LARGE) != 0

def pmd_none(pmd):
    return pmd_val(pmd) == _SEGMENT_ENTRY_EMPTY

def pmd_large(pmd):
    return (pmd_val(pmd) & _SEGMENT_ENTRY_LARGE) != 0

def pgd_index(address): return (((address) >> PGDIR_SHIFT) & (PTRS_PER_PGD-1))
def p4d_index(address): return (((address) >> P4D_SHIFT) & (PTRS_PER_P4D-1))
def pud_index(address): return (((address) >> PUD_SHIFT) & (PTRS_PER_PUD-1))
def pmd_index(address): return (((address) >> PMD_SHIFT) & (PTRS_PER_PMD-1))
def pte_index(address): return (((address) >> PAGE_SHIFT) & (PTRS_PER_PTE-1))

def pgd_offset(mm, address): return ((mm).pgd + pgd_index(address))
def pgd_offset_k(address): return pgd_offset(readSymbol("init_mm"), address)

def pmd_deref(pmd): return (pmd_val(pmd) & _SEGMENT_ENTRY_ORIGIN)
def pud_deref(pud): return (pud_val(pud) & _REGION_ENTRY_ORIGIN)
def p4d_deref(pud): return (p4d_val(pud) & _REGION_ENTRY_ORIGIN)
def pgd_deref(pgd): return (pgd_val(pgd) & _REGION_ENTRY_ORIGIN)

def p4d_offset(pgd, address):
    p4d = pgd
    if ((pgd_val(pgd) & _REGION_ENTRY_TYPE_MASK) == _REGION_ENTRY_TYPE_R1):
        p4d = pgd_deref(pgd)
    return readSU("p4d_t", p4d) + p4d_index(address)

def pud_offset(p4d, address):
    pud = p4d
    if ((p4d_val(p4d) & _REGION_ENTRY_TYPE_MASK) == _REGION_ENTRY_TYPE_R2):
        pud = p4d_deref(p4d);
    return readSU("pud_t", pud) + pud_index(address)

def pmd_offset(pud, address):
    pmd = pud
    if ((pud_val(pud) & _REGION_ENTRY_TYPE_MASK) == _REGION_ENTRY_TYPE_R3):
        pmd = pud_deref(pud);
    return readSU("pmd_t", pmd) + pmd_index(address)

# Find an entry in the lowest level page table..
def pte_offset(pmd, addr): return readSU("pte_t", pmd_deref(pmd)) + pte_index(addr)
def pte_offset_kernel(pmd, address): return pte_offset(pmd, address)

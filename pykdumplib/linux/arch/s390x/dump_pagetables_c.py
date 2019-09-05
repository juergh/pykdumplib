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

from pykdump.API import *

from pykdumplib import utils
utils.include("page_h")
utils.include("pgtable_h")

__PAGE_BAD = "__PAGE_BAD"

# File: arch/s390x/mm/dump_pagetables.c

g_max_addr = 0

class addr_marker():
    def __init__(self, start_address, name):
        self.start_address = start_address
        self.name = name

# enum address_marker_idx
IDENTITY_NR = 0
KERNEL_START_ADDR = 1
KERNEL_END_ADDR = 2
# FIXEME: (juergh) Kasan
VMEMMAP_NR = 3
VMALLOC_NR = 4
MODULES_NR = 5

g_address_markers = [
    addr_marker(0, "Identity Mapping"),
    addr_marker(readSymbol('_stext'), "Kernel Image Start"),
    addr_marker(readSymbol('_end'), "Kernel Image End"),
    # FIXME: (juergh) Kasan
    addr_marker(0, "vmemmap Area"),
    addr_marker(0, "vmalloc Area"),
    addr_marker(0, "Modules Area"),
    addr_marker(sys.maxsize, ""),
]

class pg_state():
    def __init__(self):
        self.level = 0
        self.current_prot = 0
        self.start_address = 0
        self.current_address = 0
        self.marker = 0

def print_prot(pr, level):
    level_name = ("ASCE", "PGD", "PUD", "PMD", "PTE")

    fmt = "{:4s} {:2s} {:2s} ({:08x})"
    if pr == __PAGE_BAD:
        a1 = "B!"
        a2 = ""
    elif pr & _PAGE_INVALID:
        a1 = "I"
        a2 = ""
    else:
        a1 = "RO" if (pr & _PAGE_PROTECT) else "RW"
        a2 = "NX" if (pr & _PAGE_NOEXEC)  else "X"
    print(fmt.format(level_name[level], a1, a2, pr))

def note_page(st, new_prot, level):
    units = "KMGTPE "

    prot = new_prot
    cur = st.current_prot

    if not st.level:
        # First entry
        st.current_prot = new_prot
        st.level = level
        st.marker = g_address_markers
        print("---[ {:s} ] ---".format(st.marker[0].name))
    elif prot != cur or level != st.level or \
         st.current_address >= st.marker[1].start_address:
        # Print the actual finished series
        print("0x{:016x}-0x{:016x} ".format(st.start_address,
                                            st.current_address), end='')
        delta = (st.current_address - st.start_address) >> 10
        while (not (delta & 0x3ff)) and units[1] != ' ':
            delta >>= 10
            units = units[1:]
        print("{:9d}{:s} ".format(delta, units[0]), end='')
        print_prot(st.current_prot, st.level)
        while st.current_address >= st.marker[1].start_address:
            st.marker.pop(0)
            print("--- [ {:s} ] ---".format(st.marker[0].name))
        st.start_address = st.current_address
        st.current_prot = new_prot
        st.level = level

def walk_pte_level(st, pmd, addr):
    for i in range(0, PTRS_PER_PTE):
        if addr >= g_max_addr:
            break
        st.current_address = addr
        pte = pte_offset_kernel(pmd, addr)
        prot = pte_val(pte) & \
            (_PAGE_PROTECT | _PAGE_INVALID | _PAGE_NOEXEC)
        note_page(st, prot, 4)
        addr += PAGE_SIZE

def walk_pmd_level(st, pud, addr):
    # FIXME: (juergh) Check for CONFIG_KASAN
    for i in range(0, PTRS_PER_PMD):
        if addr >= g_max_addr:
            break
        st.current_address = addr
        pmd = pmd_offset(pud, addr)
        if pmd_bad(pmd):
            note_page(st, __PAGE_BAD, 3)
        elif not pmd_none(pmd):
            if pmd_large(pmd):
                prot = pmd_val(pmd) & \
                    (_SEGMENT_ENTRY_PROTECT |
                     _SEGMENT_ENTRY_NOEXEC)
                note_page(st, prot, 3)
            else:
                walk_pte_level(st, pmd, addr)
        else:
            note_page(st, _PAGE_INVALID, 3)
        addr += PMD_SIZE

def walk_pud_level(st, p4d, addr):
    # FIXME: (juergh) Check for CONFIG_KASAN
    for i in range (0, PTRS_PER_PUD):
        if addr >= g_max_addr:
            break
        st.current_address = addr
        pud = pud_offset(p4d, addr)
        if pud_bad(pud):
            note_page(st, __PAGE_BAD, 2)
        elif not pud_none(pud):
            if pud_large(pud):
                prot = pud_val & \
                    (_REGION_ENTRY_PROTECT |
                     _REGION_ENTRY_NOEXEC)
                note_page(st, prot, 2)
            else:
                walk_pmd_level(st, pud, addr)
        else:
            note_page(st, _PAGE_INVALID, 2)
        addr += PUD_SIZE

def walk_p4d_level(st, pgd, addr):
    # FIXME: (juergh) Check for CONFIG_KASAN
    for i in range(0, PTRS_PER_P4D):
        if addr >= g_max_addr:
            break
        st.current_address = addr
        p4d = p4d_offset(pgd, addr)
        if p4d_bad(p4d):
            note_page(st, __PAGE_BAD, 2)
        elif not p4d_none(p4d):
            walk_pud_level(st, p4d, addr)
        else:
            not_page(st, _PAGE_INVALID, 2)
        addr += P4D_SIZE

def walk_pgd_level():
    addr = 0

    st = pg_state()
    for i in range(0, PTRS_PER_PGD):
        if addr >= g_max_addr:
            break
        st.current_address = addr
        pgd = pgd_offset_k(addr)
        if pgd_bad(pgd):
            note_page(st, __PAGE_BAD, 2)
        elif not pgd_none(pgd):
            walk_p4d_level(st, pgd, addr)
        else:
            note_page(st, _PAGE_INVALID, 1)
        addr += PGDIR_SIZE

    # Flush out the last page
    st.current_address = g_max_addr
    note_page(st, 0, 0);

def ptdump_show(max_addr=0):
    global g_max_addr
    global g_address_markers

    if max_addr == 0:
        S390_lowcore = readSU("struct lowcore", 0)
        if S390_lowcore.kernel_asce == 0:
            print("Warning: S390_lowcore.kernel_asce = 0")

        g_max_addr = (S390_lowcore.kernel_asce & _REGION_ENTRY_TYPE_MASK) >> 2
        g_max_addr = 1 << (max_addr * 11 + 31)
    else:
        g_max_addr = max_addr

    g_address_markers[MODULES_NR].start_address = readSymbol("MODULES_VADDR")
    g_address_markers[VMEMMAP_NR].start_address = Addr(readSymbol("vmemmap"))
    g_address_markers[VMALLOC_NR].start_address = readSymbol("VMALLOC_START")

    walk_pgd_level()

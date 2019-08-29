# !/usr/bin/env python
# -*- coding: utf-8 -*-
# module LinuxDump.Analysis
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
This is a package providing subroutines to analyse processes interdependicies,
locks etc. These subroutines can be used in different top-level programs
'''
import textwrap
import operator

from pykdump.API import *

from LinuxDump.inet import proto
from LinuxDump.Tasks import (TaskTable, Task, tasksSummary, ms2uptime,
                             decode_tflags, decode_waitq, TASK_STATE)

from LinuxDump.fregsapi import (search_for_registers, DisasmFlavor)
from LinuxDump.BTstack import (exec_bt, verifyFastSet)


# Print processes waiting for UNIX sockets (usually syslog /dev/log)
def print_wait_for_AF_UNIX(v=0):
    tt = TaskTable()

    # Part I - find all Unix sockets with peers
    peers_dict = defaultdict(list)              # peer-> (task, sock) list
    socks_dict = defaultdict(list)              # sock-> owners
    for t in tt.allTasks():
        once = TrueOnce(1)
        try:
            task_fds = t.taskFds()
        except crash.error:
            # page excluded
            continue
        last_ran = float(t.Ran_ago)/1000
        for fd, filep, dentry, inode in task_fds:
            socketaddr = proto.inode2socketaddr(inode)
            if (not socketaddr): continue

            socket = readSU("struct socket", socketaddr)
            sock = Deref(socket.sk)
            family, sktype, protoname, inet = proto.decodeSock(sock)
            if (family != proto.P_FAMILIES.PF_FILE):
                continue

            # AF_UNIX. on 2.4 we have just 'struct sock',
            # on 2.6 'struct unix_sock'
            if (not proto.sock_V1):
                sock = sock.castTo("struct unix_sock")

            #u_sock = readSU("struct unix_sock", 0xffff81073a7c3180)
            state, ino, path = proto.unix_sock(sock)
            socks_dict[sock].append((last_ran, t))
            # Check whether we have a peer
            peer = sock.Peer
            if (peer):
                peers_dict[peer].append((t, sock))

    # Part II - look at all peers
    nonempty_tasklist = []
    for peer, lst in peers_dict.items():
        state, ino, path = proto.unix_sock(peer)
        #if (path != "/dev/log"):
        #    continue
        #sleep = peer.sk.sk_sleep
        try:
            waitq = peer.peer_wait
        except:
            waitq = peer.peer_wq.wait
        tasklist = decode_waitq(waitq)
        if (tasklist):
            owners = sorted(socks_dict[peer])
            if (not owners):
                pylog.warning("Cannot find a socket for peer {}".format(peer))
                continue
            last_ran, t = owners[0]
            # Sanitize tasklist in case it has corrupted pointers
            ntasklist = []
            pids = []
            for tt in tasklist:
                try:
                    pids.append(tt.pid)
                    ntasklist.append(tt)
                except:
                    pylog.warning("Corrupted waitq of", peer)
            tasklist = ntasklist
            state, ino, path = proto.unix_sock(peer)
             # if last_ran is greater than this, issue a warning
            __max_time = 5
            stack = t.get_task_stack()
            if (stack.hasfunc("console_lock")):
                pylog.warning("Syslog daemon is waiting for serial console")
                print(stack)
            if (v < 1 and last_ran < __max_time):
                continue
            if (v < 1 and path == "/dev/log"):
                # Just issue warnings
                msg = ("A problem with syslog daemon <{}> pid={} state={}\n"
                    "       It ran {:5.2f}s ago and {} processes"
                    " are waiting for it"
                     "".format(t.comm, t.pid,
                                                t.state[5:7], last_ran,
                                                len(tasklist)))
                if (v < 0):
                    msg += ("\n       Run 'hanginfo --syslogger -v' to get"
                                " more details")
                if (t.pid in pids):
                    msg += ("\n       Task pid={} CMD={} is waiting for"
                    " its own socket".format(t.pid, t.comm))

                pylog.warning(msg)
                if (v < 0):
                    return

            print(" -- Socket we wait for: {} {}".format(peer, path))
            print("   Youngest process with this socket <{}> pid={}({}) ran "
                "{:5.2f}s ago".format(t.comm, t.pid, t.state[5:7], last_ran))
            # Tasklist has been already sanitized getting rid of those
            # elements where we have been unable to deref task.pid
            if (tasklist):
                print("   ...  {} tasks waiting for this socket".\
                    format(len(tasklist)))

                if (v > 0):
                    for task in sorted(tasklist, key=operator.attrgetter('pid')):
                        print("     pid=%7d   CMD=%s" % (task.pid, task.comm))
            else:
                print("     cannot print tasks as socket wait queue is corrupted")

    #if (once):
    #    print("--pid={} comm={} ran {:5.2f}s ago".format(t.pid, t.comm, last_ran))

def __print_pids(spids, h = ""):
    # convert list of integers and strings
    out = []
    for e in spids:
        out.append(str(e))
    spids = '[' + ', '.join(out) + ']'
    print(textwrap.fill(h + str(spids), initial_indent=' '*6,
                    subsequent_indent=' ' *7))

# Print pidlists. As these lists can be both short and lengthy, we can control
# what is printed using the following keywords:
# sortbytime True/False
#        True - youngest first
#        False - lower pid first
# maxpids - how many pids to print. If sorted by time, print first 'maxpids/2' and
#           last 'maxpids/2'
# verbose
def print_pidlist(pids, title = '', verbose = False, maxpids = 10,
                  sortbytime = True, statefilter = None):
    npids = len(pids)
    if (npids < 1):
        return
    # Prepare a list of (ran_ms_ago, pid) list to sort them
    mlist = []
    T_table = TaskTable()
    for pid in pids:
        t = T_table.getByTid(pid)
        if (statefilter):
            state = t.state[5:7]
            if (state in statefilter):
                mlist.append((int(t.Ran_ago), pid))
        else:
            mlist.append((int(t.Ran_ago), pid))
    mlist = sorted(mlist)
    # Youngest and oldest
    if (not mlist):
        print("  no Pids")
        return
    ago_y, pid_y = mlist[0]
    ago_o, pid_o = mlist[-1]

    print("    ... {} pids. Youngest,oldest: {}, {}  Ran ms ago:"
        " {}, {}".format(npids, pid_y, pid_o, ago_y, ago_o))

    if (maxpids < 1):
        return
    if (npids > maxpids):
        print("        printing {} out of {}".format(maxpids, npids))
    if (sortbytime):
        # ............. sorted by time ................................
        if (npids > maxpids):
            n1 = maxpids//2
            n2 = maxpids - n1
            ml1 = mlist[:n1]
            ml2 = mlist[-n2:]
            skipped = npids-maxpids
            mlp = ml1 + [(None, "<{} skipped>".format(skipped))] + ml2
        else:
            mlp = mlist
        if (verbose):
            print ("     PID          CMD       CPU   Ran ms ago   STATE")
            print ("    --------   ------------  --  ------------- -----")
            for tago, pid in mlp:
                if (tago is not None):
                    t = T_table.getByTid(pid)
                    comm = str(t.comm)[:11]
                    state = t.state[5:7]
                    print("    {:8d}  {:12s}  {:3d} {:10d}      {}".\
                        format(pid, comm, t.cpu, tago, state))
                else:
                    print("             {}".format(pid))
        else:
            print("        sorted by ran_ago, youngest first".format(npids))
            mlp_s = [pid for (ts, pid) in mlp]
            __print_pids(mlp_s, title)


    else:
        # ............. sorted by pid .................................
        pids = sorted(pids)
        if (npids > maxpids):
            n1 = maxpids//2
            n2 = maxpids - n1
            ml1 = pids[:n1]
            ml2 = pids[-n2:]
            mlp = ml1 + ["..." ] + ml2
        else:
            mlp = pids
        print("        sorted by pid")
        __print_pids(mlp, title)


# Check whether we have a hang: there should be at least 3 old UN threads
__OLD_AGO = 120000      # in ms, we consider such threads old
def check_possible_hang():
    T_table = TaskTable()
    pids_UN = {t.pid for t in T_table.allThreads() \
        if t.ts.state & TASK_STATE.TASK_UNINTERRUPTIBLE}
    tot_UN = len(pids_UN)
    # Now check how many pids are older than 120s
    mlist = []
    for pid in pids_UN:
        t = T_table.getByTid(pid)
        mlist.append((t.Ran_ago, pid))
    mlist = sorted(mlist)
    n_old = 0
    for ran_ago, pid in mlist[-10:]:
        if (ran_ago > __OLD_AGO):
            n_old += 1
    if (n_old > 1):
        pylog.warning("Possible hang")
    return n_old



# Check for memory pressure subroutines
# We report memory pressure in one of two following cases:
#   there is at least one UN thread trying to get memory
#   the threads are not necessarily in UN, but there are many of them
__mp_names = "shrink_all_zones|shrink_zone|balance_dirty_pages"
def check_memory_pressure(_funcpids):
    subpids = _funcpids(__mp_names)
    if (not subpids):
        return False
    if (len(subpids) < 100):
        verifyFastSet(subpids, __mp_names)
    d = defaultdict(int)
    total = 0
    T_table = TaskTable()
    for pid in subpids:
        t = T_table.getByTid(pid)
        d[t.state] += 1
        total += 1
    if ("TASK_UNINTERRUPTIBLE" in d or total > 20):
        pylog.warning("Memory pressure detected")
        print("  *** {} ***".format(__mp_names))
        for k, v in d.items():
            print ("   {:4d} in {} state".format(v, k))
        return True

# Check for hanging nfsd threads
def check_hanging_nfsd(_funcpids):
    subpids = _funcpids("nfsd")
    d = defaultdict(int)
    total = 0
    T_table = TaskTable()
    for pid in subpids:
        t = T_table.getByTid(pid)
        d[t.state] += 1
        total += 1
    if ("TASK_UNINTERRUPTIBLE" in d):
        pylog.warning("Hanging nfsd threads")
        return True
    else:
        return False



# SAP HANA specific things.

# Check whether this is SAP HANA
# Return 0 - no
#        1 - SAP, no HANA
#        2 - SAP HANA
def check_saphana():
    T_table = TaskTable()
    sap  = T_table.getByComm("sapstart")
    hana = T_table.getByComm("hdbindexserver")
    if (sap and hana):
        return 2
    elif (sap):
        return 1
    else:
        return 0


__ARG_REG = ('RDI','RSI','RDX','RCX','R8','R9')
@memoize_cond(CU_LIVE|CU_LOAD)
def get_tentative_arg(pid, funcname, argN):
    foundarg = None
    s = exec_bt("foreach {} bt".format(pid), MEMOIZE=False)[0]

    with DisasmFlavor('att'):
        search_for_registers(s)
        for f in s.frames:
            if (funcname not in f.func):
                continue

            if(f.lookup_regs):
                for reg in f.reg:
                    if (not reg in __ARG_REG):
                        continue
                    if (__ARG_REG.index(reg) == argN):
                        addr, conf = f.reg[reg]
                        foundarg = addr
                        break
    return foundarg

# For a given pid, try extracting only some interesting arguments
# We are interested only in struct pointers
__re_struct = re.compile(r'^(struct [\da-zA-Z_]+) \*$')

# Generates (funcname, sname, addr) tuples
def get_interesting_arguments(pid, re_funcnames, re_ctypes):
    __ARG_REG = ('RDI','RSI','RDX','RCX','R8','R9')
    s = exec_bt("bt {}".format(pid), MEMOIZE=False)[0]
    with DisasmFlavor('att'):
        #search_for_registers(s, re_funcnames)
        #for f in s.frames:
        for f in search_for_registers(s, re_funcnames):
            #print(f.func)
            #if (not re_funcnames.search(f.func)):
            #    continue
            if(f.lookup_regs):
                once = TrueOnce(1)
                if (not f.func):
                    continue
                argprotos = funcargs(f.func)
                if (not argprotos):
                    continue
                nargs = len(argprotos)
                #print(f.func, argprotos)
                for reg in f.reg:
                    if (not reg in __ARG_REG or not f.func):
                        continue
                    index = __ARG_REG.index(reg)
                    if (index >= nargs):
                        continue
                    ctype = argprotos[index]
                    if (not re_ctypes.search(ctype)):
                        continue
                    #if (once):
                        #print(f.func)
                    addr = f.reg[reg][0]
                    #print('  {} {} {:#x}'.format(index, reg, addr))
                    #print('    ', ctype)
                    m = __re_struct.match(ctype)
                    if (not m):
                        continue
                    sname = m.group(1)
                    yield (f.func, sname, addr)

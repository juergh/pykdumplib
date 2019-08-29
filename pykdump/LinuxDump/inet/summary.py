
# module LinuxDump.inet.summary
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
This is a package printing various summaries of networking subsystems.
These summaries are used both in 'xportshow' and 'crashinfo'
'''

from pykdump.API import *
from LinuxDump.inet import (proto, netdevice)

from LinuxDump.inet.proto import (tcpState, sockTypes,
     IP_sock,  P_FAMILIES)

import itertools




# Print a summary of TCP/IP subsystem
def TCPIP_Summarize(quiet = False):
    if (not quiet):
        print ("TCP Connection Info")
        print ("-------------------")
    counts = {}

    # LISTEN
    lqfull = 0                          # Listen Queue Full
    lqne = 0                            # Listen Queue Non-Empty
    udata = 0                           # Socks with user_data set
    for o in proto.get_TCP_LISTEN():
        pylog.silenterror("TCP_LISTEN")
        pstr = IP_sock(o, True)
        counts[pstr.state] = counts.setdefault(pstr.state, 0) + 1
        if (pstr.user_data):
            udata += 1
        if (pstr.sk_ack_backlog):
            lqne += 1
            if (pstr.sk_ack_backlog == pstr.sk_max_ack_backlog):
                lqfull += 1
    
    # ESTABLISHED TCP

    # How 'nonagle' is used on Linux: TCP_NODELAY sets 1
    #define TCP_NAGLE_OFF  1  /* Nagle's algo is disabled */
    #define TCP_NAGLE_CORK 2  /* Socket is corked           */
    #define TCP_NAGLE_PUSH 4  /* Cork is overridden for already queued data */

    nodelay = 0
    w_rcv_closed = 0
    w_snd_closed = 0
    n_retrans = 0           # how many connections are in retransmission
    tcp_max_retrans = 0     # maximum number of retranmissions on any socket

    # Process ESTABLISHED + TIME_WAIT
    all_tcp = itertools.chain(proto.get_TCP_ESTABLISHED(),
                             proto.get_TCP_TIMEWAIT())
    for o, otype in  all_tcp :
        pylog.silenterror("TCP_ESTABLISHED")
        try:
            if (otype == "tcp"):
                pstr = IP_sock(o, True)
            elif (otype == "tw"):
                pstr = proto.IP_conn_tw(o, True)
            elif (otype == "rqs"):
                pstr = proto.IP_rqs(o, True)
            else:
                pylog.error("Unknown socket type")
                continie
        except KeyError as msg:
            pylog.error(msg)
            continue
        if (otype == "tcp"):
            if (pstr.protocol != 6):
                pylog.warning("non-TCP socket in TCP-hash", o, pstr.protocol)
                continue
            counts[pstr.state] = counts.setdefault(pstr.state, 0) + 1
            if (pstr.user_data):
                udata += 1
            #nonagle=pstr.Tcp.nonagle
            nonagle = pstr.topt.nonagle
            if (nonagle == 1):
                nodelay += 1
            snd_wnd = pstr.topt.snd_wnd
            rcv_wnd = pstr.topt.rcv_wnd
            if (rcv_wnd == 0):
                w_rcv_closed += 1
            if (snd_wnd == 0):
                w_snd_closed += 1
            if (pstr.Retransmits):
                n_retrans += 1
                tcp_max_retrans = max(tcp_max_retrans, pstr.Retransmits)
        elif (otype == "tw"):
            # TIME_WAIT
            jiffies = readSymbol("jiffies")
            counts[pstr.state] = counts.setdefault(pstr.state, 0) + 1
        elif (otype == "rqs"):
            # NEW_SYN_RECV
            counts[pstr.state] = counts.setdefault(pstr.state, 0) + 1

    states = sorted(counts.keys())
    if (not quiet):
        for s in states:
            print ("    %15s  %5d" % (tcpState[s][4:], counts[s]))
        if (nodelay):
            print ("\t\t\tNAGLE disabled (TCP_NODELAY): %5d" % nodelay)
        if (udata):
            print ("\t\t\tuser_data set (NFS etc.):     %5d" % udata)
        
    if  (lqne or lqfull or w_rcv_closed or w_rcv_closed or n_retrans):
        print ("")
        print ("  Unusual Situations:")
    if (lqne):
        print ("    Listen Queue Non-Empty:    {:5d}".format(lqne))
    if (lqfull):
        print ("    Listen Queue Full:         {:5d}".format(lqfull))
    if (w_rcv_closed):
        print ("    Receive Window Closed:     {:5d}".format(w_rcv_closed))
    if (w_snd_closed):
        print ("    Send Window Closed:        {:5d}".format(w_snd_closed))
    if (n_retrans):
        print ("    Doing Retransmission:      {:5d}  {:s}".format\
               (n_retrans, "(run xportshow --retrans for details)"))
        if (tcp_max_retrans > 3):
            DCache.tmp.tcp_max_retrans = tcp_max_retrans
    if (not quiet):
        print ("\n\nUDP Connection Info")
        print ("-------------------")
    count = rcvfull = sndfull = established = 0
    udata = 0
    for o in proto.get_UDP():
        pylog.silenterror("UDP")
        pstr = IP_sock(o, True)
        count += 1
        if (pstr.user_data):
            udata += 1
        if (pstr.state == tcpState.TCP_ESTABLISHED):
            established += 1
        # Check whether buffers are full more than 50%
        if (pstr.rmem_alloc *100 >= pstr.rcvbuf * 75):
            rcvfull += 1
        if (pstr.wmem_alloc *100 >= pstr.sndbuf * 75):
            sndfull += 1
    if (not quiet):
        print ("  %d UDP sockets, %d in ESTABLISHED" % (count, established))
    if (not quiet and udata):
        print ("\t\t\tuser_data set (NFS etc.):     %5d" % udata)
    if (rcvfull or sndfull):
        pylog.warning("UDP buffer fill >=75%%  rcv=%d snd=%d" % (rcvfull, sndfull))
 
    if (quiet):
        return

    print ("\n\nUnix Connection Info")
    print ("------------------------")

    counts = {}
    count = 0
    for s in proto.get_AF_UNIX():
        state, ino, path = proto.unix_sock(s)
        counts[state] = counts.setdefault(state, 0) + 1
        count += 1
        
    states = sorted(counts.keys())
    for s in states:
        try:
            statename = tcpState[s][4:]
        except KeyError:
            statename = "|%d|" % s
            print (WARNING, "bogus TCP state", s)
        print ("    %15s  %5d" % (statename, counts[s]))

    print ("\n\nRaw sockets info")
    print ("--------------------")

    counts = {}
    for o in list(proto.get_RAW()) + list(proto.get_RAW6()):
        try:
            pstr = IP_sock(o, True)
        except KeyError as msg:
            pylog.error(msg)
            continue
        
        counts[state] = counts.setdefault(state, 0) + 1

    states = sorted(counts.keys())
    if (len(counts) == 0):
        print ("    None")
        

    for s in states:
        print ("    %15s  %5d" % (tcpState[s][4:], counts[s]))

    print ("\n\n")


# Compute delay between a given timestamp and jiffies
def __j_delay(ts, jiffies):
    v = (jiffies - ts) & INT_MASK
    if (v > INT_MAX):
        v = "     n/a"
    elif (v > HZ*3600*10):
        v = ">10hours"
    else:
        v = "%8.1f" % (float(v)/HZ)
    return v
    
# Print a summary of interface state

HZ = sys_info.HZ

def IF_Summarize(quiet = False):

    if (quiet):
        return
    print ("Interfaces Info")
    print ("---------------")
    dev_base_list = netdevice.dev_base_list()
    print ("  How long ago (in seconds) interfaces transmitted/received?")
    print ("\t  Name        RX          TX")
    print ("\t  ----    ----------    ---------")

    jiffies = readSymbol("jiffies")
    for dev in dev_base_list:
        try:
            last_rx = __j_delay(dev.last_rx, jiffies)
        except KeyError:
            last_rx = "n/a"
        if (dev.hasField("_tx")):
            trans_start = dev._tx.trans_start
        else:
            trans_start = dev.trans_start
        trans_start = __j_delay(trans_start, jiffies)
        print ("\t%8s    %s       %s"% ( dev.name, last_rx, trans_start))


    print ("\n\n")

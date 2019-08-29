# -*- coding: utf-8 -*-

# --------------------------------------------------------------------
# (C) Copyright 2006-2019 Hewlett Packard Enterprise Development LP
#
# Author: Alex Sidorenko <asid@hpe.com>
#
# --------------------------------------------------------------------

# Print info about NFS/RPC

__version__ = "1.1.1"

from collections import (Counter, OrderedDict, defaultdict)
import itertools
import operator

from pykdump.API import *

# For FS stuff
from LinuxDump.fs import *

# Mutex
from LinuxDump.KernLocks import decode_mutex

# For INET stuff
from LinuxDump.inet import *

from LinuxDump.inet import proto, netdevice
from LinuxDump.inet.proto import (tcpState, sockTypes,
        IP_sock,  P_FAMILIES, format_sockaddr_in, protoName)

# For NFS/RPC stuff
from LinuxDump.nfsrpc import *

# Time info
from LinuxDump.Time import *

# Decoding waitq
from LinuxDump.Tasks import decode_waitq

# Stacks info
from LinuxDump.BTstack import (exec_bt, bt_mergestacks, fastSubroutineStacks,
                               verifyFastSet)

# Arguments analysis
from LinuxDump.Analysis import (get_tentative_arg,
                                get_interesting_arguments)

# NFSv4-specific
import LinuxDump.fs.nfs4_fs_h as Nfs4

import string, struct
from socket import ntohl, ntohs, htonl, htons


debug = API_options.debug



NFS4_C = '''
#define NFSPROC4_NUL            0
#define NFSPROC4_COMPOUND       1
'''

NFS3_C = '''
#define NFS3PROC_NULL           0
#define NFS3PROC_GETATTR        1
#define NFS3PROC_SETATTR        2
#define NFS3PROC_LOOKUP         3
#define NFS3PROC_ACCESS         4
#define NFS3PROC_READLINK       5
#define NFS3PROC_READ           6
#define NFS3PROC_WRITE          7
#define NFS3PROC_CREATE         8
#define NFS3PROC_MKDIR          9
#define NFS3PROC_SYMLINK        10
#define NFS3PROC_MKNOD          11
#define NFS3PROC_REMOVE         12
#define NFS3PROC_RMDIR          13
#define NFS3PROC_RENAME         14
#define NFS3PROC_LINK           15
#define NFS3PROC_READDIR        16
#define NFS3PROC_READDIRPLUS    17
#define NFS3PROC_FSSTAT         18
#define NFS3PROC_FSINFO         19
#define NFS3PROC_PATHCONF       20
#define NFS3PROC_COMMIT         21
'''

NFS2_C = '''
#define NFSPROC_NULL            0
#define NFSPROC_GETATTR         1
#define NFSPROC_SETATTR         2
#define NFSPROC_ROOT            3
#define NFSPROC_LOOKUP          4
#define NFSPROC_READLINK        5
#define NFSPROC_READ            6
#define NFSPROC_WRITECACHE      7
#define NFSPROC_WRITE           8
#define NFSPROC_CREATE          9
#define NFSPROC_REMOVE          10
#define NFSPROC_RENAME          11
#define NFSPROC_LINK            12
#define NFSPROC_SYMLINK         13
#define NFSPROC_MKDIR           14
#define NFSPROC_RMDIR           15
#define NFSPROC_READDIR         16
#define NFSPROC_STATFS          17
'''

NFS2_PROCS = CDefine(NFS2_C)
NFS3_PROCS = CDefine(NFS3_C)
NFS4_PROCS = CDefine(NFS4_C)

#  * Reserved bit positions in xprt->state (3.10 kernel)
#  */
__XPRT_C = '''
#define XPRT_LOCKED             0
#define XPRT_CONNECTED          1
#define XPRT_CONNECTING         2
#define XPRT_CLOSE_WAIT         3
#define XPRT_BOUND              4
#define XPRT_BINDING            5
#define XPRT_CLOSING            6
#define XPRT_CONNECTION_ABORT   7
#define XPRT_CONNECTION_CLOSE   8
#define XPRT_CONGESTED          9
'''

__XPRT_BITS = CDefine(__XPRT_C)
# For 3.0 we need to replace XPRT_CONGESTED->XPRT_INITIALIZED
if (sys_info.kernel < "3.10.0"):
    __XPRT_BITS["XPRT_INITIALIZED"] = __XPRT_BITS["XPRT_CONGESTED"]
    del __XPRT_BITS["XPRT_CONGESTED"]

# Convert it to proper bits
XPRT_BITS = {k: 1<<v for k,v in __XPRT_BITS.items()}
#print(XPRT_BITS)
#print (dbits2str(17, XPRT_BITS))

__XPT_C = '''
#define XPT_BUSY        0               /* enqueued/receiving */
#define XPT_CONN        1               /* conn pending */
#define XPT_CLOSE       2               /* dead or dying */
#define XPT_DATA        3               /* data pending */
#define XPT_TEMP        4               /* connected transport */
#define XPT_DEAD        6               /* transport closed */
#define XPT_CHNGBUF     7               /* need to change snd/rcv buf sizes */
#define XPT_DEFERRED    8               /* deferred request pending */
#define XPT_OLD         9               /* used for xprt aging mark+sweep */
#define XPT_DETACHED    10              /* detached from tempsocks list */
#define XPT_LISTENER    11              /* listening endpoint */
#define XPT_CACHE_AUTH  12              /* cache auth info */
'''

__XPT_BITS = CDefine(__XPT_C)
# Convert it to proper bits
XPT_BITS = {k: 1<<v for k,v in __XPT_BITS.items()}
#print(XPT_BITS)

__NFSEXP_C = '''
#define NFSEXP_READONLY         0x0001
#define NFSEXP_INSECURE_PORT    0x0002
#define NFSEXP_ROOTSQUASH       0x0004
#define NFSEXP_ALLSQUASH        0x0008
#define NFSEXP_ASYNC            0x0010
#define NFSEXP_GATHERED_WRITES  0x0020
/* 40 80 100 currently unused */
#define NFSEXP_NOHIDE           0x0200
#define NFSEXP_NOSUBTREECHECK   0x0400
#define NFSEXP_NOAUTHNLM        0x0800          /* Don't authenticate NLM requests - just trust */
#define NFSEXP_MSNFS            0x1000  /* do silly things that MS clients expect; no longer supported */
#define NFSEXP_FSID             0x2000
#define NFSEXP_CROSSMOUNT       0x4000
#define NFSEXP_NOACL            0x8000  /* reserved for possible ACL related use */
#define NFSEXP_V4ROOT           0x10000
#define NFSEXP_ALLFLAGS         0x17E3F
'''

__NFSEXP_BITS = CDefine(__NFSEXP_C)

__EXPFLAGS = OrderedDict((
    ("NFSEXP_READONLY", ("ro", "rw")),
    ("NFSEXP_INSECURE_PORT", ("insecure", "")),
    ("NFSEXP_ROOTSQUASH", ("root_squash", "no_root_squash")),
    ("NFSEXP_ALLSQUASH", ("all_squash", "")),
    ("NFSEXP_ASYNC", ("async", "sync")),
    ("NFSEXP_GATHERED_WRITES", ("wdelay", "no_wdelay")),
    ("NFSEXP_NOHIDE", ("nohide", "")),
    ("NFSEXP_CROSSMOUNT", ("crossmnt", "")),
    ("NFSEXP_NOSUBTREECHECK", ("no_subtree_check", "")),
    ("NFSEXP_NOAUTHNLM", ("insecure_locks", "")),
    ("NFSEXP_V4ROOT", ("v4root", ""))
))



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

# To store IP-addr the older kernels use 'struct sockaddr_in,
# newer kernels use

#struct __kernel_sockaddr_storage {
#    short unsigned int ss_family;
#    char __data[126];
#}
# and it is casted to 'struct sockaddr'

def format_cl_addr(s):
    try:
        family = s.sin_family
        # This is sockaddr_in
        return ntodots(s.sin_addr.s_addr)
    except:
        family = s.ss_family
        if (family == P_FAMILIES.PF_INET):
            n = htonl(struct.unpack("I", s.__data[:4])[0])
            return ntodots(n)
        elif (family == P_FAMILIES.PF_INET6):
            pass
        return "???"



# -- get a generator for a cache with a given name. We iterate
# both through hash-table and its buckets and return non-null
# 'struct cache_head'
#
def getCache(cname):
    details = None
    cache_list = ListHead(sym2addr("cache_list"), "struct cache_detail")

    for c in cache_list.others:
        if (c.name == cname):
            details = c
            break
    if (not details):
        return

    # It is  struct cache_head **hash_table; on older kernels
    # but    struct hlist_head *hash_table; on newer ones (e.g. 4.4)
    #
    # Until we fix it properly, just return an empty table
    table = details.hash_table
    try:
        unsupported = not bool(table.hasField("next"))
    except AttributeError:
        unsupported = False
    if (unsupported):
        print ("No support yet for NFS cache details, will be added later")
        print("      {} {}".format(c.name, c))
        return []
    size = details.hash_size
    for i in range(size):
        ch1 = table[i]
        if (not ch1):
            continue
        ch1 = Deref(ch1)
        for ch in readStructNext(ch1, "next"):
            #print ch, ch.flags
            yield ch




# Getting addr form ip_map.m_addr
#struct in6_addr {
#    union {
#        __u8 u6_addr8[16];
#        __be16 u6_addr16[8];
#        __be32 u6_addr32[4];
#    } in6_u;
#}

#define CACHE_VALID     0       /* Entry contains valid data */
#define CACHE_NEGATIVE  1       /* Negative entry - there is no match for the key */
#define CACHE_PENDING   2       /* An upcall has been sent but no reply received yet*/

__CACHE_VALID = 0
__CACHE_NEGATIVE = 1
__CACHE_PENDING = 2

def test_bit(nbit, val):
    return ((val >> nbit) == 1)

def _test_cache(ch):
    #   if (test_bit(CACHE_VALID, &h->flags) &&
    #    !test_bit(CACHE_NEGATIVE, &h->flags))
    return (test_bit(__CACHE_VALID, ch.flags) and not
            test_bit(__CACHE_NEGATIVE, ch.flags))

def _test_cache_pending(ch):
    return test_bit(__CACHE_PENDING, ch.flags)


# static inline int key_len(int type)
# {
#       switch(type) {
#       case FSID_DEV:          return 8;
#       case FSID_NUM:          return 4;
#       case FSID_MAJOR_MINOR:  return 12;
#       case FSID_ENCODE_DEV:   return 8;
#       case FSID_UUID4_INUM:   return 8;
#       case FSID_UUID8:        return 8;
#       case FSID_UUID16:       return 16;
#       case FSID_UUID16_INUM:  return 24;
#       default: return 0;
#       }
# }

def key_len(t):
    if (t == __F.FSID_DEV):   return 8
    elif(t == __F.FSID_NUM):  return 4
    elif(t == __F.FSID_MAJOR_MINOR):    return 12
    elif(t == __F.FSID_ENCODE_DEV):     return 8
    elif(t == __F.FSID_UUID4_INUM):     return 8
    elif(t == __F.FSID_UUID8):  return 8
    elif(t == __F.FSID_UUID16): return 16
    elif(t == __F.FSID_UUID16_INUM):    return 24
    else: return 0

# Older kernels
def key_len_old(t):
    if (t == 0):   return 8
    elif(t == 1):  return 4
    elif(t == 2):       return 12
    elif(t == 3):       return 8
    else: return 0

# NFS Export Cache (as reported by /proc/net/rpc/nfsd.export/contents)
# #domain fsidtype fsid [path]
# 192.168.0/24 1 0x00000000 /
# 192.168.0/24 6 0x4b47467c994212335620b49e04ab2baf /data

def print_nfsd_fh(v=0):
    ip_table = getCache("nfsd.fh")
    print ("----- NFS FH (/proc/net/rpc/nfsd.fh)------------")
    if (v >= 0):
        print ("#domain fsidtype fsid [path]")
    entries = 0
    for ch in ip_table:
        ek = container_of(ch, "struct svc_expkey", "h")
        out = []
        out.append("%s %d 0x" %( ek.ek_client.name, ek.ek_fsidtype))
        #for (i=0; i < key_len(ek->ek_fsidtype)/4; i++)
        #       seq_printf(m, "%08x", ek->ek_fsid[i]);
        for i in range(key_len(ek.ek_fsidtype)//4):
            out.append("%08x" % ek.ek_fsid[i])

        if (_test_cache(ch)):
            # On older kernels we have ek.ek_mnt and ek.ek_dentry
            # On newer ones exp.ek_path.mnt and ek.ek_path.dentry
            try:
                path = ek.ek_path
                pathname = get_pathname(path.dentry, path.mnt)
            except:
                pathname = get_pathname(ek.ek_dentry, ek.ek_mnt)
            out.append(" " + pathname)
        s = "".join(out)
        entries += 1
        if (v >=0):
            print (s)

    if (v < 0):
        # Summary
        print("    {} entries".format(entries))

# Decode and print svc_export
#define EX_UUID_LEN             16
EX_UUID_LEN = 16
#       #192.168.0.0/24(ro,no_root_squash,sync,no_wdelay,no_subtree_check,v4root,fsid=0,
# uuid=b30dfe99:2e754043:92c9d2d2:e0bfaabf,sec=1)
#/data   192.168.0.0/24(rw,no_root_squash,async,wdelay,uuid=f24a2605:e915401a:b11dcefb:f823f865,sec=1)

def print_svc_export(exp):
    mask = __NFSEXP_BITS.NFSEXP_ALLFLAGS
    flags = exp.ex_flags & mask
    #print("mask={:#0x} flags={:#0x}".format(mask, flags))
    out = []
    for f in __EXPFLAGS.keys():
        bit = __NFSEXP_BITS[f]
        t = __EXPFLAGS[f]
        s = t[0] if flags&bit else t[1]
        if(s):
            out.append(s)
    if (flags & __NFSEXP_BITS.NFSEXP_FSID):
        out.append("fsid={}".format(exp.ex_fsid))

    # UUID
    if (exp.ex_uuid):
        out1 = ["uuid="]
        for i in range(EX_UUID_LEN):
            if ((i&3) == 0 and i):
                out1.append(':')
            out1.append("{:02x}".format(exp.ex_uuid[i]))
        uuid = ''.join(out1)
        out.append(uuid)

    # show_secinfo part

    # Now assemble options line and print it
    print(','.join(out))


# NFS Export Cache (as reported by /proc/net/rpc/nfsd.export/contents)
def print_nfsd_export(v=0):
    ip_table = getCache("nfsd.export")
    print ("----- NFS Exports (/proc/net/rpc/nfsd.export)------------")
    entries = 0
    tot_pending =  0
    for ch in ip_table:
        exp = container_of(ch, "struct svc_export", "h")
        pending = _test_cache_pending(ch)
        if (_test_cache(ch) or pending):
            # On older kernels we have exp.ex_mnt and exp.ex_dentry
            # On newer ones exp.ex_path.mnt and exp.exp_path.dentry
            try:
                path = exp.ex_path
                pathname = get_pathname(path.dentry, path.mnt)
            except:
                pathname = get_pathname(exp.ex_dentry, exp.ex_mnt)
            if (not pending):
                entries += 1
            else:
                tot_pending += 1
            if (v > 0):
                extra = "  {}".format(exp)
            else:
                extra = ""
            if (v >=0):
                pref = " (p)" if pending else "    "
                print (pref, pathname, exp.ex_client.name, extra)
                print_svc_export(exp)

    if (v < 0):
        # Summary
        print("    {} valid entries".format(entries))
    if(tot_pending):
        pylog.warning("pending entries in nfsd.export cache: {}".\
            format(tot_pending))


# IP Map Cache (as reported by /proc/net/rpc/auth.unix.ip/contents)
def print_ip_map_cache():
    ip_table = getCache("auth.unix.ip")
    print ("-----IP Map (/proc/net/rpc/auth.unix.ip)------------")
    #         nfsd              192.168.0.6  192.168.0/24
    print ("    #class              IP         domain")
    for ch in ip_table:
        im = container_of(ch, "struct ip_map", "h")
        dom = ""
        if (_test_cache(ch)):
            dom = im.m_client.h.name;
        # On new kernels, m_addr is 'strict in6_addr'
        # On old (2.6.18) it is just 'struct in_addr'
        addr = im.m_addr
        if (addr.hasField("s_addr")):
            # IPv4-only
            addr_s = ntodots(addr.s_addr)
        else:
            # IPv6
            if (ipv6_addr_v4mapped(im.m_addr)):
                addr_s =  ntodots(im.m_addr.in6_u.u6_addr32[3])
            else:
                addr_s = ntodots6(im.m_addr)
        print ("    %-8s %20s  %s" % (im.m_class, addr_s, dom))

# /* access the groups "array" with this macro */
# #define GROUP_AT(gi, i) \
#       ((gi)->blocks[(i) / NGROUPS_PER_BLOCK][(i) % NGROUPS_PER_BLOCK])

#define NGROUPS_PER_BLOCK       ((unsigned int)(PAGE_SIZE / sizeof(gid_t)))

NGROUPS_PER_BLOCK = PAGESIZE/struct_size("gid_t")
def GROUP_AT(gi, i):
    return gi.blocks[i/NGROUPS_PER_BLOCK][i % NGROUPS_PER_BLOCK]

# Unix GID Cache (as reported by /proc/net/rpc/auth.unix.gid/contents)
def print_unix_gid(v=0):
    gid_table = getCache("auth.unix.gid")
    print ("-----GID Map (/proc/net/rpc/auth.unix.gid)------------")
    print ("#uid cnt: gids...")
    for ch in gid_table:
        ug = container_of(ch, "struct unix_gid", "h")
        dom = ""
        if (_test_cache(ch)):
            glen = ug.gi.ngroups
        else:
            glen = 0
        out = []
        out.append("%u %d:" % (ug.uid, glen))
        for i in range(glen):
            out.append(" %d" % GROUP_AT(ug.gi, i))
        print ("".join(out))

# On 2.4 and earlier 2.6:

# struct rpc_task {
#         struct list_head        tk_list;        /* wait queue links */
# #ifdef RPC_DEBUG
#         unsigned long           tk_magic;       /* 0xf00baa */
# #endif
#         struct list_head        tk_task;        /* global list of tasks */

# On newer 2.6:

# struct rpc_task {
# #ifdef RPC_DEBUG
#       unsigned long           tk_magic;       /* 0xf00baa */
# #endif
#       atomic_t                tk_count;       /* Reference count */
#       struct list_head        tk_task;        /* global list of tasks */





# Decode and Print one RPC task (struct rpc_task)
def print_rpc_task(s, v = 0):
    # On a live system we can easily get bad addresses
    try:
        #print s
        cl_pi = s.CL_procinfo
        rpc_proc = s.P_proc
        tk_client = s.tk_client
        tk_status = s.tk_status
        try:
            pn = s.P_name
        except KeyError:
            pn =''

        cl_xprt= tk_client.cl_xprt
        addr_in = cl_xprt.addr.castTo("struct sockaddr_in")
        ip = ntodots(addr_in.sin_addr.s_addr)

        try:
            server = tk_client.cl_server
        except KeyError:
            server = cl_xprt.servername
        print ("\tProtocol=",cl_xprt.prot, " Server=", server, ip)

        if (v > 1):
            print("\t ", tk_client)
            print("\t ", cl_xprt)

        try:
            print ("\t  protname=", tk_client.cl_protname)
        except KeyError:
            pass

        try:
            pid_owner = s.tk_owner
            print("\tOwner pid={}".format(pid_owner))
        except KeyError:
            # Does not work on RHEL5
            pass

        vers = s.CL_vers
        prog = s.CL_prog
        if (prog == 100003 and vers == 2):
            procname = "%d(%s)" % (rpc_proc, NFS2_PROCS.value2key(rpc_proc))
        elif (prog == 100003 and vers == 3):
            procname = "%d(%s)" % (rpc_proc, NFS3_PROCS.value2key(rpc_proc))
        elif (prog == 100003 and vers == 4):
            procname = "%d(%s)" % (rpc_proc, NFS4_PROCS.value2key(rpc_proc))
        else:
            procname = "%d" % rpc_proc
        print ("\t  rpc_proc={} {}  tk_status={}".format(procname, pn, tk_status))

        print ("\t  pmap_prog=", prog, ", pmap_vers=", vers)

        rqst = s.tk_rqstp

        if (rqst):
            if(rqst.rq_retries):
                print ("\t  rq_retries=", rqst.rq_retries, "rq_timeout=", rqst.rq_timeout,\
                "rq_majortimeo", rqst.rq_majortimeo)
            #print("\t  rq_slen={}".format(rqst.rq_snd_buf.len))
        tk_callback = s.tk_callback
        if (tk_callback):
            print ("\t  callback=%s" % addr2sym(tk_callback))
        # Try to find how long ago it has started
        try:
            tk_start = s.tk_start.tv64
            ms_ago = round((get_ktime_j() - tk_start)/1000000)
            print("\t  started {} ms ago".format(ms_ago))
        except:
            pass
        if (v > 2):
            print("\t  tk_flags={}".format(dbits2str(s.tk_flags, RPC_flags)))
            u = s.u
            links = u.tk_wait.links
            tk_work = u.tk_work
            func = addr2sym(tk_work.func)
            if (func is not None):
                print("\t  func={}".format(func))
                if (not (s.tk_flags & RPC_flags["RPC_TASK_SENT"])):
                    print("\t    !!! inconsistent state")
    except crash.error:
        pass

__sstate = EnumInfo("socket_state")
# decode/print rpc_xprt
def print_xprt(xprt, v = 0):
    try:
        # Get sock from xprt. For old (RHEL5) kernels, use directly xprt
        if (struct_exists("struct sock_xprt")):
            sock_xprt = container_of(xprt, "struct sock_xprt", "xprt")
        else:
            sock_xprt = xprt
        print ("      ...", xprt.shortStr(), "...", sock_xprt.shortStr())
        print("        state={}".format(dbits2str(xprt.state, XPRT_BITS)))
        jiffies = readSymbol("jiffies")
        print ("        last_used %s s ago" % __j_delay(xprt.last_used, jiffies))
        if (v < 1):
            return

        socket = sock_xprt.sock     # struct socket
        sk = socket.sk              # struct sock
        # IP
        ip_sock = IP_sock(sk)
        # Compact str(ip_sock)
        s = ' '.join(str(ip_sock).split())
        print("       ", s)

        for qn in ("binding", "sending","resend", "pending", "backlog"):
            try:
                print ("        len(%s) queue is %d" % (qn,
                                                    getattr(xprt, qn).qlen))
            except KeyError:
                pass
        try:
            xprt.stat.Dump()
        except KeyError:
            # There is no 'stat' field in xprt on 2.6.9
            pass
    except (IndexError, crash.error):
        # Null pointer and invalid addr
        return
    print("")

# decode/print svc_xprt
def print_svc_xprt(xprt, v = 0, indent = 0):
    indent_str = ' ' * indent
    s_struct ='{!s:-^50}'.format(xprt)
    laddr = (l_ip, l_port) = decode_ksockaddr(xprt.xpt_local)
    raddr = (r_ip, r_port) = decode_ksockaddr(xprt.xpt_remote)
    s_addr = "  Local: {} Remote: {}".format(laddr, raddr)
    flags = "        flags={}".format(dbits2str(xprt.xpt_flags, XPT_BITS))
    print(indent_str, s_struct, sep='')
    print(indent_str, s_addr, sep='')
    print(indent_str, flags, sep='')


# Find total number of tasks, even if it very high
def count_rpc_tasks():
    __max = 10000000
    if (symbol_exists("all_tasks")):
        flen = getListSize(sym2addr("all_tasks"), 0, __max)
    else:
        all_clients = get_all_rpc_clients()
        if(not all_clients):
            return 0
        flen = 0
        for cl in all_clients:
            flen += getListSize(cl.cl_tasks, 0, __max)
    return flen

# print all rpc pending tasks
def print_all_rpc_tasks(v=1, maxtoprint = 20):
    # Obtain all_tasks
    flen = count_rpc_tasks()
    if (v >= 0 and flen > maxtoprint):
        print ("  ----Printing first {} out of total {} RPC Tasks ---------".\
            format(maxtoprint, flen))
    else:
        print ("  ------- %d RPC Tasks ---------" % flen)

    tasks = get_all_rpc_tasks(maxtoprint)
    allc = get_all_rpc_clients()
    xprtset = set()
    if (allc):
        print ("      --- %d RPC Clients ----" % len(allc))
    for t in tasks:
        if (v >= 0):
            print ("    ---", t)
            print_rpc_task(t, v)
        # On a live kernel pointers may get invalid while we are processing
        try:
            xprt= t.tk_client.cl_xprt
            #xprt = t.tk_rqstp.rq_xprt
            xprtset.add(xprt)
            #print_rpc_task(t)
        except (IndexError, crash.error):
            # Null pointer and invalid addr
            continue
    # Print XPRT vitals
    print (" --- XPRT Info ---")
    for xprt in xprtset:
        print_xprt(xprt, 2)

def print_all_tasks():
    all_tasks = readSUListFromHead("all_tasks", "tk_task", "struct rpc_task")
    # Check whether it's 2.4 or 2.6
    newk = (member_size("struct rpc_clnt", "cl_pmap_default") != -1)
    for s in all_tasks:
        print_rpc_task(s)


# Print info about RPC status
def print_rpc_status():
    all_tasks = sym2addr("all_tasks")
    #l = readList(all_tasks, 0, maxel=100000, inchead=False)
    print ("all_tasks has %d elements" % getListSize(all_tasks, 0, 10000000))
    return
    for qname in ("schedq", "childq", "delay_queue"):
        tasks = readSU("struct rpc_wait_queue", sym2addr(qname)).tasks
        print ("Number of elements in %15s:" % qname, end='')
        for lh in tasks:
            #print hexl(Addr(lh))
            print (" [%d] " % getListSize(Addr(lh), 0, 10000000), end='')
        print ("")

    return
    # Print schedq elements
    shedq0 = readSU("struct rpc_wait_queue", sym2addr("schedq")).tasks[0]
    for ta in readList(Addr(shedq0), 0, maxel=20, inchead=False):
        rpct = readSU("struct rpc_task", ta)
        print_rpc_task(rpct)

# Warning: on older kernels:
# struct net_generic {
#        unsigned int len;
#
# and on newer ones:
# struct net_generic {
#	union {
#		struct {
#			unsigned int len;
#			struct rcu_head rcu;
#		} s;

# In the latter case, net_generic() returns ng->ptr[id] instead of
# ng->ptr[id-1]

def net_generic(net, net_id):
    ng = net.gen
    ptr = ng.ptr
    try:
        ng_len = ng.len
        newstyle = False
    except KeyError:
        ng_len = ng.s.len
        newstyle = True
    #print(net_id, ng_len)
    assert (not (net_id == 0 or net_id > ng_len))
    addr = ptr[net_id] if newstyle else ptr[net_id - 1]
    return addr


# Get sunrpc_net
def get_sunrpc_net():
    if (not symbol_exists("sunrpc_net_id")):
        return 0
    net_id = readSymbol("sunrpc_net_id")
    net = readSymbol("init_net")
    return net_generic(net, net_id)

# Getting all tasks.
#
# On recent 2.6:
#/*
# * All RPC clients are linked into this list
# */
#static LIST_HEAD(all_clients);

# Get all RPC clients for kernels where they exist
def get_all_rpc_clients():
    all_clients = sym2addr("all_clients")
    if (all_clients == 0):
        addr = get_sunrpc_net()
        if (not addr):
            return []
        sn = readSU("struct sunrpc_net", addr)
        all_clients = long(sn.all_clients)
    return readSUListFromHead(all_clients, "cl_clients", "struct rpc_clnt")

def get_all_rpc_tasks(nmax = 100):
    all_taddr = sym2addr("all_tasks")
    if (all_taddr):
        return readSUListFromHead(all_taddr, "tk_task", "struct rpc_task",
                           maxel= nmax, warn = False)

    out = []
    allc = get_all_rpc_clients()
    nleft = nmax
    for cl in allc:
        tasks = readSUListFromHead(long(cl.cl_tasks), "tk_task",
                                   "struct rpc_task",
                                   maxel = nleft, warn = False)
        out += tasks
        nleft -= len(tasks)

    return out


# This class will be used to hold all information we can extract about
# NFS/RPC servers and clients. It should probably be a Singleton but
# at this moment we do not care

class _NFS_Tables():
    def __init__(self):
        # list of struct nfs_server
        self.srv_list = []
        # Mount path for nfs_server, a dict of strings indexed by srv
        self.srv_mount = {}
        # list of struct nfs_client
        self.nfs_cli_list = []
        # list of all structs refering to this struct rpc_clnt
        self.rpc_cl = defaultdict(list)

        for hostname, srv, mnt in get_nfs_mounts():
            self.srv_list.append(srv)
            self.srv_mount[srv] = mnt
            self.rpc_cl[long(srv.client)].append(srv)
            self.rpc_cl[long(srv.client_acl)].append(srv)
            try:
                nfs_cl = srv.nfs_client
                self.nfs_cli_list.append(nfs_cl)
                self.rpc_cl[long(nfs_cl.cl_rpcclient)].append(nfs_cl)
            except KeyError:
                # Old 2.6.9 kernels, we do not care about them anymore
                pass
    # Get list of nfs_server structs, return (srv, mnt)
    def get_nfs_servers(self):
        return [(srv, self.srv_mount[srv]) for srv in self.srv_list]
    # Get list of all nfs_client struct
    def get_nfs_clients(self):
        return self.nfs_cli_list
    # get all know structures referring to a given rpc_clnt
    def get_rpc_cl_friends(self, addr):
        return self.rpc_cl.get(addr, [])

#@memoize_cond(CU_LIVE |CU_PYMOD)
def NFS_Tables():
    return _NFS_Tables()



# Get dirty inodes
#       struct list_head        s_dirty;        /* dirty inodes */
#       struct list_head        s_io;           /* parked for writeback */

def print_test():
    for sa in readList(sym2addr("super_blocks"), 0, inchead=False):
        sb = readSU("struct super_block", sa)
        fsname = sb.Deref.s_type.name
        if (fsname != "nfs"):
            continue
        s_dirty = readSUListFromHead(Addr(sb.s_dirty), "i_list", "struct inode")
        try:
            s_io = readSUListFromHead(Addr(sb.s_io), "i_list", "struct inode")
        except KeyError:
            s_io = []
        if (len(s_dirty) | len(s_io)):
            print (sb, fsname, \
                  "len(s_dirty)=%d len(s_io)=%d" % (len(s_dirty),len(s_io)))



def INT_LIMIT(bits):
    return (~(1 << (bits - 1)))


# Print 'struct file_lock' info
def print_file_lock(fl):
    lockhost = fl.fl_owner.castTo("struct nlm_host")
    print (lockhost)

# Print FH
def printFH(fh, indent = 0):
    def chunk(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i:i+size]
    sz = fh.size
    data = fh.data[:sz]
    s = []
    for c in data:
        s.append("%02x" % c)
    FH = "FH(%d)" % sz
    lFH = len(FH)
    s =  ''.join(s)
    sb = s[:76-indent-lFH]
    se = s[76-indent-lFH:]
    print (' ' * indent, FH, sb)
    for ss in chunk(se, 76-indent - lFH):
        print (' ' * (indent + lFH + 1), ss)


# Print 'struct svc_serv'
# 2.6.18 kernel
#   On this kernel, sv_permsocks is a list of svc_sock linked via sk_list
# 2.6.35 kernel
#   On this kernel, sv_permsocks is a list of svc_sock linked via sk_xprt.xpt_list
def print_svc_serv(srv):
    print ("  -- Sockets Used by NLM")
    print ("     -- Permanent Sockets")
    for s in ListHead(Addr(srv.sv_permsocks), "struct svc_sock").SockList:
        print ("\t", s, "\n  ", IP_sock(s.sk_sk))
    if (srv.sv_tmpcnt):
        print (" -- Temp Sockets")
        for s in ListHead(Addr(srv.sv_tempsocks), "struct svc_sock").SockList:
            print ("\t", s, "\n  ", IP_sock(s.sk_sk))


# Print NLM stuff

def print_nlm_serv():
    # This exists on 2.6.18 but not on 2.6.35
    try:
        svc_serv = readSymbol("nlmsvc_serv")
    except TypeError:
        # On 2.6.35 we have
        # static struct svc_rqst                *nlmsvc_rqst;
        nlmsvc_rqst = readSymbol("nlmsvc_rqst")
        # This is NULL if we are NFSv3-only
        if (not nlmsvc_rqst):
            return
        # Maybe we should print svc_rqst here?
        svc_serv = nlmsvc_rqst.rq_server
    print_svc_serv(svc_serv)

# Print nlm_blocked list

def print_nlm_blocked_clnt(nlm_blocked):
    sizeloff = getSizeOf("loff_t")
    bits = sizeloff*8
    OFFSET_MASK = (~(~0<<bits))
    OFFSET_MAX =  (~(1 << (bits - 1))) & OFFSET_MASK
    lh = ListHead(nlm_blocked, "struct nlm_wait")
    if (len(lh)):
        print ("  ................ Waiting For Locks .........................")

    for block in lh.b_list:
        fl_blocked = block.b_lock
        owner = fl_blocked.fl_u.nfs_fl.owner.pid
        haddr = block.b_host.h_addr.castTo("struct sockaddr_in")
        ip = ntodots(haddr.sin_addr.s_addr)
        print ("    ----  ", block)
        #inode = fl_blocked.fl_file.f_dentry.d_inode
        inode = fl_blocked.Inode
        nfs_inode = container_of(inode, "struct nfs_inode", "vfs_inode")
        print ("     ", inode, nfs_inode)
        fh = nfs_inode.fh
        fl_start = fl_blocked.fl_start
        fl_end = fl_blocked.fl_end
        if (fl_end == OFFSET_MAX):
            length = 0
        else:
            length = (fl_end - fl_start + 1) & OFFSET_MASK
        print ("         fl_start=%d fl_len=%d owner=%d ip=%s" % (fl_start,
                                                          length, owner, ip))
        # Print FH-data
        printFH(fh, 8)

# built-in crash command 'files -l' is broken on recent kernels
#   On newer kernels (e.g. 2.6.20) we have
# static struct hlist_head      nlm_files[FILE_NRHASH];
#   On older kernels (e.g. 2.6.9-2.6.18) we have
# static struct nlm_file *      nlm_files[FILE_NRHASH];

def print_nlm_files():
    nlm_files = readSymbol("nlm_files")
    once = TrueOnce(1)

    def get_all_nlm_files():
        try:
            #print "New style"
            for h in nlm_files:
                if (h.first == 0):
                    continue
                #print h
                for e in hlist_for_each_entry("struct nlm_file", h, "f_list"):
                    yield e
        except (KeyError, AttributeError):
            # struct nlm_file *nlm_files[32];
            # struct nlm_file {
            #     struct nlm_file *f_next;

            for e in nlm_files:
                if (not e):
                    continue
                # Deref the pointer
                for e in readStructNext(e, "f_next"):
                    yield e


    for e in get_all_nlm_files():
        f_file = e.f_file
        if (once):
            print ("  -- Files NLM locks for clients ----")
        print ("    File:", get_pathname(f_file.Dentry, f_file.Mnt))
        print ("         ", e)
        for fl in readStructNext(e.Inode.i_flock, "fl_next"):
            lockhost = fl.fl_owner.castTo("struct nlm_host")
            print ("       Host:", lockhost.h_name)

# Print info for remote nfs-server (we are a client!)
def print_remote_nfs_server(nfs, mntpath):
    print ("    --%s %s:%s" % (str(nfs), nfs.Hostname, mntpath))
    print ("       flags=<%s>," % dbits2str(nfs.flags, NFS_flags, 10), end='')
    print (" caps=<%s>" % dbits2str(nfs.caps, NFS_caps, 8), end='')
    print (" rsize=%d, wsize=%d" % (nfs.rsize, nfs.wsize))
    # Here the verbose sections starts
    if (True):
        return
    print ("       acregmin=%d, acregmax=%d, acdirmin=%d, acdirmax=%d" % \
          (nfs.acregmin, nfs.acregmax, nfs.acdirmin, nfs.acdirmax))
    # Stats for nfs_server (struct nfs_iostats *io_stats;) are not very
    # interesting (just events/bytes per cpu). So let us rather print
    # stats for nfs_client
    #nfsv4_server = Nfs4.nfs_server(nfs)
    #nfsv4_server.print_verbose(o.owner, o.lock, o.delegation)




def print_nfsmount(v = 0):
    my_ipv4, my_ipv6 = netdevice.get_host_IPs()
    # First, prepare a summary
    #    print (" Mounted NFS-shares ".center(70, '-'))

    # Object to be used for summary
    count_all = 0
    count_flag = Counter()
    count_caps = Counter()

    nfstable = NFS_Tables()

    for srv, mnt in nfstable.get_nfs_servers():
        # Prepare a summary
        count_all += 1
        count_flag[dbits2str(srv.flags, NFS_flags, 10)] += 1
        count_caps[dbits2str(srv.caps, NFS_caps, 8)] += 1
    if (count_all):
        # Print a summary
        print(" -- {} mounted shares, by flags/caps:".format(count_all))
        for k, val in count_flag.items():
            print ("  {:3d} shares with flags=<{}>".format(val, k))
        for k, val in count_caps.items():
            print ("  {:3d} shares with caps=<{}>".format(val, k))

    # idmap with busy waitqueues, if any. At this moment it works for older
    # kernels only (e.g. RHEL6), on newer kernels there is no 'idmap_wq' field
    idmap_busy = {}
    for srv, mnt in nfstable.get_nfs_servers():
        print ("   ---%s %s:%s" % (str(srv), srv.Hostname, mnt))
        print ("       flags=<%s>," % dbits2str(srv.flags, NFS_flags, 10), end='')
        print (" caps=<%s>" % dbits2str(srv.caps, NFS_caps, 8), end='')
        print (" rsize=%d, wsize=%d" % (srv.rsize, srv.wsize))

        nfs_cl = srv.nfs_client
        # At this moment, only IPv4
        addr_in = nfs_cl.cl_addr.castTo("struct sockaddr_in")
        ip = ntodots(addr_in.sin_addr.s_addr)
        # Version
        nfs_major_vers = nfs_cl.rpc_ops.version
        nfsvers = "{}.{}".format(nfs_major_vers, nfs_cl.cl_minorversion)
        print("       NFS version: {}".format(nfsvers))

        print ("    ---", nfs_cl, nfs_cl.cl_hostname, ip)
        if (ip in my_ipv4):
            pylog.warning("NFS loopback mount -> {}".format(ip))

        if (v):
            # Print owner_id if available
            try:
                cl_owner_id = nfs_cl.cl_owner_id
                if (cl_owner_id):
                    print("     ", cl_owner_id)
            except:
                pass
        # Check idmap queues
        try:
            idmap = nfs_cl.cl_idmap
        except (TypeError,KeyError):
            # On newer kernels we need to load debuginfo for nfsv4.ko
            # But it does not make sense to try it until we modify the code
            # for waitqueue - on these kernels there is no 'idmap_wq' field
            idmap = None
        if (idmap and idmap.hasField('idmap_wq')):
            wq = idmap.idmap_wq
            if (wq):
                if (idmap not in idmap_busy):
                    tasks = decode_waitq(wq)
                    if (tasks):
                        idmap_busy[idmap] = tasks

        rpc_clnt = nfs_cl.cl_rpcclient
        if (v > 1):
            print('        ...', rpc_clnt)
        # Print/decode the transport
        xprt = rpc_clnt.cl_xprt
        print_xprt(xprt, detail)
        #print rpc_clnt, rpc_clnt.cl_metrics

        # NFSv4 specific
        if (nfs_major_vers == 4 and v > 1):
            nfsv4_client = Nfs4.nfs_client(nfs_cl)
            nfsv4_client.print_verbose()
            nfsv4_server = Nfs4.nfs_server(srv)
            nfsv4_server.print_verbose(1, 1, 1)


    if (idmap_busy):
        print ("\n  ............. idmap with busy workqueues .................")
        for idmap, tasks in idmap_busy.items():
            print("      --- {} ---".format(idmap))
            for t in tasks:
                print("          PID={}".format(t.pid))
            print("")
    # Stats are per RPC program, and all clients are using "NFS"
    cl_stats = rpc_clnt.cl_stats
    rpc_prog = cl_stats.program
    print ("  .... Stats for program ", rpc_prog.name)
    cl_stats.Dump()

# Decode sockaddr_storage and return (ip, port). Works for AF_INET and AF_INET6.
# For unknown families, returns ("Unknown family", None)
# For ss_faimily=0 returns (None, None)
def decode_ksockaddr(ksockaddr):
    family = ksockaddr.ss_family
    # char __data[126]
    data = ksockaddr.__data.ByteArray
    if (family == socket.AF_INET):
        port = data[0]*256+data[1]
        ip = socket.inet_ntop(socket.AF_INET, struct.pack(4*'B', *data[2:2+4]))
        return (ip, port)
    elif (family == socket.AF_INET6):
        port = data[0]*256+data[1]
        ip = socket.inet_ntop(socket.AF_INET6, struct.pack(16*'B', *data[6:6+16]))
        return (ip, port)
    elif (family == 0):
        return (None, None)
    else:
        return ("Unknown family {}".format(family), None)

def print_all_svc_xprt(v = 0):
    # Get nfsd_serv. On 2.6.32 it was a global variable, later it was moved
    # to init_net.gen[nfsd_net_id]
    # On 2.6.18 it is a global variable but lists are different
    try:
        nfsd_serv = readSymbol("nfsd_serv")
    except TypeError:
        try:
            # On recent kernels, there are many  interesting
            # tables in "init_net", but not on 2.6.32 it is not available
            nfsd_net_id = readSymbol("nfsd_net_id") - 1
            net = get_ns_net()
            nfsd_net_ptr = net.gen.ptr[nfsd_net_id]
            nfsd_net = readSU("struct nfsd_net", nfsd_net_ptr)
            nfsd_serv = nfsd_net.nfsd_serv
        except KeyError:
            return
    if (not nfsd_serv):
        # No NFS-server running on this host
        return

    if (v >= 0):
        print (" ============ SVC Transports/Sockets ============")
    sn = "struct svc_xprt"              # RHEL6
    if (struct_exists(sn)):
        lnk = "xpt_list"
    else:
        sn = "struct svc_sock"          # RHEL5
        lnk = "sk_list"
    for st, lst in (
        ("sv_permsocks", ListHead(nfsd_serv.sv_permsocks, sn)),
        ("sv_tempsocks", ListHead(nfsd_serv.sv_tempsocks, sn ))):

        if (v >= 0):
            print("\n *** {} ***".format(st))

        for x in getattr(lst, lnk):
            if (sn == "struct svc_xprt"):       # RHEL6
                mutex =  x.xpt_mutex
                s_struct ='{!s:-^50}{:-^28}'.format(x, addr2sym(x.xpt_class))
                laddr = (l_ip, l_port) = decode_ksockaddr(x.xpt_local)
                raddr = (r_ip, r_port) = decode_ksockaddr(x.xpt_remote)
                s_addr = "  Local: {} Remote: {}".format(laddr, raddr)
                flags = "        flags={}".format(dbits2str(x.xpt_flags, XPT_BITS))
                #print("         xpt_flags={:#x}".format(x.xpt_flags))
            else:
                mutex = x.sk_mutex
                s_struct = '{!s:-^78}'.format(x)
                s_addr = str(IP_sock(x.sk_sk))
                flags = ''
            counter = mutex.count.counter
            if (v >= 0 or counter != 1):
                print(s_struct)
                print(s_addr)
                if(flags):
                    print(flags)
            if (counter != 1):
                print("   +++ mutex is in use +++", mutex)
                decode_mutex(mutex)

# Print from cache_defer_hash.
# v=-1 is for summary
def print_deferred(v = 0):
    if (v >= 0):
        print (" {:-^78}".format("cache_defer_hash"))
    svc_revisit = sym2addr("svc_revisit")
    total = 0
    for hb in readSymbol("cache_defer_hash"):
        first = hb.first
        if (not first):
            continue
        for a in readList(first):
            total += 1
            if (v < 0):
                continue
            dreq = container_of(a, "struct cache_deferred_req", "hash")
            print("  {!s:=^60}".format(dreq))
            if (dreq.revisit == svc_revisit):
                dr =  container_of(dreq, "struct svc_deferred_req", "handle")
                print("       ", dr)
                print_svc_xprt(dr.xprt, indent=8)
        if (v == -1 and total):
            pylog.warning("{} deferred requests".format(total))


# --- find all threads that have nfs or rpc subroutines on their stack
def find_all_NFS(v = 0):
    stacks_helper = fastSubroutineStacks()
    _funcpids = stacks_helper.find_pids_byfuncname
    pids = _funcpids(re.compile("nfs|rpc"))
    for pid in pids:
        print_pid_NFS_stuff(pid, v)

# --- look at this PID to see whether we can find anything interesting
# related to NFS/RPC

def print_pid_NFS_stuff(pid, v = 0):
    re_nfsrpc=re.compile(r'nfs|rpc')
    re_ctypes = re.compile(r'nfs|rpc|inode|path')
    # Verify whether we really havd these subroutines on the stack
    bts = exec_bt("bt {}".format(pid))[0]
    if (not bts.hasfunc(re_nfsrpc)):
        return
    print("--- PID={} ---".format(pid))

    # Group by funcname
    iterable = list(get_interesting_arguments(pid, re_nfsrpc, re_ctypes))
    #if (iterable):
        #print("   --- PID={} ---".format(pid))
    keyfunc = operator.itemgetter(0)
    for funcname, g in itertools.groupby(iterable, keyfunc):
        print(" ---", funcname)
        for funcname, sname, addr in g:
            obj = readSU(sname, addr)
            print("   {!s:45s}".format(obj))
            decoder = "__nfs_decode_{}".format(sname.split()[1])
            #print("  ", decoder)
            try:
                exec ("{}(obj, funcname)".format(decoder),globals(),locals())
            except NameError as val:
                if ('__nfs_decode' in str(val)):
                    pass
                    #__nfs_default_decoder(obj, funcname)
                else:
                    print("   Error:", val)

def __nfs_default_decoder(obj, funcname):
    print("    {!s:45s}".format(obj))

def __nfs_decode_path(path, func):
    pathname = get_pathname(path.dentry, path.mnt)
    print("     ⮡{}".format(pathname))

def __nfs_decode_inode(inode, func):
    nfs_server = NFS_SERVER(inode)
    print("    ⮡", nfs_server)
    nfs_cl = nfs_server.nfs_client
    if (nfs_cl):
        print("      ⮡", nfs_cl)

def __nfs_decode_nfs4_state(o, func):
    owner = o.owner
    nfs_server = owner.so_server
    print("    ⮡", nfs_server)
    nfs_cl = nfs_server.nfs_client
    if (nfs_cl):
        print("      ⮡", nfs_cl)

def __nfs_decode_rpc_clnt(o, func):
    print("      ⮡server: {}".format(o.cl_server))
    nfstable = NFS_Tables()
    for owner in nfstable.get_rpc_cl_friends(o):
        print("      ⮡used by: {}".format(owner))


# The following exists on new kernels but not on old (e.g. 2.6.18)
try:
    __F = EnumInfo("enum nfsd_fsid")
except TypeError:
    __F = None
    key_len = key_len_old

# There are two nlm_blocked lists: the 1st one declared in clntlock.c,
# the 2nd one in svclock.c.

# E.g.:
# ffffffff88cf6240 (d) nlm_blocked
# ffffffff88cf6800 (d) nlm_blocked

# The client listhead is typically followed by 'nlmclnt_lock_ops'
# (but not on 2.4),  the svs by 'nlmsvc_procedures'
# So we assume that address near 'nlmclnt_lock_ops' is the client addr

anchor = sym2addr("nlmclnt_lock_ops")
#print "anchor", hexl(anchor)

clnt, svc = tuple(sym2alladdr("nlm_blocked"))

if (abs(clnt-anchor) > abs(svc-anchor)):
    clnt, svc = svc, clnt

#print "nlm_blocked clnt=", hexl(clnt), getListSize(clnt, 0, 1000)
#print "nlm_blocked svc=", hexl(svc), getListSize(svc, 0, 1000)
#print_nlm_blocked_clnt(clnt)


#print_rpc_status()
#print_test()
#get_all_tasks_old()

HZ = sys_info.HZ

# Printing info for NFS-client
def host_as_client(v = 0):
    print ('*'*20, " Host As A NFS-client ", '*'*20)
    print_nfsmount(v)
    print_nlm_blocked_clnt(clnt)

#print_nlm_files()



# Printing info for NFS-server
def host_as_server(v = 0):
    if (not is_NFSD()):
        return
    print ('*'*20, " Host As A NFS-server ", '*'*20)

    # Exportes filesystems
    if (v >= 0):
        print_ip_map_cache()
        print ("")
    print_nfsd_export(v)
    print ("")
    print_nfsd_fh(v)
    print ("")
    if (v >= 0):
        print_unix_gid(v)
        print ("")

    # Locks we are holding for clients
    print_nlm_files()

    print_all_svc_xprt(v)

    # Print number of deferred rqequest (if any)
    try:
        print_deferred(-1)
    except:
        print("cannot print deferred requests for this kernel yet")

    # Print RPC-reply cache only when verbosity>=2
    if (v >=0 and v < 2):
        return
    # Time in seconds - show only the recent ones
    new_enough = 10 * HZ
    lru_head = sym2addr("lru_head")
    rpc_list = []
    if (lru_head):
        sn = "struct svc_cacherep"
        jiffies = readSymbol("jiffies")
        offset = member_offset(sn, "c_hash")
        for e in ListHead(lru_head, sn).c_lru:
            #print e, ntodots(e.c_addr.sin_addr.s_addr), e.c_timestamp, e.c_state
            if (e.c_state == 0):       # RC_UNUSED
                continue
            hnode = e.c_hash

            for he in readList(hnode, 0):
                hc = readSU(sn, he-offset)
                secago = (jiffies-hc.c_timestamp)/HZ
                if (secago > new_enough):
                    continue
                rpc_list.append((secago, hc))

        if (rpc_list):
            rpc_list.sort()
            if (v < 0):
                print(" -- {} RPC Reply-cache Entries in last 10s".format(
                    len(rpc_list)))
                return
            print ("  -- Recent RPC Reply-cache Entries (most recent first)")
            for secago, hc in rpc_list:
                prot = protoName(hc.c_prot)
                proc = hc.c_proc
                try:
                    saddr = format_sockaddr_in(hc.c_addr)
                except TypeError:
                    saddr = "n/a"
                print ("   ", hc, prot, saddr, secago, hc.c_state)

def print_sunrpc_net(v):
    sn = readSU("struct sunrpc_net", get_sunrpc_net())
    print("   --- {} ---".format(sn))
    for cname in ("ip_map_cache", "unix_gid_cache"):
        try:
            cd = getattr(sn, cname)
            cname = "{}/{}".format(cname, cd.name)
            print("  {:30s} {}".format(cname, cd))
        except KeyError:
            pass


detail = 0

if ( __name__ == '__main__'):
    import argparse

    class hexact(argparse.Action):
        def __call__(self,parser, namespace, values, option_string=None):
            # A special value 'all'
            if (values == 'all'):
                val = 'all'
            else:
                val =  int(values,16)
            setattr(namespace, self.dest, val)
            return

    parser =  argparse.ArgumentParser()


    parser.add_argument("-a","--all", dest="All", default = 0,
                  action="store_true",
                  help="print all")

    parser.add_argument("--server", dest="Server", default = 0,
                  action="store_true",
                  help="print info about this host as an NFS-server")

    parser.add_argument("--client", dest="Client", default = 0,
                  action="store_true",
                  help="print info about this host as an NFS-client")

    parser.add_argument("--rpctasks", dest="Rpctasks", default = 0,
                  action="store_true",
                  help="print RPC tasks")

    parser.add_argument("--decoderpctask", dest="Decoderpctask", default = -1,
                  action=hexact,
                  help="Decode RPC task at address")

    parser.add_argument("--maxrpctasks", dest="Maxrpctasks", default = 20,
                  type=int, action="store",
                  help="Maximum number of RPC tasks tp print")

    parser.add_argument("--locks", dest="Locks", default = 0,
                    action="store_true",
                    help="print NLM locks")
    parser.add_argument("--deferred",  default = 0,
                  action="store_true",
                  help="Print Deferred Requests")

    parser.add_argument("--pid", dest="Pid", default=None, const=-1,
                nargs = '?',
                type=int, action="store",
                help="Try to find everything NFS-related for this pid")

    parser.add_argument("--version", dest="Version", default = 0,
                  action="store_true",
                  help="Print program version and exit")


    parser.add_argument("-v", dest="Verbose", default = 0,
        action="count",
        help="verbose output")


    o = args = parser.parse_args()

    detail = o.Verbose

    if (o.Version):
        print ("nfsshow version %s" % (__version__))
        sys.exit(0)

    if (o.Client or o.All):
        if (get_nfs_mounts()):
            host_as_client(detail)

    if (detail):
        print_sunrpc_net(detail)
    
    if (o.Server or o.All):
        host_as_server(detail)

    if (o.Rpctasks or o.All):
        print_all_rpc_tasks(detail, o.Maxrpctasks)

    if (o.Decoderpctask != -1):
        s = readSU("struct rpc_task", o.Decoderpctask)
        print_rpc_task(s, detail)
        sys.exit(0)

    if (o.Pid):
        if (o.Pid == -1):
            # All processes with nfs/rpc on stack
            print("  --- All Processes doing NFS or RPC ---")
            find_all_NFS(detail)
        else:
            print_pid_NFS_stuff(o.Pid, detail)
        sys.exit(0)

    if (o.Locks or o.All):
        print ('*'*20, " NLM(lockd) Info", '*'*20)
        print_nlm_files()
        print_nlm_serv()

    if (o.deferred):
        print_deferred(detail)
    

    # If no options have been provided, print just a summary
    rargs = len(sys.argv) - 1
    if (not (rargs == 0 or rargs == 1 and detail)):
        sys.exit(0)

    if (get_nfs_mounts()):
        host_as_client(detail)

    # As server
    host_as_server(-1)

    # RPC tasks
    print(" RPC ".center(70, '='))
    print_all_rpc_tasks(-1)

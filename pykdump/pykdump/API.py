# -*- coding: utf-8 -*-
# module pykdump.API
#

# This is the only module from pykdump that should be directly imported
# by applications. We want to hide the details of specific implementation from
# end-user. In particular, this module decides what backends to use
# depending on availability of low-level shared library dlopened from crash
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
This is the toplevel API for Python/crash framework. Most programs should
not call low-level functions directly but use this module instead.
'''


# Messages to be used for warnings and errors
WARNING = "+++WARNING+++"
ERROR =   "+++ERROR+++"
INFO = "...INFO..."

debug = 0

import sys, os, os.path
import re, string
import time, select
import stat
import traceback
import atexit
import importlib
from collections import defaultdict
import pprint
pp = pprint.PrettyPrinter(indent=4)


# To be able to use legacy (Python-2) based subroutines
long = int

# It does not make sense to continue if C-module is unavailable
try:
    import crash
except ImportError as e:
    # Traverse frames to find the program
    # <frame object at 0x18ef288>
    # ../progs/pykdump/API.py
    # <frozen importlib._bootstrap>
    # <frozen importlib._bootstrap_external>
    # <frozen importlib._bootstrap>
    # <frozen importlib._bootstrap>
    # <frozen importlib._bootstrap>
    # ../progs/xportshow.py

    import inspect
    cframe = inspect.currentframe()
    for f in inspect.getouterframes(cframe)[1:]:
        if ("/progs/" in f.filename):
            #print(f.filename)
            g = f.frame.f_globals
            break
    vers =" %s: %s" % (g["__name__"], g["__version__"])
    raise ImportError(vers)


import pykdump                          # For version check
require_cmod_version = pykdump.require_cmod_version

require_cmod_version(pykdump.minimal_cmod_version)


# Here we make some pieces of other modules classes/functions/varibles
# visible to API

from . import Generic as gen
from .Generic import (Bunch, DCache, TrueOnce,
        ArtStructInfo, EnumInfo, iterN,
        memoize_cond, purge_memoize_cache, PY_select_purge,
        CU_LIVE, CU_LOAD, CU_PYMOD, CU_TIMEOUT,
        memoize_typeinfo, purge_typeinfo, PY_select)

hexl = gen.hexl
unsigned16 = gen.unsigned16
unsigned32 = gen.unsigned32
unsigned64 = gen.unsigned64

dbits2str = gen.dbits2str
print2columns = gen.print2columns

@memoize_cond(CU_LIVE)
def get_task_mem_usage(addr):
    return crash.get_task_mem_usage(addr)


HZ = crash.HZ
PAGESIZE = crash.PAGESIZE
PAGE_CACHE_SHIFT = crash.PAGE_CACHE_SHIFT

crash.WARNING = WARNING                 # To be used from C-code



import pprint

# For binary compatibility with older module
try:
    set_default_timeout = crash.set_default_timeout
except AttributeError:
    def set_default_timeout(timeout):
        return None

from . import wrapcrash

from .wrapcrash import (readU8, readU16, readU32, readS32,
     readU64, readS64, readInt, readPtr,
     readSymbol, readSU,
     sLong, le32_to_cpu, cpu_to_le32, le16_to_cpu,
     readList, readBadList, getListSize, readListByHead,  list_for_each_entry,
     ListHead, LH_isempty, hlist_for_each_entry,
     readSUArray, readSUListFromHead, readStructNext,
     getStructInfo, getFullBuckets, getFullBucketsH, FD_ISSET,
     struct_exists, symbol_exists,
     Addr, Deref, SmartString, tPtr,
     sym2addr, addr2sym, sym2alladdr, addr2mod,
     get_pathname, is_task_active, pid_to_task, task_to_pid,
     readmem, uvtop, phys_to_page, readProcessMem, set_readmem_task,
     struct_size, union_size, member_offset, member_size, enumerator_value,
     getSizeOf, container_of, whatis, funcargs, printObject,
     exec_gdb_command, exec_crash_command, exec_crash_command_bg,
     exec_crash_command_bg2, exec_command,
     structSetAttr, structSetProcAttr, sdef2ArtSU, AttrSetter,
     getCurrentModule, registerObjAttrHandler, registerModuleAttr)

gen.d = wrapcrash
# Add all GDB-registered types as Generic and wrapcrash variables
for n in dir(crash):
    if (n.find('TYPE_CODE') == 0):
        setattr(gen, n, getattr(crash, n))
        setattr(wrapcrash, n, getattr(crash, n))
    TYPE_CODE_SU = (crash.TYPE_CODE_STRUCT, crash.TYPE_CODE_UNION)
    setattr(gen, 'TYPE_CODE_SU', TYPE_CODE_SU)
    setattr(wrapcrash, 'TYPE_CODE_SU', TYPE_CODE_SU)

from .tparser import CEnum, CDefine

# API module globals
sys_info = Bunch()
API_options = Bunch()

# =================================================================
# =                                                               =
#              Global and Debugging options                       =
# =                                                               =

registerModuleAttr("debugReload", default=0)

# Timeout used on a previous run
global __timeout_exec
__timeout_exec = 0

class PyLog:
    def __init__(self):
        self._cache = defaultdict(list)
        self._silent = ""
    def _addtocache(self, name, data):
        if (not data in self._cache[name]):
            self._cache[name].append(data)
    def _printandcache(self, name, data):
        self._addtocache(name, data)
        print(name, end=' ')
        args, kwargs = data
        print(*args, **kwargs)
    def timeout(self, msg):
        print(WARNING, msg)
        self._addtocache("timeout", msg)
    def warning(self, *args, **kwargs):
        # Print traceback if debug is enabled
        if (debug):
            traceback.print_stack()
        name = WARNING
        self._printandcache(name, (args, kwargs))
    # Another flavor of warning - print on exit only
    def warning_onexit(self, *args, **kwargs):
        name = WARNING
        self._addtocache(name, (args, kwargs))
    def info(self, *args, **kwargs):
        name = INFO
        self._addtocache(name, (args, kwargs))
    def error(self, *args, **kwargs):
        name = ERROR
        # Print traceback if debug is enabled
        if (debug):
            traceback.print_stack()

        self._printandcache(name, (args, kwargs))
    def silent(self, msg):
        self._silent = msg
    def getsilent(self):
        msg = self._silent
        self._silent = ""
        return msg
    # Propagate silent error to real error if any, but do not print it
    def silenterror(self, extra):
        msg = self.getsilent()
        if (msg):
            args = (extra, msg)
            kwargs = {}
            self._addtocache(ERROR, (args, kwargs))
    def cleanup(self):
        # Clear the cache
        self._cache.clear()
        self._silent = ""
    def onexit(self):
        # Is there anything to print?
        if (not self._cache):
            return
        self.__print_problems()
        self.__print_info()
    def __print_info(self):
        if (not INFO in self._cache):
            return
        print("")
        print(" Additional Info ".center(78, '~'))
        for args, kwargs in self._cache[INFO]:
            print(end="    ")
            print(*args, **kwargs)
        print('~'*78)
    def __print_problems(self):
        _keys = set(self._cache.keys()) - {INFO}
        if (not _keys):
            return
        print("")
        print('*'*78)
        print(" A Summary Of Problems Found ".center(78, '*'))
        print('*'*78)
        # Are there are timeout messages?
        if (self._cache["timeout"]):
            print(" Some crash built-in commands did not complete "
                  "within timeout ".center(78, '-'))
            for l in self._cache["timeout"]:
                print("   ", l)
            print(" *** You can rerun your command with a different timeout\n"
                  "     by adding --timeout=NNN to your options\n"
                  "     For example, 'crashinfo -v --timeout=1200\n"
                  "     to run with timeout of 1200s")
        # Are there any warnings/errors?
        for name in (WARNING, ERROR):
            if (self._cache[name]):
                print(" A list of all {} messages ".format(name).center(78, '-'))
                for args, kwargs in self._cache[name]:
                    print(end="    ")
                    print(*args, **kwargs)
        print('-'*78)



pylog = PyLog()
setattr(wrapcrash, 'pylog', pylog)


class MsgExtra(object):
    _msgstack = [None]
    def __init__(self, msg = None):
        self.msg = msg

    def __enter__(self):
        self._msgstack.append(self.msg)
        return None

    def __exit__(self, *args):
        self._msgstack.pop()
    def __str__(self):
        return str(self._msgstack[-1])

setattr(wrapcrash, 'MsgExtra', MsgExtra)

# Check whether we output to a real file.

def isfileoutput():
    if (sys.stdout.isatty()):
        return False
    mode = os.fstat(sys.stdout.fileno())[stat.ST_MODE]
    return stat.S_ISREG(mode)

# Return the current nsproxy
try:
    __init_proxy = readSymbol("init_nsproxy")
except:
    __init_proxy = None

__proxy = __init_proxy
def get_nsproxy():
    return __proxy

def set_nsproxy(pid = None):
    global __proxy
    if (pid == None):
        __proxy = __init_proxy
    else:
        taskaddr = pid_to_task(pid)
        if (taskaddr):
            task = readSU("struct task_struct", taskaddr)
            __proxy = task.nsproxy
        else:
            print("There is no PID={}".format(pid))
            sys.exit(0)

# Some kernels use a simple integer and some use atomic_t wrapper
# This subroutine returns a.counter if argument is atomic_t or
# just argument without any changes otherwise
def atomic_t(o):
    try:
        return o.counter
    except AttributeError:
        return o

# Process common (i.e. common for all pykdump scripts) options.
from optparse import OptionParser, Option
def __epythonOptions():
    """Process epython common options and filter them out"""

    op = OptionParser(add_help_option=False, option_class=Option)
    op.add_option("--experimental", dest="experimental", default=0,
              action="store_true",
              help="enable experimental features (for developers only)")

    op.add_option("--debug", dest="debug", default=-1,
              action="store", type="int",
              help="enable debugging output")

    op.add_option("--timeout", dest="timeout", default=120,
              action="store", type="int",
              help="set default timeout for crash commands")
    op.add_option("--maxel", dest="Maxel", default=10000,
              action="store", type="int",
              help="set maximum number of list elements to traverse")
    op.add_option("--usens", dest="usens",
              action="store", type="int",
              help="use namespace of the specified PID")

    op.add_option("--reload", dest="reload", default=0,
              action="store_true",
              help="reload already imported modules from Linuxdump")

    op.add_option("--dumpcache", dest="dumpcache", default=0,
              action="store_true",
              help="dump API caches info")

    op.add_option("--ofile", dest="filename",
                  help="write report to FILE", metavar="FILE")

    op.add_option("--ehelp", default=0, dest="ehelp",
                  action = "store_true",
                  help="Print generic epython options")

    if (len(sys.argv) > 1):
        (aargs, uargs) = __preprocess(sys.argv[1:], op)
    else:
        aargs = uargs = []

    (o, args) = op.parse_args(aargs)
    wrapcrash.experimental = API_options.experimental = o.experimental
    global debug, __timeout_exec
    if (o.debug != -1):
        debug = o.debug
    API_options.debug = gen.debug = debug

    if (o.ehelp):
        op.print_help()
        print ("Current debug level=%d" % debug)
    # pdir <module 'pdir' from '/tmp/pdir.py'>
    # thisdir <module 'thisdir' from './thisdir.pyc'>
    # subdir.otherdir <module 'subdir.otherdir' from './subdir/otherdir.pyc'>

    # Do not reload from /pykdump/ - this is dangerous
    # Do not reload from mpydump.so - it makes no sense as it is
    # immutable
    # We do not reload __main__
    if (o.reload):
        purge_memoize_cache(CU_PYMOD)
        PY_select_purge()
        for k, m in list(sys.modules.items())[:]:
            if (hasattr(m, '__file__')):
                mod1 = k.split('.')[0]
                fpath = m.__file__
                # Do not reload if there is no such file
                if (not os.path.isfile(fpath)):
                    continue
                # Don't reload pykdump/
                if ( mod1 in ('pykdump', '__main__')):
                    continue
                if (debugReload > 1):
                    print(k, fpath)

                #del sys.modules[k]
                # Befor reloading, delete DCache objects related
                # to this module
                DCache.perm._delmodentries(m)
                importlib.reload(m)
                if (debugReload):
                    print ("--reloading", k)

    if  (o.timeout):
        set_default_timeout(o.timeout)
        crash.default_timeout = o.timeout
        # Purge the CU_TIMEOUT caches if we _increase_ the timeout
        # This makes sense if some commands did not complete and we
        # re-run with bigger timeout
        if (o.timeout > __timeout_exec):
            purge_memoize_cache(CU_TIMEOUT)
        __timeout_exec = o.timeout
    if (o.Maxel):
        wrapcrash._MAXEL = o.Maxel

    # Reset nsproxy every time
    set_nsproxy(None)
    if  (o.usens):
        print(" *=*=* Using namespaces of PID {}  *=*=*".format(o.usens))
        set_nsproxy(o.usens)

    if (o.filename):
        sys.stdout = open(o.filename, "w")

    sys.argv[1:] = uargs
    #print ("EPYTHON sys.argv=", sys.argv)

    API_options.dumpcache = o.dumpcache
    del op

# Preprocess options, splitting them into these for API_wide and those
# userscript-specific
def __preprocess(iargv,op):
    """Preprocess options separating these controlling API
    from those passed to program as arguments
    """
    # Split the arguments into API/app

    aargv = []                              # API args
    uargv = []                              # Application args

    #print ("iargv=", iargv)

    while(iargv):
        el = iargv.pop(0)
        if (el and (el[:2] == '--' or el[0] == '-')):
            # Check whether this option is present in optparser's op
            optstr = el.split('=')[0]
            opt =  op.get_option(optstr)
            #print ("el, opt", el, opt)
            if (opt):
                nargs = opt.nargs
                aargv.append(el)
                # If we don't have '=', grab the next element too
                if (el.find('=') == -1 and nargs):
                    aargv.append(iargv.pop(0))
            else:
                uargv.append(el)
        else:
            uargv.append(el)
    #print ("aargv=", aargv)
    #print ("uargv", uargv)
    return (aargv, uargv)

# Format sys.argv in a nice way
def argv2s(argv):
    out = ['']
    for i, o in enumerate(argv):
        if (i == 0):
            o = os.path.basename(o)
        if (' ' in o):
            out.append('"{}"'.format(o))
        else:
            out.append(o)
    out.append('')
    return ' '.join(out)


# This function is called on every 'epython' invocation
# It is called _before_ we  start the real script
# This is done by 'epython' command.
# Here we can print information messages  and initialize statistics

re_apidebug=re.compile(r'^--apidebug=(\d+)$')
def enter_epython():
    # Purge temp entries in DCache
    DCache.cleartmp()
    global t_start, t_start_children, t_starta, pp
    ost = os.times()
    t_start = ost[0]+ost[1]
    t_start_children = ost[2] + ost[3]
    t_starta = time.time()

    # We might redefine stdout every time we execute a command...
    # We expect stdout supporting utf-8
    sys.stdout.reconfigure(encoding='utf-8')

    pp = pprint.PrettyPrinter(indent=4)

    pylog.cleanup()     # Do cleanup every time
    #print ("Entering Epython")

    # Process hidden '--apidebug=level' and '--reload' options
    # filtering them out from sys.argv. Save the old copy in sys.__oldargv
    sys.__oldargv = sys.argv.copy()
    __epythonOptions()

    # The dumpfile name can optionally have extra info appended, e.g.
    # /Dumps/Linux/test/vmcore-netdump-2.6.9-22.ELsmp  [PARTIAL DUMP]
    dumpfile = sys_info.DUMPFILE.split()[0]
    #cwd = os.getcwd()
    dumpfile = os.path.abspath(dumpfile)
    text = " %s (%s) " % (dumpfile, sys_info.RELEASE)
    lpad = (77-len(text))//2
    # Print vmcore name/path when not on tty
    if (isfileoutput()):
        # Print executed command
        print("\n   {:*^60s}".format(argv2s(sys.__oldargv)))
        print (" {:o^77s}".format(text))

    # Use KVADDR
    set_readmem_task(0)

    # Insert directory of the file to sys.path
    pdir = os.path.dirname(sys.argv[0])
    #print ("pdir=", pdir)
    # We need to remove it in exit_epython
    sys.path.insert(0, pdir)
    #raise Exception("enter_epython")


# We call this when exiting epython
def exit_epython():
    # Remove prog directory that we have inserted
    sys.path.pop(0)
    if API_options.dumpcache:
        #BaseStructInfo.printCache()
        #wrapcrash.BaseTypeinfo.printCache()
        pass
    pylog.onexit()
    cleanup()


def cleanup():
    set_readmem_task(0)
    try:
        ost = os.times()
        parent_t = ost[0] + ost[1] - t_start
        child_t = ost[2] + ost[3] - t_start_children
        if (abs(child_t) > 0.001):
            child_s = ", Child processes: %6.2fs" % child_t
        else:
            child_s = ""
        print ("\n ** Execution took %6.2fs (real) %6.2fs (CPU)%s" % \
                                        (time.time() - t_starta,
                                         parent_t, child_s))
    except IOError as v:
        print(v, file=sys.stderr)
    try:
        sys.stdout.flush()
    except BrokenPipeError as v:
        print(v, file=sys.stderr)
        pass



# The following function is used to do some black magic - adding methods
# to classes dynamically after dump is open.
# E.g. we cannot obtain struct size before we have access to dump

def funcToMethod(func,clas,method_name=None):
    """This function adds a method dynamically"""
    import new
    method = new.instancemethod(func,None,clas)
    if not method_name: method_name=func.__name__
    setattr(clas, method_name, method)



# For fbase specified as 'nfsd' find all files like nfds.o, nfsd.ko,
# nfsd.o.debug and nfsd.ko.debug that are present in a given directory

def possibleModuleNames(topdir, fbase):
    """Find filenames matching a given module name"""
    if (topdir == None):
        return None
    exts = (".ko.debug", ".o.debug", ".ko", ".o")
    lfb = len(fbase)
    #print ("++ searching for", fbase, " at", topdir)

    for d, dummy, files in os.walk(topdir):
        for f in files:
            if (f.find(fbase) != 0):
                continue
            ext = f[lfb:]
            for e in exts:
                if (ext == e):
                    return os.path.join(d, fbase + e)
    return None


# Loading extra modules. Some defauls locations for debuginfo:

# RH /usr/lib/debug/lib/modules/uname/...
# CG /usr/lib/kernel-image-2.6.10-telco-1.27-mckinley-smp-dbg/lib/modules/2.6.10-telco-1.27-mckinley-smp/...

# So we'll try these directories first, then the default /lib/modules/uname,
# then the dump directory

# If we load module successfully, we receive
#  MODULE   NAME          SIZE  OBJECT FILE
# f8a95800  sunrpc      139173  /data/Dumps/test/sunrpc.ko.debug


__loaded_Mods = {}
def loadModule(modname, ofile = None, altname = None):
    """Load module file into crash"""

    # In some cases we load modules renaming them.
    # In this case modname is the original name (used to search for debug)
    # and altname is the name in 'mod' output
    if (not altname):
        altname = modname
    try:
        return __loaded_Mods[modname]
    except KeyError:
        pass

    if (debug > 1):
        print ("Starting module search", modname)
    if (ofile == None):
        for t in sys_info.debuginfo:
            if (debug > 1):
                print (t)
            # Some modules use different names in file object and lsmod, e.g.:
            # dm_mod -> dm-mod.ko
            for mn in (modname, modname.replace("_", "-")):
               ofile = possibleModuleNames(t, mn)
               if (ofile):
                   break
            if (ofile):
                break
        if (debug > 1):
            print ("Loading", ofile)
    if (ofile == None):
        return False
    # If we specify a non-loaded module, exec_crash_command does not return
    if (debug > 1):
        print ("Checking for altname")
    if (not altname in lsModules()):
        return False
    if (debug > 1):
        print ("Trying to insert", altname, ofile)
    rc = exec_crash_command("mod -s %s %s" % (altname, ofile))
    success = (rc.find("MODULE") != -1)
    __loaded_Mods[modname] = success
    # Invalidate typeinfo caches
    purge_typeinfo()
    return success

# Unload module

def delModule(modname):
    #print __loaded_Mods
    try:
        del __loaded_Mods[modname]
        exec_crash_command("mod -d %s" % modname)
        if (debug):
            print ("Unloading", modname)
    except KeyError:
        pass

# get modules list. We need it mainly to find
__mod_list = []
def lsModules():
    if (len(__mod_list) > 1):
        return __mod_list

    try:
        # On older kernels, we have module_list
        kernel_module = sym2addr("kernel_module")
        if (kernel_module):
            module_list = readSymbol("module_list")
            for m in readStructNext(module_list, "next", inchead = False):
                if (long(m) != kernel_module):
                    __mod_list.append(m.name)
        else:
            # On new kernels, we have a listhead
            lh = ListHead(sym2addr("modules"), "struct module")
            for m in lh.list:
               __mod_list.append(m.name)
    except:
        # If anything went wrong, return a partial list
        pass
    return __mod_list


# Execute 'sys' command and put its split output into a dictionary
# Some names contain space and should be accessed using a dict method, e.g.
# sys_info["LOAD AVERAGE"]
#
# A special case:
   #DUMPFILES: vmcore1 [PARTIAL DUMP]
              #vmcore2 [PARTIAL DUMP]
              #vmcore3 [PARTIAL DUMP]
              #vmcore4 [PARTIAL DUMP]

def old_doSys():
    """Execute 'sys' commands inside crash and return the parsed results"""
    for il in exec_crash_command("sys").splitlines():
        spl = il.split(':', 1)
        if (len(spl) == 2):
            sys_info.__setattr__(spl[0].strip(), spl[1].strip())

def _doSys():
    """Execute 'sys' commands inside crash and return the parsed results"""
    key = 'UNKNOWN'
    for il in exec_crash_command("sys").splitlines():
        spl = il.split(':', 1)
        if (len(spl) == 2):
            key = spl[0].strip()
            sys_info[key] = spl[1].strip()
        else:
            sys_info[key] += '|' + il.strip()
    # If there are DUMPFILES, fill-in DUMPFILE for printing
    dfiles = sys_info.get('DUMPFILES', None)
    if (dfiles is None):
        return
    out = []
    for v in dfiles.split('|'):
        out.append(v.split()[0].strip())
    sys_info['DUMPFILE'] = ','.join(out)

# -----------  initializations ----------------

# What happens if we use 'epython' command several times without
# leaving 'crash'? The first time import statements really do imports running
# some code, next time the import statement just sees that the code is already
# imported and it does not execute statements inside modules. So the code
# here is executed only the first time we import API (this might change if we
# purge modules, e.g. for debugging).
#
# But the function enter_python() is called every time - the first time when
# we do import, next times as it is registered as a hook


pointersize = getSizeOf("void *")
_intsize = getSizeOf("int")
_longsize = getSizeOf("long int")
sys_info.pointersize = wrapcrash.pointersize = pointersize
sys_info.pointermask = 2**(pointersize*8)-1
_doSys()

# Check whether this is a live dump
if (sys_info.DUMPFILE.find("/dev/") == 0):
    sys_info.livedump = gen.livedump = True
else:
    sys_info.livedump = gen.livedump = False


# Check the kernel version and set HZ
kernel = re.search(r'^(\d+\.\d+\.\d+)', sys_info.RELEASE).group(1)
sys_info.kernel = gen.KernelRev(kernel)
sys_info.HZ = HZ

# Convert CPUS to integer. Usually we just have an integer, but sometimes
# CPUS: 64 [OFFLINE: 32]
sys_info.CPUS = int(sys_info.CPUS.split()[0])

# Extract hardware from MACHINE
sys_info.machine = wrapcrash.machine = sys_info["MACHINE"].split()[0]

# This is where debug kernel resides
try:
    sys_info.DebugDir = os.path.dirname(sys_info["DEBUG KERNEL"])
except KeyError:
    sys_info.DebugDir = os.path.dirname(sys_info["KERNEL"])

# A list of top directories where we will search for debuginfo
kname = sys_info.RELEASE
RHDIR = "/usr/lib/debug/lib/modules/" + kname
CGDIR = "/usr/lib/kernel-image-%s-dbg/lib/modules/%s/" %(kname, kname)
debuginfo = [RHDIR, CGDIR]

if (sys_info.DebugDir == ""):
    sys_info.DebugDir ="."
if (not  sys_info.livedump):
    # Append the directory of where the dump is located
    debuginfo.append(sys_info.DebugDir)
else:
    # Append the current directory (useful for development)
    debuginfo.insert(0, '.')
# Finally, there's always a chance that this kernel is compiled
# with debuginfo
debuginfo.append("/lib/modules/" + kname)
sys_info.debuginfo = debuginfo


# As we cannnot analyze 32-bit dump with a 32-bit crash, Python
# is built for the same arch. So on Python 2, 'int matches' C-int size
if (pointersize == 4):
    PTR_SIZE = 4
elif (pointersize == 8):
    PTR_SIZE = 8
else:
    raise TypeError("Cannot find pointer size on this arch")

if (_intsize == 4):
    readInt = readS32
    readUInt = readU32
    uInt =  unsigned32
    INT_MASK = 0xffffffff
    INT_SIZE = 4
    BITS_PER_INT = 32
elif (_intsize == 8):
    readInt = readS64
    readUInt = readU64
    uInt =  unsigned64
    INT_MASK = 0xffffffffffffffff
    INT_SIZE = 8
    BITS_PER_INT = 64
else:
    raise TypeError("Cannot find int size on this arch")

if (_longsize == 4):
    readLong = readS32
    readULong = readU32
    uLong = unsigned32
    LONG_MASK = 0xffffffff
    LONG_SIZE = 4
    BITS_PER_LONG = 32
elif (_longsize == 8):
    readLong = readS64
    readULong = readU64
    uLong = unsigned64
    LONG_MASK = 0xffffffffffffffff
    LONG_SIZE = 8
    BITS_PER_LONG = 64
else:
    raise TypeError("Cannot find long size on this arch")


INT_MAX = ~0&(INT_MASK)>>1
LONG_MAX = ~0&(LONG_MASK)>>1

def ALIGN(addr, align):
    return (long(addr) + align-1)&(~(align-1))

HZ = sys_info.HZ

# Is this a per_cpu symbol? At this moment we do not check for modules yet
if (symbol_exists("__per_cpu_start") and symbol_exists("__per_cpu_end")):
    __per_cpu_start = sym2addr("__per_cpu_start")
    __per_cpu_end = sym2addr("__per_cpu_end")
    def is_percpu_symbol(addr):
        return (addr >= __per_cpu_start and addr < __per_cpu_end)
else:
    def is_percpu_symbol(addr):
        return False

# A special object to be used instead of readSymbol, e.g.
# readSymbol("xtime") -> PYKD.xtime
# we do not try to workaround Python mangling of attrs starting with
# __, as  presumably using names that begin with double underscores
# in C is "undefined behavior", which is the technical term for
# "don't do it."

class __PYKD_reader(object):
    def __getattr__(self, attrname):
        return readSymbol(attrname)

PYKD = __PYKD_reader()

enter_epython()

# Hooks used by C-extension
sys.enterepython = enter_epython
sys.exitepython = exit_epython

if (API_options.debug):
    print ("-------PyKdump %s-------------" % pykdump.__version__)
#atexit.register(cleanup)

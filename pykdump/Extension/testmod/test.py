#!/usr/bin/env python

# Time-stamp: <2018-05-18 14:18:19 alexs>

# --------------------------------------------------------------------
# (C) Copyright 2006-2018 Hewlett-Packard Development Company, L.P.
#
# Author: Alex Sidorenko <asid@hp.com>
#
# --------------------------------------------------------------------

# Test low-level API


import sys
#sys.path.insert(0, "../..")
import time

#import cProfile

from pykdump.API import *

import pykdump.Generic as Gen
from pykdump.Generic import TypeInfo, VarInfo, SUInfo


import crash
loadModule("testmod", "testmod.ko")

#pp.pprint(crash.gdb_typeinfo("struct ASID"))

addr = sym2addr("asid")
asid = readSU("struct ASID", addr)



nfailed = 0
ntests = 0

ntests += 1
if(asid.li == 123456789 and  asid.i2 == -555):
    pass
else:
    print ("Integers failed")
    nfailed += 1

# tPtr (char *) -> SmartString
ntests += 1
__vals = ("one", "two")
for i in range(2):
    cp = asid.dpchar[i]
    s = SmartString(cp)
    if (s != __vals[i]):
        print ("tPtr->SmartString failed")
        nfailed += 1

# Global boolean
ntests += 1
if (PYKD.true_ == True and  PYKD.false_ == False):
    pass
else:
    print ("Global boolean variables failed")
    nfailed += 1

# Boolean bitfields
ntests += 1
if (asid.booli1 == True and  asid.booli2 == False and \
    asid.boolbf1 == False and asid.boolbf2 == True):
    pass
else:
    print ("Boolean bitfields in struct failed")
    nfailed += 1

ntests += 1
# Boolean arrays
for i in range(6):
    v = True if (i%3) else False
    if (asid.boolarr[i] != v):
        print ("Boolean arrays failed")
        nfailed += 1
        break


ntests += 1
if(asid.bf1 == 1 and  asid.bf2 == 2 and  asid.bf3 == -2 and asid.bf4 == 123):
    pass
else:
    print ("Bitfields failed")
    nfailed += 1

ntests += 1
if (asid.f1.ff.bb == "bbstring" and  asid.f2.buf == "buf"):
    pass
else:
    print ("Strings/Chararrays failed")
    nfailed += 1

ntests += 1
if (asid.sarr[0].a0 == 11 and asid.sarr[1].a0 == 22 and asid.sarr[2].a0 == 33):
    pass
else:
    print ("Struct arrays failed")
    nfailed += 1

# Integer Pointers 


ntests += 1
if (asid.lptr.Deref == 7 and asid.iptr.Deref == 6 \
    and asid.ipptr.Deref.Deref == 6 and asid.ippptr.Deref.Deref.Deref == 6):
    pass
else:
    print ("Integer pointers failed")
    nfailed += 1


# Integer multidim arrays
ntests += 1
iarr2 = asid.iarr2
for i in range(5):
    for j in range(3):
        if (iarr2[i][j] != i*10 + j):
             print ("Multidim Integer arrays failed")
             nfailed += 1
             break

# Pointer arithmetic
ntests += 1

sarrptr = asid.sarrptr
if (sarrptr[0].a0 == 11 and sarrptr[1].a0 == 22 and sarrptr[2].a0 == 33 and \
    (sarrptr+2).a0 == 33):
    pass
else:
    print ("Pointer aritmetic failed")
    print (sarrptr[0].a0, sarrptr[1].a0, sarrptr[2].a0)
    nfailed += 1

# Pointer arrays
ntests += 1

ptrarr = asid.ptrarr
if (ptrarr[0].Deref.a0 == 11 and ptrarr[1].Deref.a0 == 22 \
    and ptrarr[2].Deref.a0 == 33):
    pass
else:
    print ("Pointer arrays failed")
    print (ptrarr[0].Deref.a0, ptrarr[1].Deref.a0, ptrarr[2].Deref.a0)
    nfailed += 1

# Function pointers
ntests += 1
if (addr2sym(asid.funcptr) == "testfunc"):
    pass
else:
    print ("Function Pointers")
    print (addr2sym(asid.funcptr))
    nfailed += 1


def dPrint(v):
    print(type(v), repr(v))

# Various pointers
nptr = readSymbol("asid_ptr")

ntests += 1
for i in range(3):
    a0 = nptr.ii.a0[i]
    a3 = nptr.ii.a3[i]
    if (a0.a0 == i and a3.a0 == i):
        pass
    else:
        print (a0.a0, a3.a0, i)
        print ("Various pointers failed")
        nfailed += 1
        break

print ("%d tests run, %d failed" % (ntests, nfailed))

sys.exit(0)

iPtr = readSymbol("iPtr")
#print (repr(iPtr))

iPtrarr =  readSymbol("iPtrarr")
#print (type(iPtrarr), repr(iPtrarr))


cptr = readSymbol("charPtrArr")

#dPrint(cptr[0])

#dPrint(nptr.ii.a0[1])
#dPrint(nptr.ii.a3[1])

for i in range(3):
    a0 = nptr.ii.a0[i]
    a3 = nptr.ii.a3[i]
    print ((a0.a0, a0.b0), (a3.a0, a3.b0))



sys.exit(0)

print (" ------------ Performance testing --------------")

addr = sym2addr("asid")

tot = 100000

t0 = time.time()
for i in xrange(0, tot):
    readPtr(addr)
    
print ("readPtr: %10.0f/s" % (tot/(time.time() - t0)))

t0 = time.time()
size = 8
for i in xrange(0, tot):
    readIntN(addr, size, True)
    
print ("readinteger: %10.0f/s" % (tot/(time.time() - t0)))

t0 = time.time()
for i in xrange(0, tot):
    s = getStructInfo("struct ASID")

print ("SUInfo: %10.0f/s" % (tot/(time.time() - t0)))

t0 = time.time()
for i in xrange(0, tot):
    asid.li

print ("struct.integer: %10.0f/s" % (tot/(time.time() - t0)))

t0 = time.time()
for i in xrange(0, tot):
    asid.lptr

print ("(struct.iptr: %10.0f/s" % (tot/(time.time() - t0)))

t0 = time.time()
for i in xrange(0, tot):
    asid.lptr.Deref

print ("*(struct.iptr): %10.0f/s" % (tot/(time.time() - t0)))

t0 = time.time()
for i in xrange(0, tot):
    s = readSU("struct ASID", addr)

print ("readSU: %10.0f/s" % (tot/(time.time() - t0)))

s = readSU("struct ASID", addr)
fi = s.PYT_sinfo["li"]
reader = fi.reader
faddr = addr + fi.offset
t0 = time.time()
for i in xrange(0, tot):
    reader(faddr)

print ("intReader: %10.0f/s" % (tot/(time.time() - t0)))

fi = s.PYT_sinfo["sptr"]
reader = fi.reader
faddr = addr + fi.offset
t0 = time.time()
for i in xrange(0, tot):
    reader(faddr)
    
    
print ("ptrReader: %10.0f/s" % (tot/(time.time() - t0)))


t0 = time.time()
for i in xrange(0, tot):
    fi = s.PYT_sinfo["sptr"]
    reader = fi.reader
    
print ("getattr/reader: %10.0f/s" % (tot/(time.time() - t0)))

t0 = time.time()
for i in xrange(0, tot):
    tptr = tPtr(addr, fi)
    
print ("tPtr: %10.0f/s" % (tot/(time.time() - t0)))



# Profiler stuff

def testfunc():
    for i in xrange(0, tot):
        #asid.lptr
        asid.lptr.Deref

cProfile.run('testfunc()')

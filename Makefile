#! -*- makefile -*-
#
# Copyright (c) 2019 Canonical Ltd.
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

PYKDUMP_SO_DIR := $(CURDIR)/pykdump/Extension
PYKDUMP_SO := $(PYKDUMP_SO_DIR)/pykdump.so

CRASH_DIR := $(CURDIR)/.crash
CRASH := $(CRASH_DIR)/crash

TMPDIR := $(CURDIR)/.tmp
DESTDIR ?= $(CURDIR)/.build

MAKE_PYKDUMP := $(MAKE) -C $(PYKDUMP_SO_DIR) -f Makefile.pykdump \
	CRASH_DIR=$(CRASH_DIR)

SCRIPTS := shell sysfs

all: crash pykdump install

#
# Install the pykdump and pykdumplib files to DESTDIR
#
install:
	rm -rf $(DESTDIR)
	install -d $(DESTDIR)

	# Install the core pykdump files
	install $(PYKDUMP_SO) $(DESTDIR)
	rsync -a pykdump/pykdump $(DESTDIR)/

	# Install the pykdumplib files
	install $(SCRIPTS) $(DESTDIR)
	rsync -a pykdumplib $(DESTDIR)/

#
# Build the pykdump extension for crash
#
pykdump: $(PYKDUMP_SO)
$(PYKDUMP_SO): Makefile.pykdump
	cp Makefile.pykdump $(PYKDUMP_SO_DIR)
	$(MAKE_PYKDUMP)

#
# Download and build crash
#
crash: $(CRASH)
$(CRASH):
	test -d $(TMPDIR) && rm -rf $(TMPDIR) || true
	test -d $(CRASH_DIR) && rm -rf $(CRASH_DIR) || true
	mkdir -p $(TMPDIR)
	cd $(TMPDIR) && pull-lp-source -d crash $(shell lsb_release -c -s)
	cd $(TMPDIR) && dpkg-source -x *.dsc $(CRASH_DIR)
	cd $(CRASH_DIR) && debian/rules build

#
# Cleaning rule
#
clean:
	rm -rf $(CRASH_DIR) $(TMPDIR) $(DESTDIR)
	$(MAKE_PYKDUMP) clean

.PHONY: crash pykdump

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

PYKDUMP_SO := $(CURDIR)/pykdump/Extension/pykdump.so
CRASH := $(CURDIR)/crash/crash

PYKDUMP_SO_DIR := $(dir $(PYKDUMP_SO))
CRASH_DIR := $(dir $(CRASH))

MAKE_PYKDUMP := $(MAKE) -C $(PYKDUMP_SO_DIR) -f Makefile.pykdump \
	CRASH_DIR=$(CRASH_DIR)

#
# Build the pykdump extension for crash
#
pykdump: $(PYKDUMP_SO)
$(PYKDUMP_SO): $(CRASH) Makefile.pykdump
	cp Makefile.pykdump $(PYKDUMP_SO_DIR)
	$(MAKE_PYKDUMP)

#
# Download and build crash
#
crash: $(CRASH)
$(CRASH): $(CRASH_DIR)/Makefile
	rm -rf .source $(CRASH_DIR)
	mkdir .source
	cd .source && pull-lp-source -d crash $(shell lsb_release -c -s)
	dpkg-source -x .source/*.dsc $(CRASH_DIR)
	rm -rf .source
	cd $(CRASH_DIR) && make

#
# Cleaning rule
#
clean:
	rm -rf .source $(CRASH_DIR)
	$(MAKE_PYKDUMP) clean

.PHONY: crash pykdump

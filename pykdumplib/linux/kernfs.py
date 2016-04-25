#!/usr/bin/env python
#
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

#
# Kernfs functions
#

from __future__ import print_function

from pykdump.API import *

from pykdumplib.linux import rbtree
from pykdumplib import utils


KERNFS_TYPE_MASK = 0x000f
KERNFS_DIR = enumerator_value('KERNFS_DIR')
KERNFS_FILE = enumerator_value('KERNFS_FILE')
KERNFS_LINK = enumerator_value('KERNFS_LINK')


def _print_node(node, indent=0):
    '''
    Pretty print a kernfs node
    '''
    sindent = ' ' * indent

    if node.type == KERNFS_DIR:
            utils.cprint('%s%s' % (sindent, node.name), end='', type='dir')
            print(' (%x)' % node.addr())

    elif node.type == KERNFS_LINK:
            utils.cprint('%s%s' % (sindent, node.name), end='', type='link')
            print(' (%x) -> ' % node.addr(), end='')

            target = Node(node.struct.symlink.target_kn)
            if target.type == KERNFS_DIR:
                utils.cprint(target.fullpath(), end='', type='dir')
            else:
                print(target.fullpath(), end='')
            print(' (%x)' % target.addr())

    else:
        print('%s%s (%x)' % (sindent, node.name, node.addr()))


@utils.singleton
class Node(object):
    '''
    Kernfs node class
    '''
    struct_type = 'struct kernfs_node'

    def __init__(self, obj):
        self.struct = obj
        self.name = obj.name
        self.type = obj.flags & KERNFS_TYPE_MASK
        self._parent = obj.parent

    def addr(self):
        return Addr(self.struct)

    def parent(self):
        return Node(self._parent)

    def fullpath(self, limit=100):
        '''
        Return the full path going all the way up to the root node. Limit to
        100 to prevent infinite loops.
        '''
        path = []
        node = self
        while node and len(path) < limit:
            path.insert(0, node.name)
            node = node.parent()
        if len(path) == limit:
            return 'Bad kernfs_node'
        return '/'.join(path)

    def iterchildren(self):
        '''
        Iterate through all children (in sorted order)
        '''
        if self.type != KERNFS_DIR:
            return

        tree = rbtree.Tree(self.struct.dir.children)
        for node in tree.iternodes():
            yield Node(container_of(node.struct, 'struct kernfs_node', 'rb'))

    def pretty_print(self, level=1, indent=0):
        '''
        Pretty print a node (tree)
        '''
        _print_node(self, indent)

        if level == 1:
            return

        if self.type == KERNFS_DIR:
            for child in self.iterchildren():
                child.pretty_print(level - 1, indent + 3)

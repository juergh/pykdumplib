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
# RB tree functions
#
# See:
#   - include/linux/rbtree.h
#   - lib/rbtree.c
#

from __future__ import print_function

from pykdump.API import *

from pykdumplib import utils


@utils.singleton
class Node(object):
    '''
    Red-black (rb) tree node class
    '''
    struct_type = 'struct rb_node'

    def __init__(self, obj):
        self.struct = obj
        self._parent = obj.__rb_parent_color & ~3
        self._rb_left = obj.rb_left
        self._rb_right = obj.rb_right

    def parent(self):
        return Node(self._parent)

    def left(self):
        return Node(self._rb_left)

    def right(self):
        return Node(self._rb_right)

    def next(self):
        '''
        Return the next node (in sort order)
        '''
        if self.parent() == self:
            return

        # If we have a right-hand child, go down and then left as far
        # as we can
        node = self.right()
        if node:
            while node and node.left():
                node = node.left()
            return node

        # No right-hand children. Everything down and left is smaller than us,
        # so any 'next' node must be in the general direction of our parent.
        # Go up the tree; any time the ancestor is a right-hand child of its
        # parent, keep going up. First time it's a left-hand child of its
        # parent, said parent is our 'next' node.
        node = self
        parent = node.parent()
        while parent and node == parent.right():
            node = parent
            parent = node.parent()

        return parent


@utils.singleton
class Tree(object):
    '''
    Red-black (rb) tree class
    '''
    struct_type = 'struct rb_root'

    def __init__(self, obj):
        self.struct = obj
        self._rb_node = obj.rb_node

    def firstnode(self):
        '''
        Return the first (left-most) node of the tree
        '''
        node = Node(self._rb_node)
        while node and node.left():
            node = node.left()
        return node

    def iternodes(self):
        '''
        Iterate through all nodes (in sort order) of the tree
        '''
        node = self.firstnode()
        while node:
            yield node
            node = node.next()

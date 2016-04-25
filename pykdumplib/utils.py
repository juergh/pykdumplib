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

from __future__ import print_function

from pykdump.API import *
from pykdump.wrapcrash import StructResult


_font_attr = {
    'bold': '\033[1m',
    'underline': '\033[4m',

    'black': '\033[0;90m',
    'red': '\033[0;91m',
    'green': '\033[0;92m',
    'yellow': '\033[0;93m',
    'blue': '\033[0;94m',
    'purple': '\033[0;95m',
    'cyan': '\033[0;96m',
    'white': '\033[0;97m',

    'off': '\033[0m',
}


_font_attr_type = {
    'link': ('cyan', 'bold'),
    'dir': ('blue', 'bold'),
}


def cprint(*args, **kwargs):
    '''
    Color print
    '''
    type = kwargs.pop('type')
    if type is not None:
        for t in _font_attr_type[type]:
            print(_font_attr[t], end='')

    print(*args, **kwargs)

    if type is not None:
        print(_font_attr['off'], end='')


def singleton(cls):
    '''
    Singleton class decorator
    '''
    cache = {}

    def _getinstance(obj):
        if obj is None or obj == 0:
            return None

        if isinstance(obj, StructResult):
            struct = obj
            addr = Addr(obj)
        else:
            struct = readSU(cls.struct_type, obj)
            addr = obj
        if addr not in cache:
            cache[addr] = cls(struct)
        return cache[addr]

    return _getinstance


def dec(name, *args, **kwargs):
    '''
    Decorator for subcommand arguments and help text
    '''
    def _decorator(func):
        # Because of the semantics of decorator composition if we just append
        # to the options list positional options will appear to be backwards
        func.__dict__.setdefault(name, []).insert(0, (args, kwargs))
        return func
    return _decorator


def add_help(*args, **kwargs):
    return dec('help', *args, **kwargs)


def add_arg(*args, **kwargs):
    return dec('arg', *args, **kwargs)


def add_subcommand_parsers(parser, module):
    '''
    Add subparsers for the subcommands
    '''
    subparsers = parser.add_subparsers(title='commands')

    # Walk through the 'do_' functions
    for attr in (a for a in dir(module) if a.startswith('do_')):
        cmd_name = attr[3:].replace('_', '-')
        cmd_cb = getattr(module, attr)
        cmd_desc = cmd_cb.__doc__ or ''
        cmd_help = getattr(cmd_cb, 'help', [])
        cmd_args = getattr(cmd_cb, 'arg', [])

        parser = subparsers.add_parser(cmd_name, help=cmd_help[0][0][0],
                                       description=cmd_desc, add_help=False)

        parser.add_argument('-h', '--help', action='help')
        for (args, kwargs) in cmd_args:
            parser.add_argument(*args, **kwargs)

        parser.set_defaults(func=cmd_cb)

# Copyright (c) 2009 Type Supply LLC

from __future__ import print_function, division, absolute_import
from fontTools.misc.psCharStrings import CFF2Subr
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.cffLib.specializer import specializeCommands


class MergeTypeError(TypeError):
    def __init__(self, point_type, pt_index, m_index, default_type):
        error_msg = """{point_type} at point index {pt_index} in master"
{m_index}' differs from the default font point "
type {default_type}""".format(
                                        point_type=point_type,
                                        pt_index=pt_index,
                                        m_index=m_index,
                                        default_type=default_type)

        super(MergeTypeError, self).__init__(error_msg)


def commandsToProgram(commands, max_stack):
    """Takes a commands list as returned by programToCommands() and converts
    it back to a T2CharString program list."""
    program = []
    for op, args in commands:
        num_args = len(args)
        # some of the args may be blend lists, and some may be
        # single coordinate values.
        i = 0
        stack_use = 0
        while i < num_args:
            arg = args[i]
            if type(arg) is not tuple:
                program.append(arg)
                i+= 1
                stack_use += 1
            else:
                """ The arg is a tuple of blend values.
                These are each (master 0,master 1..master n)
                Look forward to see how many we can combine.
                """
                num_masters = len(arg)
                blendlist = [arg]
                i+= 1
                stack_use += 1 # for the num_blends arg
                while (i < num_args) and (type(args[i]) is  tuple):
                    blendlist.append(args[i])
                    i += 1
                    stack_use += num_masters
                    if stack_use + num_masters > max_stack:
                        break
                num_blends = len(blendlist)
                # append the 'num_blends' default font values
                for arg in blendlist:
                    program.append(arg[0])
                # for each arg, append the region deltas
                for arg in blendlist:
                    program.extend([argn - arg[0] for argn in arg[1:]])
                program.append(num_blends)
                program.append('blend')
        if op:
            program.append(op)
    return program


class CFF2CharStringMergePen(T2CharStringPen):
    """Pen to merge Type 2 CharStrings.
    """
    def __init__(self, default_commands, num_masters, master_idx):
        super(
            CFF2CharStringMergePen,
            self).__init__(width=None, glyphSet=None, CFF2=True)
        self.pt_index = 0
        self._commands = default_commands
        self.m_index = master_idx
        self.num_masters = num_masters

    def _p(self, pt):
        p0 = self._p0
        pt = self._p0 = self.roundPoint(pt)
        return [pt[0]-p0[0], pt[1]-p0[1]]

    def add_point(self, point_type, pt_coords):

        if self.m_index == 0:
            self._commands.append([point_type, [pt_coords]])
        else:
            cmd = self._commands[self.pt_index]
            if cmd[0] != point_type:
                raise MergeTypeError(
                                point_type,
                                self.pt_index,
                                len(cmd[1]),
                                cmd[0])
            cmd[1].append(pt_coords)
        self.pt_index += 1

    def _moveTo(self, pt):
        pt_coords = self._p(pt)
        self.add_point('rmoveto', pt_coords)

    def _lineTo(self, pt):
        pt_coords = self._p(pt)
        self.add_point('rlineto', pt_coords)

    def _curveToOne(self, pt1, pt2, pt3):
        _p = self._p
        pt_coords = _p(pt1)+_p(pt2)+_p(pt3)
        self.add_point('rrcurveto', pt_coords)

    def _closePath(self):
        pass

    def _endPath(self):
        pass

    def restart(self, region_idx):
        self.pt_index = 0
        self.m_index = region_idx
        self._p0 = (0,0)
        
    def getCommands(self):
        return self._commands

    def reorder_blend_args(self):
        """
        For a moveto to lineto, the args are now arranged as:
            [ [master_0 x,y], [master_1 x,y], [master_2 x,y] ]
        We re-arrange this to
        [   [master_0 x, master_1 x, master_2 x],
            [master_0 y, master_1 y, master_2 y]
        ]
        """
        for cmd in self._commands:
            # arg[i] is the set of arguments for this operator from master i.
            args = cmd[1]
            m_args = zip(*args)
            # m_args[n] is now all num_master args for the ith argument
            # for this operation.
            cmd[1] = m_args
            # reduce the variable args to a non-variable arg
            # if the values are all the same.
            for i, arg in enumerate(m_args):
                if max(arg) == min(arg):
                    m_args[i] = arg[0]
            cmd[1] = m_args

    def getCharString(self, private=None, globalSubrs=None, optimize=True):
        self.reorder_blend_args()
        commands = self._commands
        if optimize:
            maxstack = 48 if not self._CFF2 else 513
            commands = specializeCommands(commands,
                                          generalizeFirst=False,
                                          maxstack=maxstack)
        program = commandsToProgram(commands, maxstack)
        charString = CFF2Subr(
            program=program, private=private, globalSubrs=globalSubrs)
        return charString

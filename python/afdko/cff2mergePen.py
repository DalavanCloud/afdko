# Copyright (c) 2009 Type Supply LLC

from __future__ import print_function, division, absolute_import
from fontTools.misc.psCharStrings import CFF2Subr
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.cffLib.specializer import (
                            _categorizeVector,
                            _mergeCategories,
                            _negateCategory,
                            generalizeCommands)


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


def specializeCommands(
                commands,
                ignoreErrors=False,
                generalizeFirst=True,
                preserveTopology=False,
                maxstack=48):

    """
    We perform several rounds of optimizations. They are carefully
    ordered and are:

     0. Generalize commands.
        This ensures that they are in our expected simple form, with
        each line/curve only having arguments for one segment, and using
        the generic form (rlineto/rrcurveto).
        If caller is sure the input is in this form, they can turn off

     1. Combine successive rmoveto operations.

     2. Specialize rmoveto/rlineto/rrcurveto operators into
     horizontal/vertical variants.
        We specialize into some, made-up, variants as well, which
        simplifies following passes.

     3. Merge or delete redundant operations, to the extent requested.
        OpenType spec declares point numbers in CFF undefined.  As such,
        we happily change topology.  If client relies on point numbers
        (in GPOS anchors, or for hinting purposes(what?)) they can turn
        this off.

     4. Peephole optimization to revert back some of the h/v variants
     back into their original "relative" operator (rline/rrcurveto) if
     that saves a byte.

     5. Combine adjacent operators when possible, minding not to go over
     max stack size.

     6. Resolve any remaining made-up operators into real operators.

     I have convinced myself that this produces optimal bytecode (except
     for, possibly one byte each time maxstack size prohibits
     combining.)  YMMV, but you'd be wrong. :-) A dynamic-programming
     approach can do the same but would be significantly slower.
    """

    # 0. Generalize commands.
    if generalizeFirst:
        commands = generalizeCommands(commands, ignoreErrors=ignoreErrors)
    else:
        commands = list(commands)  # Make copy since we modify in-place later.

    # 1. Combine successive rmoveto operations.
    for i in range(len(commands)-1, 0, -1):
        if 'rmoveto' == commands[i][0] == commands[i-1][0]:
            v1, v2 = commands[i-1][1], commands[i][1]
            commands[i-1] = ('rmoveto', [v1[0]+v2[0], v1[1]+v2[1]])
            del commands[i]

    """
    2. Specialize rmoveto/rlineto/rrcurveto operators into
    horizontal/vertical variants.

    We, in fact, specialize into more, made-up, variants that
    special-case when both X and Y components are zero.  This simplifies
    the following optimization passes. This case is rare, but OCD does
    not let me skip it.

     After this round, we will have four variants that use the following
     mnemonics:

      - 'r' for relative,   ie. non-zero X and non-zero Y,
      - 'h' for horizontal, ie. zero X and non-zero Y,
      - 'v' for vertical,   ie. non-zero X and zero Y,
      - '0' for zeros,      ie. zero X and zero Y.

     The '0' pseudo-operators are not part of the spec, but help
     simplify the following optimization rounds.  We resolve them at the
     end.  So, after this, we will have four moveto and four lineto
     variants:

      - 0moveto, 0lineto
      - hmoveto, hlineto
      - vmoveto, vlineto
      - rmoveto, rlineto

     and sixteen curveto variants.  For example, a '0hcurveto' operator
     means a curve dx0,dy0,dx1,dy1,dx2,dy2,dx3,dy3 where dx0, dx1, and
     dy3 are zero but not dx3.
     An 'rvcurveto' means dx3 is zero but not dx0,dy0,dy3.

     There are nine different variants of curves without the '0'.  Those
     nine map exactly to the existing curve variants in the spec:
     rrcurveto, and the four variants hhcurveto, vvcurveto, hvcurveto,
     and vhcurveto each cover two cases, one with an odd number of
     arguments and one without.  Eg. an hhcurveto with an extra argument
     (odd number of arguments) is in fact an rhcurveto.  The operators
     in the spec are designed such that all four of rhcurveto,
     rvcurveto, hrcurveto, and vrcurveto are encodable for one curve.

     Of the curve types with '0', the 00curveto is equivalent to a
     lineto variant.  The rest of the curve types with a 0 need to be
     encoded as a h or v variant.  Ie. a '0' can be thought of a "don't
     care" and can be used as either an 'h' or a 'v'.  As such, we
     always encode a number 0 as argument when we use a '0' variant.
     Later on, we can just substitute the '0' with either 'h' or 'v' and
     it works.

     When we get to curve splines however, things become more
     complicated...  XXX finish this. There's one more complexity with
     splines.  If one side of the spline is not horizontal or vertical
     (or zero), ie. if it's 'r', then it limits which spline types we
     can encode. Only hhcurveto and vvcurveto operators can encode a
     spline starting with 'r', and only hvcurveto and vhcurveto
     operators can encode a spline ending with 'r'. This limits our
     merge opportunities later.
    """
    for i in range(len(commands)):
        op, args = commands[i]

        if op in {'rmoveto', 'rlineto'}:
            c, args = _categorizeVector(args)
            commands[i] = c+op[1:], args
            continue

        if op == 'rrcurveto':
            c1, args1 = _categorizeVector(args[:2])
            c2, args2 = _categorizeVector(args[-2:])
            commands[i] = c1+c2+'curveto', args1+args[2:4]+args2
            continue

    """
    3. Merge or delete redundant operations, to the extent requested.

     TODO
     A 0moveto that comes before all other path operations can be
     removed. though I find conflicting evidence for this.

     TODO
     "If hstem and vstem hints are both declared at the beginning of a
     CharString, and this sequence is followed directly by the hintmask
     or cntrmask operators, then the vstem hint operator (or, if
     applicable, the vstemhm operator) need not be included."

     "The sequence and form of a CFF2 CharString program may be
     represented as: {hs* vs* cm* hm* mt subpath}? {mt subpath}*"

     https://www.microsoft.com/typography/otspec/cff2charstr.htm#
     section3.1

     For Type2 CharStrings the sequence is:
       w? {hs* vs* cm* hm* mt subpath}? {mt subpath}* endchar"
    """

    # Some other redundancies change topology (point numbers).
    if not preserveTopology:
        for i in range(len(commands)-1, -1, -1):
            op, args = commands[i]

            # A 00curveto is demoted to a (specialized) lineto.
            if op == '00curveto':
                assert len(args) == 4
                c, args = _categorizeVector(args[1:3])
                op = c+'lineto'
                commands[i] = op, args
                # and then...

            # A 0lineto can be deleted.
            if op == '0lineto':
                del commands[i]
                continue

            # Merge adjacent hlineto's and vlineto's.
            if (
                i and op in {'hlineto', 'vlineto'} and
                op == commands[i-1][0] and
                type(args[0]) != tuple
               ):
                _, other_args = commands[i-1]
                assert len(args) == 1 and len(other_args) == 1
                commands[i-1] = (op, [other_args[0]+args[0]])
                del commands[i]
                continue

    """
    4. Peephole optimization to revert back some of the h/v variants
    back into their original "relative" operator (rline/rrcurveto) if
    that saves a byte.
    """
    for i in range(1, len(commands)-1):
        op, args = commands[i]
        prv, nxt = commands[i-1][0], commands[i+1][0]

        if op in {'0lineto', 'hlineto', 'vlineto'} and prv == nxt == 'rlineto':
            assert len(args) == 1
            args = [0, args[0]] if op[0] == 'v' else [args[0], 0]
            commands[i] = ('rlineto', args)
            continue

        if (
            op[2:] == 'curveto' and
            len(args) == 5 and
            prv == nxt == 'rrcurveto'
           ):
            assert (op[0] == 'r') ^ (op[1] == 'r')
            if op[0] == 'v':
                pos = 0
            elif op[0] != 'r':
                pos = 1
            elif op[1] == 'v':
                pos = 4
            else:
                pos = 5
            # Insert, while maintaining the type of
            # args (can be tuple or list).
            args = args[:pos] + type(args)((0,)) + args[pos:]
            commands[i] = ('rrcurveto', args)
            continue

    """
    5. Combine adjacent operators when possible, minding not to go over
    max stack size.
    """
    for i in range(len(commands)-1, 0, -1):
        op1, args1 = commands[i-1]
        op2, args2 = commands[i]
        new_op = None

        # Merge logic...
        if {op1, op2} <= {'rlineto', 'rrcurveto'}:
            if op1 == op2:
                new_op = op1
            else:
                if op2 == 'rrcurveto' and len(args2) == 6:
                    new_op = 'rlinecurve'
                elif len(args2) == 2:
                    new_op = 'rcurveline'

        elif (op1, op2) in {
                        ('rlineto', 'rlinecurve'),
                        ('rrcurveto', 'rcurveline')
                      }:
            new_op = op2

        elif {op1, op2} == {'vlineto', 'hlineto'}:
            new_op = op1

        elif 'curveto' == op1[2:] == op2[2:]:
            d0, d1 = op1[:2]
            d2, d3 = op2[:2]

            if d1 == 'r' or d2 == 'r' or d0 == d3 == 'r':
                continue

            d = _mergeCategories(d1, d2)
            if d is None:
                continue
            if d0 == 'r':
                d = _mergeCategories(d, d3)
                if d is None:
                    continue
                new_op = 'r'+d+'curveto'
            elif d3 == 'r':
                d0 = _mergeCategories(d0, _negateCategory(d))
                if d0 is None:
                    continue
                new_op = d0+'r'+'curveto'
            else:
                d0 = _mergeCategories(d0, d3)
                if d0 is None:
                    continue
                new_op = d0+d+'curveto'

        # Make sure the stack depth does not exceed (maxstack - 1), so
        # that subroutinizer can insert subroutine calls at any point.
        if new_op and len(args1) + len(args2) < maxstack:
            commands[i-1] = (new_op, args1+args2)
            del commands[i]

    # 6. Resolve any remaining made-up operators into real operators.
    for i in range(len(commands)):
        op, args = commands[i]

        if op in {'0moveto', '0lineto'}:
            commands[i] = 'h'+op[1:], args
            continue

        if (
            op[2:] == 'curveto' and
            op[:2] not in {'rr', 'hh', 'vv', 'vh', 'hv'}
           ):
            op0, op1 = op[:2]
            if (op0 == 'r') ^ (op1 == 'r'):
                assert len(args) % 2 == 1
            if op0 == '0':
                op0 = 'h'
            if op1 == '0':
                op1 = 'h'
            if op0 == 'r':
                op0 = op1
            if op1 == 'r':
                op1 = _negateCategory(op0)
            assert {op0, op1} <= {'h', 'v'}, (op0, op1)

            if len(args) % 2:
                if op0 != op1:  # vhcurveto / hvcurveto
                    if (op0 == 'h') ^ (len(args) % 8 == 1):
                        # Swap last two args order
                        args = args[:-2]+args[-1:]+args[-2:-1]
                else:  # hhcurveto / vvcurveto
                    if op0 == 'h':  # hhcurveto
                        # Swap first two args order
                        args = args[1:2]+args[:1]+args[2:]

            commands[i] = op0+op1+'curveto', args
            continue

    return commands


def commandsToProgram(commands, max_stack, var_model=None):
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
                i += 1
                stack_use += 1
            else:
                """ The arg is a tuple of blend values.
                These are each (master 0,master 1..master n)
                Look forward to see how many we can combine.
                """
                num_masters = len(arg)
                blendlist = [arg]
                i += 1
                stack_use += 1  # for the num_blends arg
                while (i < num_args) and (type(args[i]) is tuple):
                    blendlist.append(args[i])
                    i += 1
                    stack_use += num_masters
                    if stack_use + num_masters > max_stack:
                        break
                num_blends = len(blendlist)
                # append the 'num_blends' default font values
                for arg in blendlist:
                    program.append(arg[0])
                for arg in blendlist:
                    # for each coordinate tuple, append the region deltas
                    deltas = var_model.getDeltas(arg)
                    # First item in 'deltas' is the default master value;
                    # for CFF2 data, that has already been written.
                    program.extend(deltas[1:])
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
        self._p0 = (0, 0)

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

    def getCharString(
                    self, private=None, globalSubrs=None,
                    var_model=None, optimize=True
                ):
        self.reorder_blend_args()
        commands = self._commands
        if optimize:
            maxstack = 48 if not self._CFF2 else 513
            commands = specializeCommands(commands,
                                          generalizeFirst=False,
                                          maxstack=maxstack)
        program = commandsToProgram(commands, maxstack, var_model)
        charString = CFF2Subr(
            program=program, private=private, globalSubrs=globalSubrs)
        return charString

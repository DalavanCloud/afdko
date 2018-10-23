# Copyright 2017,2018 Adobe. All rights reserved.

from __future__ import print_function, division, absolute_import

__usage__ = """
buildcff2vf.py  1.15.0 Oct 5 2018
Build a variable font from a designspace file and the UFO master source fonts.

python buildcff2vf.py -h
python buildcff2vf.py -u
python buildcff2vf.py <path to designspace file> (<optional path to output
                                                               variable font>)
"""

__help__ = __usage__ + """
Options:
-p   Use 'post' table format 3.

The script makes a number of assumptions.
1) all the master source fonts are blend compatible in all their data.
2) The source OTF files are in the same directory as the master source
   fonts, and have the same file name but with an extension of '.otf'
   rather than '.ufo'.
3) The master source OTF fonts were built with the companion script
   'buildmasterotfs.py'. This does a first pass of compatibilization
   by using 'tx' with the '-no_opt' option to undo T2 charstring
   optimization applied by makeotf.

The variable font inherits all the OpenType Tables except CFF2 and GPOS
from the default master source font. The default font is flagged in the
designspace file by having the element "<info copy="1" />" in the <source>
element.

The width values and the GPOS positioning data are drawn from all the
master source fonts, so each must be built with with a full set of GPOS
features.

The companion script buildmasterotfs.py will build the master source OTFs
from the designspace file.

Any python interpreter may be used to run the script, as long as it has
installed the latest version of the fonttools module from
https://github.com/fonttools/fonttools
"""

import os
import sys

from fontTools import version as fontToolsVersion
from fontTools.varLib import build as varlib_build
from pkg_resources import parse_version


def otfFinder(s):
    return s.replace('.ufo', '.otf')


def run(args=None):
    if not args:
        args = sys.argv[1:]
    if '-u' in args:
        print(__usage__)
        return
    if '-h' in args:
        print(__help__)
        return

    post_format_3 = False
    if '-p' in args:
        post_format_3 = True
        args.remove('-p')

    if parse_version(fontToolsVersion) < parse_version("3.19"):
        print("Quitting. The Python fonttools module must be at least 3.19.0 "
              "in order for buildcff2vf to work.")
        return

    if len(args) == 2:
        designSpacePath, varFontPath = args
    elif len(args) == 1:
        designSpacePath = args[0]
        varFontPath = os.path.splitext(designSpacePath)[0] + '.otf'
    else:
        print(__usage__)
        return

    if os.path.exists(varFontPath):
        os.remove(varFontPath)
    varFont, varModel, masterPaths = varlib_build(
                                    designSpacePath, otfFinder)
    if post_format_3:
        varFont['post'].formatType = 3.0
    varFont.save(varFontPath)


if __name__ == '__main__':
    run()

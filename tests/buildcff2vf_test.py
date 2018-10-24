from __future__ import print_function, division, absolute_import

import os
from shutil import copytree
import tempfile

from runner import main as runner
from differ import main as differ
from test_utils import get_input_path, get_expected_path, generate_ttx_dump

TOOL = 'buildcff2vf'
CMD = ['-t', TOOL]


# -----
# Tests
# -----

def test_cjk_vf():
    input_dir = get_input_path('CJKVar')
    temp_dir = os.path.join(tempfile.mkdtemp(), 'CJKVar')
    copytree(input_dir, temp_dir)
    ds_path = os.path.join(input_dir, 'CJKVar.designspace')
    runner(CMD + ['-o', 'p', '_{}'.format(ds_path)])
    actual_path = os.path.join(temp_dir, 'CJKVar.otf')
    actual_ttx = generate_ttx_dump(actual_path,
                                   ['CFF2', 'HVAR', 'avar', 'fvar'])
    expected_ttx = get_expected_path('CJKVar.ttx')
    assert differ([expected_ttx, actual_ttx, '-s', '<ttFont sfntVersion'])


def test_feature_variation_vf():
    input_dir = get_input_path('GSUBVar')
    ds_path = os.path.join(input_dir,
                           'Roman', 'Masters',
                           'GSUBVar.designspace')
    temp_dir = tempfile.mkdtemp()
    actual_path = os.path.join(os.path.join(temp_dir, 'GSUBVar.otf'))
    runner(CMD + ['-o', 'p', '_{}'.format(ds_path), '_{}'.format(actual_path)])
    actual_ttx = generate_ttx_dump(
                            actual_path,
                            ['CFF2', 'HVAR', 'avar', 'fvar'])
    expected_ttx = get_expected_path('GSUBVar.ttx')
    assert differ([expected_ttx, actual_ttx, '-s', '<ttFont sfntVersion'])

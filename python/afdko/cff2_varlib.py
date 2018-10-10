import os
import fontTools
from fontTools.ttLib.ttFont import TTFont
from fontTools.varLib import (load_designspace, log)
from cff2_specializer import (addCFFVarStore,
                              addNamesToPost,
                              merge_PrivateDicts,
                              merge_charstrings,
                              convertCFFtoCFF2,)
from fontTools.varLib.models import VariationModel


def _add_CFF2(varFont, model, master_fonts):
    glyphOrder = varFont.getGlyphOrder()
    addNamesToPost(varFont, glyphOrder)
    convertCFFtoCFF2(varFont)
    # I sort the master font in the mode l order so as to
    # not have to index through model.mapping when building
    # a blend vector from the master font data.
    ordered_fonts_list = [master_fonts[idx] for idx in model.reverseMapping]
    model.mapping = model.reverseMapping = range(len(master_fonts))
    addCFFVarStore(varFont, model)  # Add VarStore to the CFF2 font.
    merge_region_fonts(varFont, model, ordered_fonts_list, glyphOrder)


def merge_region_fonts(varFont, model, ordered_fonts_list, glyphOrder):
    topDict = varFont['CFF2'].cff.topDictIndex[0]
    default_charstrings = topDict.CharStrings
    region_fonts = ordered_fonts_list[1:]
    region_top_dicts = [
            ttFont['CFF '].cff.topDictIndex[0] for ttFont in region_fonts
                ]
    num_masters = len(model.mapping)
    merge_PrivateDicts(topDict, region_top_dicts, num_masters, model)
    merge_charstrings(default_charstrings,
                      glyphOrder,
                      num_masters,
                      region_top_dicts, model)


def build(designspace_filename,
          master_finder=lambda s: s,
          exclude=[], optimize=True):
    """
    Build variation font from a designspace file.

    If master_finder is set, it should be a callable that takes master
    filename as found in designspace file and map it to master font
    binary as to be opened (eg. .ttf or .otf).
    """

    ds = load_designspace(designspace_filename)

    log.info("Building variable font")
    log.info("Loading master fonts")
    basedir = os.path.dirname(designspace_filename)
    master_ttfs = [master_finder(os.path.join(basedir, m.filename))
                   for m in ds.masters]
    master_fonts = [TTFont(ttf_path) for ttf_path in master_ttfs]
    # Reload base font as target font
    vf = TTFont(master_ttfs[ds.base_idx])

    # TODO append masters as named-instances as well;
    # needs .designspace change.
    fvar = fontTools.varLib._add_fvar(vf, ds.axes, ds.instances)
    if 'STAT' not in exclude:
        fontTools.varLib._add_stat(vf, ds.axes)
    if 'avar' not in exclude:
        fontTools.varLib._add_avar(vf, ds.axes)

    # Map from axis names to axis tags...
    normalized_master_locs = [
        {ds.axes[k].tag: v for k, v in loc.items()}
        for loc in ds.normalized_master_locs
        ]
    # From here on, we use fvar axes only
    axisTags = [axis.axisTag for axis in fvar.axes]

    # Assume single-model for now.
    model = VariationModel(normalized_master_locs, axisOrder=axisTags)
    assert 0 == model.mapping[ds.base_idx]

    log.info("Building variations tables")
    if 'MVAR' not in exclude:
        fontTools.varLib._add_MVAR(vf, model, master_fonts, axisTags)
    if 'HVAR' not in exclude:
        fontTools.varLib._add_HVAR(vf, model, master_fonts, axisTags)
    if 'GDEF' not in exclude or 'GPOS' not in exclude:
        fontTools.varLib._merge_OTL(vf, model, master_fonts, axisTags)
    if 'gvar' not in exclude and 'glyf' in vf:
        fontTools.varLib._add_gvar(vf, model, master_fonts, optimize=optimize)
    if 'cvar' not in exclude and 'glyf' in vf:
        fontTools.varLib._merge_TTHinting(vf, model, master_fonts)
    if 'GSUB' not in exclude and ds.rules:
        fontTools.varLib._add_GSUB_feature_variations(
                                    vf,
                                    ds.axes,
                                    ds.internal_axis_supports,
                                    ds.rules)
    if 'CFF2' not in exclude and 'CFF ' in vf:
        _add_CFF2(vf, model, master_fonts)

    for tag in exclude:
        if tag in vf:
            del vf[tag]

    return vf, model, master_ttfs

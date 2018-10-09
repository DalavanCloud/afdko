from fontTools.misc.py23 import BytesIO
from fontTools.cffLib import (TopDictIndex,
                              buildOrder,
                              topDictOperators,
                              topDictOperators2,
                              privateDictOperators,
                              privateDictOperators2,
                              FDArrayIndex,
                              FontDict,
                              VarStoreData,)
from fontTools.ttLib import newTable
from fontTools import varLib
from cff2mergePen import CFF2CharStringMergePen


def addCFFVarStore(varModel, varFont):
    supports = varModel.supports[1:]
    fvarTable = varFont['fvar']
    axisKeys = [axis.axisTag for axis in fvarTable.axes]
    varTupleList = varLib.builder.buildVarRegionList(supports, axisKeys)
    varTupleIndexes = list(range(len(supports)))
    varDeltasCFFV = varLib.builder.buildVarData(varTupleIndexes, None, False)
    varStoreCFFV = varLib.builder.buildVarStore(varTupleList, [varDeltasCFFV])

    topDict = varFont['CFF2'].cff.topDictIndex[0]
    topDict.VarStore = VarStoreData(otVarStore=varStoreCFFV)


def addNamesToPost(ttFont, fontGlyphList):
    postTable = ttFont['post']
    postTable.glyphOrder = ttFont.glyphOrder = fontGlyphList
    postTable.formatType = 2.0
    postTable.extraNames = []
    postTable.mapping = {}
    postTable.compile(ttFont)


def lib_convertCFFToCFF2(cff, otFont):
    # This assumes a decompiled CFF table.
    cff2GetGlyphOrder = cff.otFont.getGlyphOrder
    topDictData = TopDictIndex(None, cff2GetGlyphOrder, None)
    topDictData.items = cff.topDictIndex.items
    cff.topDictIndex = topDictData
    topDict = topDictData[0]
    if hasattr(topDict, 'Private'):
        privateDict = topDict.Private
    else:
        privateDict = None
    opOrder = buildOrder(topDictOperators2)
    topDict.order = opOrder
    topDict.cff2GetGlyphOrder = cff2GetGlyphOrder
    if not hasattr(topDict, "FDArray"):
        fdArray = topDict.FDArray = FDArrayIndex()
        fdArray.strings = None
        fdArray.GlobalSubrs = topDict.GlobalSubrs
        topDict.GlobalSubrs.fdArray = fdArray
        charStrings = topDict.CharStrings
        if charStrings.charStringsAreIndexed:
            charStrings.charStringsIndex.fdArray = fdArray
        else:
            charStrings.fdArray = fdArray
        fontDict = FontDict()
        fontDict.setCFF2(True)
        fdArray.append(fontDict)
        fontDict.Private = privateDict
        privateOpOrder = buildOrder(privateDictOperators2)
        for entry in privateDictOperators:
            key = entry[1]
            if key not in privateOpOrder:
                if key in privateDict.rawDict:
                    # print "Removing private dict", key
                    del privateDict.rawDict[key]
                if hasattr(privateDict, key):
                    delattr(privateDict, key)
                    # print "Removing privateDict attr", key
    else:
        # clean up the PrivateDicts in the fdArray
        fdArray = topDict.FDArray
        privateOpOrder = buildOrder(privateDictOperators2)
        for fontDict in fdArray:
            fontDict.setCFF2(True)
            for key in fontDict.rawDict.keys():
                if key not in fontDict.order:
                    del fontDict.rawDict[key]
                    if hasattr(fontDict, key):
                        delattr(fontDict, key)

            privateDict = fontDict.Private
            for entry in privateDictOperators:
                key = entry[1]
                if key not in privateOpOrder:
                    if key in privateDict.rawDict:
                        # print "Removing private dict", key
                        del privateDict.rawDict[key]
                    if hasattr(privateDict, key):
                        delattr(privateDict, key)
                        # print "Removing privateDict attr", key
    # Now delete up the decrecated topDict operators from CFF 1.0
    for entry in topDictOperators:
        key = entry[1]
        if key not in opOrder:
            if key in topDict.rawDict:
                del topDict.rawDict[key]
            if hasattr(topDict, key):
                delattr(topDict, key)

    # At this point, the Subrs and Charstrings are all still T2Charstring class
    # easiest to fix this by compiling, then decompiling again
    cff.major = 2
    file = BytesIO()
    cff.compile(file, otFont, isCFF2=True)
    file.seek(0)
    cff.decompile(file, otFont, isCFF2=True)


def pointsDiffer(pointList):
    p0 = max(pointList)
    p1 = min(pointList)
    result = True if p1 == p0 else False 


def convertCFFtoCFF2(varFont):
    # Convert base font to a single master CFF2 font.
    cffTable = varFont['CFF ']
    lib_convertCFFToCFF2(cffTable.cff, varFont)
    newCFF2 = newTable("CFF2")
    newCFF2.cff = cffTable.cff
    varFont['CFF2'] = newCFF2
    del varFont['CFF ']


def merge_PrivateDicts(topDict, region_top_dicts, num_masters, var_model):
    print(region_top_dicts)
    if hasattr(region_top_dicts[0], 'FDArray'):
        regionFDArrays =  [fdTopDict.FDArray for fdTopDict in region_top_dicts]
    else:
        regionFDArrays = [[fdTopDict] for fdTopDict in region_top_dicts]
    for fd_index, font_dict in enumerate(topDict.FDArray):
        private_dict = font_dict.Private
        pds = [private_dict] + [
            regionFDArray[fd_index].Private for regionFDArray in regionFDArrays
            ]
        for key, value in private_dict.rawDict.items():
            
            if isinstance(value, list):
                values = [pd.rawDict[key] for pd in pds]
                values = zip(*values)
                """
                Row 0 contains the first  value from each master.
                Convert each row from absolute values to relative
                values from the previous row.
                e.g for three masters,  a list of values was:
                master 0 OtherBlues = [-217,-205]
                master 1 OtherBlues = [-234,-222]
                master 1 OtherBlues = [-188,-176]
                The call to zip() converts this to:
                [(-217, -234, -188), (-205, -222, -176)]
                and is converted finally to:
                OtherBlues = [[-217, 17.0, 46.0], [-205, 0.0, 0.0]]
                """
                dataList = []
                prev_val_list = [0] * num_masters
                for val_list in values:
                    rel_list = [(val - prev_val_list[i]) for (
                            i, val) in enumerate(val_list)]
                    prev_val_list = val_list
                    deltas = var_model.getDeltas(rel_list)
                    # For PrivateDict BlueValues, the default font
                    # values are absolute, not relative to the prior value.
                    deltas[0] = val_list[0]
                    dataList.append(deltas)
            else:
                values = [pd.rawDict[key] for pd in pds]
                if pointsDiffer(values):
                    dataList = var_model.getDeltas(values)
                else:
                    dataList = values[0]
            private_dict.rawDict[key] = dataList
            print(key, dataList)


def merge_charstrings(default_charstrings,
                      glyphOrder,
                      num_masters,
                      region_top_dicts):
    for gname in glyphOrder:
        default_charstring = default_charstrings[gname]
        var_pen = CFF2CharStringMergePen([], num_masters, master_idx=0)
        default_charstring.draw(var_pen)
        region_idx = 0
        for region_td in region_top_dicts:
            region_idx += 1
            region_charstrings = region_td.CharStrings
            region_charstring = region_charstrings[gname]
            var_pen.restart(region_idx)
            region_charstring.draw(var_pen)
        new_charstring = var_pen.getCharString(
            private=default_charstring.private,
            globalSubrs=default_charstring.globalSubrs,
            optimize=True)
        default_charstrings[gname] = new_charstring

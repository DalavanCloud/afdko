#!/usr/bin/env sh

rom=Roman/Masters
ro_name=SourceCodeVariable-Roman
# build variable OTFs
buildmasterotfs $rom/$ro_name.designspace
buildcff2vf $rom/$ro_name.designspace
# delete build artifacts

echo "Done"

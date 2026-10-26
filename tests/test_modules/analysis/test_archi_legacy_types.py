"""Reading an Archi file written in ArchiMate 2 names: the types are read as ArchiMate 3 names them, so a reference
model in the older notation is scored like any other (Infrastructure* became Technology*, UsedBy became Serving, and
the British spellings Realisation and Specialisation became Realization and Specialization)."""

from __future__ import annotations

from deriva.modules.analysis.semantic_matching import parse_archi_xml

ARCHIMATE_2 = """<?xml version="1.0" encoding="UTF-8"?>
<archimate:model xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:archimate="http://www.archimatetool.com/archimate" name="shop" id="m">
  <folder name="Technology" id="f1" type="technology">
    <element xsi:type="archimate:InfrastructureService" id="ts" name="Database Service"/>
    <element xsi:type="archimate:InfrastructureInterface" id="ti" name="SQL"/>
    <element xsi:type="archimate:InfrastructureFunction" id="tf" name="Storing"/>
    <element xsi:type="archimate:Network" id="nw" name="LAN"/>
    <element xsi:type="archimate:CommunicationPath" id="cp" name="Link"/>
    <element xsi:type="archimate:Node" id="nd" name="Server"/>
  </folder>
  <folder name="Application" id="f2" type="application">
    <element xsi:type="archimate:ApplicationComponent" id="ac" name="Shop"/>
  </folder>
  <folder name="Relations" id="f3" type="relations">
    <element xsi:type="archimate:UsedByRelationship" id="r1" source="ts" target="ac"/>
    <element xsi:type="archimate:RealisationRelationship" id="r2" source="nd" target="ts"/>
    <element xsi:type="archimate:SpecialisationRelationship" id="r3" source="nd" target="nd"/>
    <element xsi:type="archimate:CompositionRelationship" id="r4" source="nd" target="tf"/>
  </folder>
</archimate:model>
"""


def test_archimate_2_names_are_read_as_archimate_3_types(tmp_path):
    path = tmp_path / "shop.archimate"
    path.write_text(ARCHIMATE_2, encoding="utf-8")

    elements, relationships = parse_archi_xml(path)

    types = {e.identifier: e.element_type for e in elements}
    assert (types["ts"], types["ti"], types["tf"]) == ("TechnologyService", "TechnologyInterface", "TechnologyFunction")
    assert (types["nw"], types["cp"], types["nd"], types["ac"]) == ("CommunicationNetwork", "Path", "Node", "ApplicationComponent")
    assert {r.identifier: r.relationship_type for r in relationships} == {"r1": "Serving", "r2": "Realization", "r3": "Specialization", "r4": "Composition"}

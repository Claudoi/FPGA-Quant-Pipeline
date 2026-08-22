"""Loader for the CME MDP 3.0 SBE XML schema — single source of layout.

Derives from `templates_FixBinary_v12.xml`: types, composites, enums, sets,
message header, messages with their fields (offset/sinceVersion) and groups
(blockLength/dimensionType). Encoding uses ONLY the non-constant components
of a composite (SBE rule: presence="constant" is not emitted).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

NS = "{http://www.fixprotocol.org/ns/simple/1.0}"

PRIMITIVE_SIZES = {
    "int8": 1, "uint8": 1, "char": 1,
    "int16": 2, "uint16": 2,
    "int32": 4, "uint32": 4,
    "int64": 8, "uint64": 8,
}

# CME type names use capitals (uInt8, Int32, CHAR...).
TYPE_ALIASES = {
    "uInt8": "uint8", "uInt16": "uint16", "uInt32": "uint32", "uInt64": "uint64",
    "Int8": "int8", "Int16": "int16", "Int32": "int32", "Int64": "int64",
    "CHAR": "char", "char": "char",
    "Int8NULL": "int8", "uInt8NULL": "uint8",
    "Int16NULL": "int16", "uInt16NULL": "uint16",
    "Int32NULL": "int32", "uInt32NULL": "uint32",
    "Int64NULL": "int64", "uInt64NULL": "uint64",
}


def canonical_type(name: str) -> str:
    return TYPE_ALIASES.get(name, name)


@dataclass
class TypeDef:
    name: str
    primitive: str
    length: int | None = None
    presence: str = "required"
    null_value: int | None = None
    constant: int | None = None
    since_version: int = 0

    @property
    def size(self) -> int:
        if self.length is not None:
            return self.length
        return PRIMITIVE_SIZES[self.primitive]


@dataclass
class Component:
    name: str
    type: TypeDef


@dataclass
class EnumDef:
    name: str
    encoding: str
    values: dict[str, int]


@dataclass
class SetDef:
    name: str
    encoding: str
    choices: dict[str, int]


@dataclass
class FieldDef:
    name: str
    id: int
    type: str  # type/composite/enum/set name
    offset: int
    since_version: int = 0


@dataclass
class GroupDef:
    name: str
    id: int
    block_length: int
    dimension_type: str  # groupSize | groupSize8Byte | ...
    fields: list[FieldDef] = field(default_factory=list)
    since_version: int = 0


@dataclass
class MessageDef:
    name: str
    id: int
    block_length: int
    semantic_type: str
    fields: list[FieldDef] = field(default_factory=list)
    groups: list[GroupDef] = field(default_factory=list)


@dataclass
class Schema:
    version: int
    byte_order: str
    header_fields: list[FieldDef]
    header_size: int
    messages: dict[int, MessageDef]
    by_name: dict[str, MessageDef]
    types: dict[str, TypeDef]
    composites: dict[str, list[Component]]
    enums: dict[str, EnumDef]
    sets: dict[str, SetDef]

    def type_size(self, name: str) -> int:
        """Encoded size of a type: constant components are not emitted."""
        if name in self.composites:
            return sum(c.type.size for c in self.composites[name]
                       if c.type.presence != "constant")
        if name in self.enums:
            return PRIMITIVE_SIZES[self.enums[name].encoding]
        if name in self.sets:
            return PRIMITIVE_SIZES[self.sets[name].encoding]
        return self.types[name].size

    def field_size(self, field: FieldDef) -> int:
        return self.type_size(field.type)

    def group_dim_size(self, group: GroupDef) -> int:
        if group.dimension_type == "groupSize8Byte":
            return 8
        if group.dimension_type in ("groupSize", "groupSizeEncoding"):
            return 3
        raise ValueError(f"unknown dimensionType: {group.dimension_type}")


def _tag(elem) -> str:
    return elem.tag.split("}")[-1]


def _text_int(elem) -> int | str:
    try:
        return int(elem.text.strip())
    except ValueError:
        return elem.text.strip()


def _attr(elem, name: str, default=None):
    v = elem.attrib.get(name, default)
    if v is None:
        return None
    if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
        return int(v)
    return v


def load_schema(path: str | Path) -> Schema:
    root = ET.parse(path).getroot()
    schema_ver = int(root.attrib["version"])
    byte_order = root.attrib.get("byteOrder", "littleEndian")

    types: dict[str, TypeDef] = {}
    composites: dict[str, list[Component]] = {}
    enums: dict[str, EnumDef] = {}
    sets: dict[str, SetDef] = {}

    for child in root:
        if _tag(child) != "types":
            continue
        for t in child:
            tt = _tag(t)
            n = t.attrib["name"]
            if tt == "type":
                presence = t.attrib.get("presence", "required")
                length = _attr(t, "length")
                types[n] = TypeDef(
                    name=n,
                    primitive=canonical_type(t.attrib["primitiveType"]),
                    length=length,
                    presence=presence,
                    null_value=_attr(t, "nullValue"),
                    constant=_text_int(t) if t.text is not None and presence == "constant" else None,
                    since_version=_attr(t, "sinceVersion") or 0,
                )
            elif tt == "composite":
                comps = []
                for c in t:
                    ct = canonical_type(c.attrib["primitiveType"])
                    cpresence = c.attrib.get("presence", "required")
                    cnull = _attr(c, "nullValue")
                    cconst = _text_int(c) if c.text is not None and cpresence == "constant" else None
                    comps.append(Component(
                        name=c.attrib["name"],
                        type=TypeDef(
                            name=c.attrib["name"],
                            primitive=ct,
                            length=_attr(c, "length"),
                            presence=cpresence,
                            null_value=cnull,
                            constant=cconst,
                            since_version=_attr(c, "sinceVersion") or 0,
                        ),
                    ))
                composites[n] = comps
            elif tt == "enum":
                enums[n] = EnumDef(
                    name=n,
                    encoding=canonical_type(t.attrib["encodingType"]),
                    values={v.attrib["name"]: _text_int(v) for v in t if _tag(v) == "validValue"},
                )
            elif tt == "set":
                sets[n] = SetDef(
                    name=n,
                    encoding=canonical_type(t.attrib["encodingType"]),
                    choices={c.attrib["name"]: _text_int(c) for c in t if _tag(c) == "choice"},
                )

    header_fields: list[FieldDef] = []
    header_size = 0
    messages: dict[int, MessageDef] = {}
    by_name: dict[str, MessageDef] = {}

    # The message header = the messageHeader composite of the schema (8 B:
    # blockLength u16, templateId u16, schemaId u16, version u16).
    for comp in composites.get("messageHeader", []):
        header_fields.append(FieldDef(
            name=comp.name,
            id=0,
            type=comp.type.primitive,
            offset=header_size,
        ))
        header_size += comp.type.size

    for child in root:
        tag = _tag(child)
        if tag == "message":
            msg = MessageDef(
                name=child.attrib["name"],
                id=int(child.attrib["id"]),
                block_length=int(child.attrib["blockLength"]),
                semantic_type=child.attrib.get("semanticType", ""),
            )
            for f in child:
                ft = _tag(f)
                if ft == "field":
                    msg.fields.append(FieldDef(
                        name=f.attrib["name"],
                        id=int(f.attrib["id"]),
                        type=f.attrib["type"],
                        offset=int(f.attrib.get("offset", 0)),
                        since_version=_attr(f, "sinceVersion") or 0,
                    ))
                elif ft == "group":
                    grp = GroupDef(
                        name=f.attrib["name"],
                        id=int(f.attrib["id"]),
                        block_length=int(f.attrib["blockLength"]),
                        dimension_type=f.attrib.get("dimensionType", "groupSize"),
                        since_version=_attr(f, "sinceVersion") or 0,
                    )
                    for gf in f:
                        if _tag(gf) == "field":
                            grp.fields.append(FieldDef(
                                name=gf.attrib["name"],
                                id=int(gf.attrib["id"]),
                                type=gf.attrib["type"],
                                offset=int(gf.attrib.get("offset", 0)),
                                since_version=_attr(gf, "sinceVersion") or 0,
                            ))
                    msg.groups.append(grp)
            messages[msg.id] = msg
            by_name[msg.name] = msg

    return Schema(
        version=schema_ver,
        byte_order=byte_order,
        header_fields=header_fields,
        header_size=header_size,
        messages=messages,
        by_name=by_name,
        types=types,
        composites=composites,
        enums=enums,
        sets=sets,
    )


# Campaign book subset: 46/47 (incremental) and 52/53 (snapshot).
SUBSET_TEMPLATES = (46, 47, 52, 53)
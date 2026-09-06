"""Custom fonts for the built-in DOCX export.

A chosen font has to reach two very different readers: Word on whatever
machine the document is finally opened on, and the docx renderer that draws
the preview in the export dialog. Naming the font is not enough for either -
Word falls back when the family is not installed, and the browser has never
heard of it at all. So the export writes the font *into* the document, the way
Word does when "Schriftarten in der Datei einbetten" is ticked: the theme's
Latin typefaces are swapped, an obfuscated copy of the file is added as a
part, and the font table points at it.

Only the built-in layout uses this. A Word template brings its own fonts, and
overriding them would defeat the point of having a template.
"""
from __future__ import annotations

import io
import re
import uuid
import zipfile

# Word reads .odttf - an ordinary TrueType/OpenType file with its first 32
# bytes scrambled. Web font containers cannot be embedded; Word ignores them.
FONT_EXTENSIONS = {".ttf", ".otf"}

CONTENT_TYPES_PART = "[Content_Types].xml"
FONT_PART = "word/fonts/font1.odttf"
FONT_TABLE_PART = "word/fontTable.xml"
FONT_TABLE_RELS = "word/_rels/fontTable.xml.rels"
SETTINGS_PART = "word/settings.xml"
THEME_PART = re.compile(r"word/theme/theme\d*\.xml")

FONT_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
)
ODTTF_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# --- reading the font file --------------------------------------------------
# sfnt wrappers we can hand to Word: TrueType outlines, OpenType/CFF outlines,
# and the two legacy Apple variants. Not .ttc, .woff or .woff2.
_SFNT_TAGS = {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"}

# Name 16 is the typographic family ("Source Serif 4"); name 1 is the family as
# older software groups it, which splits weights into families of their own
# ("Source Serif 4 SemiBold"). Prefer 16 when the font carries one.
_FAMILY_NAME_IDS = (16, 1)


def _sfnt_table(data: bytes, tag: bytes) -> bytes | None:
    """One table out of an sfnt font file, or None if it is not in there."""
    if len(data) < 12 or data[:4] not in _SFNT_TAGS:
        return None
    count = int.from_bytes(data[4:6], "big")
    for index in range(count):
        record = data[12 + index * 16 : 28 + index * 16]
        if len(record) < 16:
            return None
        if record[:4] != tag:
            continue
        start = int.from_bytes(record[8:12], "big")
        length = int.from_bytes(record[12:16], "big")
        return data[start : start + length]
    return None


def _decode_name(platform: int, raw: bytes) -> str:
    # Windows and Unicode records are UTF-16BE; the Macintosh ones are not.
    encoding = "mac_roman" if platform == 1 else "utf-16-be"
    try:
        return raw.decode(encoding).replace("\x00", "").strip()
    except (UnicodeDecodeError, LookupError):
        return ""


def family_name(data: bytes) -> str | None:
    """The family name Word will look for, read out of the font's name table."""
    table = _sfnt_table(data, b"name")
    if table is None or len(table) < 6:
        return None
    count = int.from_bytes(table[2:4], "big")
    storage = int.from_bytes(table[4:6], "big")
    best: tuple[tuple[int, int], str] | None = None
    for index in range(count):
        record = table[6 + index * 12 : 18 + index * 12]
        if len(record) < 12:
            break
        name_id = int.from_bytes(record[6:8], "big")
        if name_id not in _FAMILY_NAME_IDS:
            continue
        platform = int.from_bytes(record[0:2], "big")
        length = int.from_bytes(record[8:10], "big")
        offset = storage + int.from_bytes(record[10:12], "big")
        text = _decode_name(platform, table[offset : offset + length])
        if not text:
            continue
        # Prefer the typographic family, and within it the Windows record -
        # that is the string Word matches an installed font against.
        rank = (_FAMILY_NAME_IDS.index(name_id), 0 if platform == 3 else 1)
        if best is None or rank < best[0]:
            best = (rank, text)
    return best[1] if best else None


# --- writing the font into a document ---------------------------------------
def _obfuscate(font: bytes, font_key: str) -> bytes:
    """Word's font obfuscation: 32 bytes XORed with the key GUID, reversed."""
    key = bytes.fromhex(font_key.strip("{}").replace("-", ""))[::-1]
    data = bytearray(font)
    for index in range(min(32, len(data))):
        data[index] ^= key[index % 16]
    return bytes(data)


def _escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _theme_with_font(xml: str, family: str) -> str:
    """Point the theme's major and minor Latin typefaces at the chosen font.

    Everything in the built-in layout - body text, headings, the title - asks
    the theme for its font rather than naming one, so this single swap covers
    the whole document.
    """
    typeface = _escape(family)

    def swap(block: "re.Match[str]") -> str:
        return re.sub(
            r'(<a:latin\b[^>]*?\btypeface=")[^"]*(")',
            lambda latin: f"{latin.group(1)}{typeface}{latin.group(2)}",
            block.group(0),
            count=1,
        )

    return re.sub(r"<a:(major|minor)Font>.*?</a:\1Font>", swap, xml, flags=re.S)


def _font_table_with_embed(xml: str, family: str, rel_id: str, font_key: str) -> str:
    name = _escape(family)
    # An entry for this family may already be there, describing the installed
    # font. Ours replaces it, rather than leaving Word with the family twice.
    xml = re.sub(
        rf'<w:font\b[^>]*w:name="{re.escape(name)}"(?:\s*/>|>.*?</w:font>)',
        "", xml, flags=re.S,
    )
    entry = (
        f'<w:font w:name="{name}">'
        f'<w:embedRegular r:id="{rel_id}" w:fontKey="{font_key}" w:subsetted="false"/>'
        f"</w:font>"
    )
    return xml.replace("</w:fonts>", f"{entry}</w:fonts>", 1)


def _free_rel_id(rels: str | None) -> str:
    used = set(re.findall(r'Id="([^"]+)"', rels or ""))
    number = 1
    while f"rId{number}" in used:
        number += 1
    return f"rId{number}"


def _rels_with_font(rels: str | None, rel_id: str) -> str:
    entry = (
        f'<Relationship Id="{rel_id}" Type="{FONT_REL_TYPE}" Target="fonts/font1.odttf"/>'
    )
    if rels is None:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{RELS_NS}">{entry}</Relationships>'
        )
    return rels.replace("</Relationships>", f"{entry}</Relationships>", 1)


def _content_types_with_odttf(xml: str) -> str:
    if 'Extension="odttf"' in xml:
        return xml
    default = f'<Default Extension="odttf" ContentType="{ODTTF_CONTENT_TYPE}"/>'
    return re.sub(r"(<Types\b[^>]*>)", lambda types: types.group(1) + default, xml, count=1)


# The settings part is a fixed sequence, so the two flags cannot simply be
# appended: they go after the last element allowed to precede them.
_BEFORE_EMBED_FLAGS = (
    "writeProtection", "view", "zoom", "removePersonalInformation",
    "removeDateAndTime", "doNotDisplayPageBoundaries", "displayBackgroundShape",
    "printPostScriptOverText", "printFractionalCharacterWidth", "printFormsData",
)


def _settings_with_embedding(xml: bytes) -> bytes:
    """Tell Word the document carries its fonts, and carries them whole."""
    from lxml import etree

    root = etree.fromstring(xml)
    present = set()
    index = 0
    for position, child in enumerate(root):
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child).localname
        present.add(local)
        if local in _BEFORE_EMBED_FLAGS:
            index = position + 1
    # Both go in at the same spot, second one first, so that they end up in
    # the order the schema wants.
    if "saveSubsetFonts" not in present:
        root.insert(index, root.makeelement(f"{W_NS}saveSubsetFonts",
                                            {f"{W_NS}val": "false"}))
    if "embedTrueTypeFonts" not in present:
        root.insert(index, root.makeelement(f"{W_NS}embedTrueTypeFonts", {}))
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def apply_font(payload: bytes, family: str, font: bytes) -> bytes:
    """A copy of the .docx that asks for `family` and carries the font file."""
    source = zipfile.ZipFile(io.BytesIO(payload))
    names = set(source.namelist())
    # Without a font table there is nothing to hang the embedded file off; the
    # theme swap alone still names the font for a machine that has it.
    embed = FONT_TABLE_PART in names
    font_key = "{" + str(uuid.uuid4()).upper() + "}"
    existing_rels = (
        source.read(FONT_TABLE_RELS).decode("utf-8") if FONT_TABLE_RELS in names else None
    )
    rel_id = _free_rel_id(existing_rels)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            name = item.filename
            if THEME_PART.fullmatch(name):
                data = _theme_with_font(data.decode("utf-8"), family).encode("utf-8")
            elif embed and name == FONT_TABLE_PART:
                data = _font_table_with_embed(
                    data.decode("utf-8"), family, rel_id, font_key
                ).encode("utf-8")
            elif embed and name == FONT_TABLE_RELS:
                data = _rels_with_font(data.decode("utf-8"), rel_id).encode("utf-8")
            elif embed and name == CONTENT_TYPES_PART:
                data = _content_types_with_odttf(data.decode("utf-8")).encode("utf-8")
            elif embed and name == SETTINGS_PART:
                data = _settings_with_embedding(data)
            target.writestr(item, data)
        if embed:
            if existing_rels is None:
                target.writestr(FONT_TABLE_RELS, _rels_with_font(None, rel_id))
            target.writestr(FONT_PART, _obfuscate(font, font_key))
    return buffer.getvalue()

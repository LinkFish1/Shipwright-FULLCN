#!/usr/bin/env python3
"""Check if all Chinese characters in the reviewed translations exist in the charmap.

Parses charmap_chn.txt (Python dict format) and charmap_chn_extra.txt (simple format),
then checks each character in the translations from fill_translations.py.
Reports missing characters that need to be added to the font.
"""

import re
import os
import sys

# Also try to read the user-reviewed Excel if openpyxl is available
try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def parse_charmap_main(path):
    """Parse charmap_chn.txt — Python dict format: 'char': 0xCode"""
    chars = set()
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    # Match single characters: 'X': 0xHHHH
    for m in re.finditer(r"'(.)'(?:\s*:\s*)0x([0-9A-Fa-f]+)", content):
        chars.add(m.group(1))
    # Match special sequences like '[A]': 0xHHHH (skip these for char coverage)
    # Match \n
    chars.add('\n')
    return chars


def parse_charmap_extra(path):
    """Parse charmap_chn_extra.txt — format: '字': 0xAAAA"""
    chars = set()
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            m = re.match(r"'(.)':\s*0x([0-9A-Fa-f]+)", line)
            if m:
                chars.add(m.group(1))
    return chars


def get_max_code(path):
    """Get the highest code in charmap_chn_extra.txt for assigning new codes."""
    max_code = 0
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r"'.':\s*0x([0-9A-Fa-f]+)", line.strip())
            if m:
                code = int(m.group(1), 16)
                if code > max_code:
                    max_code = code
    return max_code


def extract_chars_from_translations(translations_dict):
    """Extract all unique non-ASCII characters from translations."""
    chars = set()
    control_tags = {'[BOX]', '[玩家名]', '[选择]', '[A]', '[B]', '[C]', '[L]', '[R]', '[Z]',
                    '[C-Up]', '[C-Down]', '[C-Left]', '[C-Right]', '[Control-Pad]'}

    for text_id, text in translations_dict.items():
        # Remove control tags
        clean = text
        for tag in control_tags:
            clean = clean.replace(tag, '')
        # Remove \n (it's a control code, not a character)
        clean = clean.replace('\n', '')

        for ch in clean:
            if ord(ch) > 0x7E:  # Non-ASCII
                chars.add(ch)
    return chars


def load_translations_from_py(py_path):
    """Load translations dict from fill_translations.py by exec."""
    with open(py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    # Extract the TRANSLATIONS dict
    # Find the start
    start = content.find('TRANSLATIONS = {')
    if start < 0:
        print("ERROR: Could not find TRANSLATIONS dict")
        sys.exit(1)
    # Use a simpler approach: just exec the relevant part
    local_ns = {}
    exec(content, {}, local_ns)
    return local_ns.get('TRANSLATIONS', {})


def load_translations_from_xlsx(xlsx_path):
    """Load translations from column D of the review Excel."""
    if not HAS_OPENPYXL:
        return None
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    translations = {}
    for row in ws.iter_rows(min_row=2, values_only=False):
        text_id = row[0].value  # Column A: TextId
        translation = row[3].value  # Column D: AI翻译
        if text_id and translation:
            translations[str(text_id)] = str(translation)
    return translations


def main():
    base = os.path.dirname(os.path.abspath(__file__))

    charmap_main_path = os.path.join(base, 'charmap_chn.txt')
    charmap_extra_path = os.path.join(base, 'charmap_chn_extra.txt')
    fill_py_path = os.path.join(base, 'fill_translations.py')
    xlsx_path = os.path.join(base, 'truncated_messages_review.xlsx')

    # Parse charmaps
    main_chars = parse_charmap_main(charmap_main_path)
    extra_chars = parse_charmap_extra(charmap_extra_path)
    all_chars = main_chars | extra_chars

    print(f"Charmap main: {len(main_chars)} chars")
    print(f"Charmap extra: {len(extra_chars)} chars")
    print(f"Total known chars: {len(all_chars)}")

    # Try to load from reviewed Excel first, fall back to fill_translations.py
    translations = None
    source = None
    if os.path.exists(xlsx_path):
        translations = load_translations_from_xlsx(xlsx_path)
        if translations:
            source = "Excel (user-reviewed)"

    if not translations:
        translations = load_translations_from_py(fill_py_path)
        source = "fill_translations.py"

    print(f"\nTranslation source: {source}")
    print(f"Messages with translations: {len(translations)}")

    # Extract unique non-ASCII chars
    used_chars = extract_chars_from_translations(translations)
    print(f"Unique non-ASCII chars in translations: {len(used_chars)}")

    # Find missing
    missing = sorted(used_chars - all_chars, key=ord)

    if not missing:
        print("\n✅ All characters are covered by the existing charmap!")
    else:
        max_code = get_max_code(charmap_extra_path)
        print(f"\n⚠️  MISSING {len(missing)} characters (not in any charmap):")
        print(f"Current max code in extra: 0x{max_code:04X}")
        print(f"\nCharacters to add to charmap_chn_extra.txt:")
        next_code = max_code + 1
        for ch in missing:
            print(f"  '{ch}': 0x{next_code:04X}   (U+{ord(ch):04X} {ch})")
            next_code += 1

        print(f"\nAppend lines for charmap_chn_extra.txt:")
        next_code = max_code + 1
        for ch in missing:
            print(f"'{ch}': 0x{next_code:04X}")
            next_code += 1

    # Also list chars that ARE in charmap for verification
    found_in_main = used_chars & main_chars
    found_in_extra = used_chars & extra_chars
    print(f"\nChars found in main charmap: {len(found_in_main)}")
    print(f"Chars found in extra charmap: {len(found_in_extra)}")

    # Show ASCII chars used (should all be fine)
    ascii_chars = set()
    for text_id, text in translations.items():
        for tag in ['[BOX]', '[玩家名]', '[选择]', '[A]', '[B]', '[C]', '[L]', '[R]', '[Z]',
                    '[C-Up]', '[C-Down]', '[C-Left]', '[C-Right]', '[Control-Pad]']:
            text = text.replace(tag, '')
        for ch in text:
            if 0x20 <= ord(ch) <= 0x7E:
                ascii_chars.add(ch)
    print(f"ASCII chars used: {len(ascii_chars)} (all in range 0x20-0x7E, OK)")


if __name__ == '__main__':
    main()

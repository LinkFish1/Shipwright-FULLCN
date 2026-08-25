#!/usr/bin/env python3
"""Apply reviewed translations from Excel to z_message_CHI.cpp.

Reads the user-reviewed Excel file (truncated_messages_review.xlsx),
encodes translations into iQue byte format using the charmap,
and updates z_message_CHI.cpp with new byte arrays and table sizes.

Control code mapping in translation text:
  \n       → 0x01 (NEWLINE)
  [BOX]    → 0x04 (BOX_BREAK)
  [玩家名]  → 0x0F (PLAYER_NAME)
  [选择]    → 0x09 0x01 0x01 0x1B 0x05 0x42 ... (TWO_CHOICE with buy/don't buy)

The script preserves the original message's header bytes (before first printable content)
and only replaces the text body.
"""

import os
import re
import sys

try:
    import openpyxl
except ImportError:
    print("Error: openpyxl required. pip install openpyxl")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
CPP_PATH = os.path.join(REPO_ROOT, 'soh', 'soh', 'z_message_CHI.cpp')
XLSX_PATH = os.path.join(SCRIPT_DIR, 'truncated_messages_review.xlsx')
CHARMAP_MAIN = os.path.join(SCRIPT_DIR, 'charmap_chn.txt')
CHARMAP_EXTRA = os.path.join(SCRIPT_DIR, 'charmap_chn_extra.txt')


def load_charmap():
    """Load both charmap files into a unified char→code dict."""
    charmap = {}

    # Main charmap (Python dict format)
    with open(CHARMAP_MAIN, 'r', encoding='utf-8') as f:
        content = f.read()
    # Single chars
    for m in re.finditer(r"'(.)'(?:\s*:\s*)0x([0-9A-Fa-f]+)", content):
        charmap[m.group(1)] = int(m.group(2), 16)
    # Multi-char sequences like [A], [C-Up], etc.
    for m in re.finditer(r"'(\[[\w-]+\])'(?:\s*:\s*)0x([0-9A-Fa-f]+)", content):
        charmap[m.group(1)] = int(m.group(2), 16)

    # Extra charmap
    with open(CHARMAP_EXTRA, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            m = re.match(r"'(.)':\s*0x([0-9A-Fa-f]+)", line)
            if m:
                charmap[m.group(1)] = int(m.group(2), 16)

    return charmap


def encode_text(text, charmap):
    """Encode a translation string to iQue byte array.

    Handles:
    - \\n → 0x01 (NEWLINE)
    - [BOX] → 0x04 (BOX_BREAK)
    - [玩家名] → 0x0F (PLAYER_NAME)
    - [选择] is handled specially by the caller (appends TWO_CHOICE sequence)
    - ASCII 0x20-0x7E → single byte
    - CJK/special chars → 2-byte code from charmap
    """
    result = bytearray()
    i = 0

    while i < len(text):
        ch = text[i]

        # Newline
        if ch == '\n':
            result.append(0x01)
            i += 1
            continue

        # Control tags
        if ch == '[':
            # Find closing bracket
            end = text.find(']', i)
            if end >= 0:
                tag = text[i:end + 1]
                if tag == '[BOX]':
                    result.append(0x04)
                    i = end + 1
                    continue
                elif tag == '[玩家名]':
                    result.append(0x0F)
                    i = end + 1
                    continue
                elif tag == '[选择]':
                    # Caller handles this — just skip
                    i = end + 1
                    continue
                elif tag in charmap:
                    code = charmap[tag]
                    result.append((code >> 8) & 0xFF)
                    result.append(code & 0xFF)
                    i = end + 1
                    continue

        # ASCII printable
        if 0x20 <= ord(ch) <= 0x7E:
            result.append(ord(ch))
            i += 1
            continue

        # CJK / special char from charmap
        if ch in charmap:
            code = charmap[ch]
            if code >= 0x100:
                result.append((code >> 8) & 0xFF)
                result.append(code & 0xFF)
            else:
                result.append(code)
            i += 1
            continue

        print(f"  WARNING: Unknown char '{ch}' (U+{ord(ch):04X}) — skipping")
        i += 1

    return result


def get_original_header(cpp_content, text_id_str):
    """Extract the header bytes (before first printable content) from original message."""
    hex_id = text_id_str.upper()
    if hex_id.startswith('0X'):
        hex_id = hex_id[2:]

    pattern = re.compile(
        r'static\s+const\s+u8\s+sCHIMsgData_0x' + hex_id +
        r'\[\]\s*=\s*\{([^}]+)\};'
    )
    m = pattern.search(cpp_content)
    if not m:
        return None, None

    hex_bytes = m.group(1)
    byte_values = []
    for token in hex_bytes.split(','):
        token = token.strip()
        if token and token.startswith('0x'):
            byte_values.append(int(token, 16))

    # Extract header: bytes before first printable content
    # Header typically starts with type byte (0x00-0x1F range control codes)
    # until we hit printable text (>= 0x20 for ASCII, >= 0xA0 for CJK)
    header = bytearray()
    idx = 0
    while idx < len(byte_values):
        b = byte_values[idx]
        if b >= 0x20:  # Start of printable content
            break
        if b in {0x05, 0x06, 0x07, 0x0C, 0x0E, 0x11, 0x12, 0x13, 0x14, 0x15, 0x1E}:
            # Control code with extra bytes — include them in header
            extra = {0x05: 1, 0x06: 1, 0x07: 2, 0x0C: 1, 0x0E: 1,
                     0x11: 2, 0x12: 2, 0x13: 1, 0x14: 1, 0x15: 3, 0x1E: 1}
            header.append(b)
            for j in range(extra[b]):
                idx += 1
                if idx < len(byte_values):
                    header.append(byte_values[idx])
            idx += 1
            continue
        header.append(b)
        idx += 1

    return bytes(header), bytes(byte_values)


def get_msg_type(cpp_content, text_id_str):
    """Get the message type from the table entry."""
    hex_id = text_id_str.upper()
    if hex_id.startswith('0X'):
        hex_id = hex_id[2:]

    pattern = re.compile(
        r'\{\s*0x' + hex_id + r',\s*0x([0-9A-Fa-f]+),'
    )
    m = pattern.search(cpp_content)
    if m:
        return int(m.group(1), 16)
    return 0x23  # default


# Standard TWO_CHOICE endings
TWO_CHOICE_BUY = bytes([0x09, 0x01, 0x01, 0x1B, 0x05, 0x42,
                         0xA0, 0xF0,  # 买
                         0x01,         # NL
                         0xA0, 0xB0,   # 不
                         0xA0, 0xF0,   # 买
                         0x05, 0x40, 0x02])  # COLOR_DEFAULT + END

TWO_CHOICE_BORROW = bytes([0x09, 0x01, 0x01, 0x1B, 0x05, 0x42,
                            0xA1, 0x63,  # 借
                            0x01,         # NL
                            0xA0, 0xB0,   # 不
                            0xA1, 0x63,   # 借
                            0x05, 0x40, 0x02])

# Mask shop buy prompts use borrow
MASK_MESSAGES = {0x70B9, 0x70BA, 0x70BB, 0x70BC, 0x70BD, 0x70BE, 0x70BF, 0x70C0, 0x70C1}

# Shop item descriptions need PERSISTENT (0x09 + 0x0A) before END
# Without PERSISTENT, the shop actor freezes when cursor hovers over the item
SHOP_DESCRIPTION_IDS = {
    # Regular shops (z_en_girla.c ShopItemEntry.itemDescTextId)
    0x00A1, 0x00A2, 0x00A3, 0x00A4, 0x00A5, 0x00A6, 0x00A7, 0x00A8, 0x00A9,
    0x00AA, 0x00AB, 0x00AC, 0x00AD, 0x00AE, 0x00AF, 0x00B0, 0x00B1, 0x00B2,
    0x00B3, 0x00B4, 0x00B5,
    # Ghost shop
    0x506F,
    # Mask shop descriptions
    0x7013,
    0x70B9,  # Only the first mask desc; 0x70BA-0x70C1 are buy prompts
}


def main():
    print(f"Loading charmap...")
    charmap = load_charmap()
    print(f"  Loaded {len(charmap)} char mappings")

    print(f"Loading Excel: {XLSX_PATH}")
    wb = openpyxl.load_workbook(XLSX_PATH)
    ws = wb.active

    translations = {}
    for row in ws.iter_rows(min_row=2, values_only=False):
        text_id = row[0].value  # Column A
        translation = row[3].value  # Column D (AI翻译)
        if text_id and translation:
            translations[str(text_id).strip()] = str(translation).strip()

    print(f"  Loaded {len(translations)} translations")

    print(f"Reading z_message_CHI.cpp...")
    with open(CPP_PATH, 'r', encoding='utf-8') as f:
        cpp_content = f.read()

    updated = 0
    errors = 0

    for text_id_str, translation_text in sorted(translations.items()):
        text_id = int(text_id_str, 16)
        hex_id = f"{text_id:04X}"

        # Get original header
        header, original_bytes = get_original_header(cpp_content, text_id_str)
        if header is None:
            print(f"  ERROR: 0x{hex_id} not found in CPP")
            errors += 1
            continue

        # Check if translation has [选择] tag
        has_choice = '[选择]' in translation_text
        clean_text = translation_text.replace('[选择]', '')

        # Encode the translation
        encoded = encode_text(clean_text, charmap)

        # Build complete message: header + encoded text + ending
        msg = bytearray(header) + encoded

        if has_choice:
            if text_id in MASK_MESSAGES:
                msg.extend(TWO_CHOICE_BORROW)
            else:
                msg.extend(TWO_CHOICE_BUY)
        elif text_id in SHOP_DESCRIPTION_IDS:
            # Shop item descriptions need QUICKTEXT_OFF + PERSISTENT + END
            msg.extend([0x09, 0x0A, 0x02])
        else:
            # End with 0x02 (END)
            if not msg or msg[-1] != 0x02:
                msg.append(0x02)

        # Format as C hex array
        hex_str = ', '.join(f'0x{b:02X}' for b in msg)
        new_data_line = f'static const u8 sCHIMsgData_0x{hex_id}[] = {{ {hex_str} }};'

        # Replace data array in CPP
        data_pattern = re.compile(
            r'static\s+const\s+u8\s+sCHIMsgData_0x' + hex_id + r'\[\]\s*=\s*\{[^}]+\};'
        )
        if data_pattern.search(cpp_content):
            cpp_content = data_pattern.sub(new_data_line, cpp_content)
        else:
            print(f"  ERROR: Could not find data array for 0x{hex_id}")
            errors += 1
            continue

        # Update table entry size
        msg_type = get_msg_type(cpp_content, text_id_str)
        table_pattern = re.compile(
            r'\{\s*0x' + hex_id + r',\s*0x[0-9A-Fa-f]+,\s*\(const char\*\)sCHIMsgData_0x' + hex_id + r',\s*\d+\s*\}'
        )
        new_table_entry = f'{{ 0x{hex_id}, 0x{msg_type:02X}, (const char*)sCHIMsgData_0x{hex_id}, {len(msg)} }}'
        if table_pattern.search(cpp_content):
            cpp_content = table_pattern.sub(new_table_entry, cpp_content)
        else:
            print(f"  WARNING: Could not find table entry for 0x{hex_id}")

        updated += 1

    # Write back
    with open(CPP_PATH, 'w', encoding='utf-8') as f:
        f.write(cpp_content)

    print(f"\nDone!")
    print(f"  Updated: {updated}")
    print(f"  Errors:  {errors}")
    print(f"  Written: {CPP_PATH}")


if __name__ == '__main__':
    main()

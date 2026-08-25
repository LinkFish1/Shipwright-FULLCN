#!/usr/bin/env python3
"""Compare English and Chinese message content lengths to find truncated iQue messages.

Counts printable characters (excluding control codes) in both English and Chinese
messages, and flags Chinese messages that are suspiciously short.
"""

import struct
import re
import sys
import os

# Control codes with extra parameter bytes (NES/iQue encoding)
NES_CTRL_EXTRA = {
    0x05: 1,  # COLOR
    0x06: 1,  # SHIFT
    0x07: 2,  # GOTO
    0x0C: 1,  # DELAY
    0x0E: 1,  # FADE
    0x11: 2,  # FADE2
    0x12: 2,  # SFX
    0x13: 1,  # ICON
    0x14: 1,  # SPEED
    0x15: 3,  # BACKGROUND
    0x1E: 1,  # HIGHSCORE
}


def count_eng_chars(data):
    """Count printable characters in an English NES message."""
    i = 0
    count = 0
    while i < len(data):
        b = data[i]
        if b >= 0x20:  # printable
            count += 1
            i += 1
        elif b in NES_CTRL_EXTRA:
            i += 1 + NES_CTRL_EXTRA[b]
        else:
            i += 1
    return count


def count_chi_chars(data):
    """Count printable characters in a Chinese iQue message.

    Chinese 2-byte chars (>=0xA0) count as 1 char each.
    ASCII printable (0x20-0x9E) count as 1 char each.
    """
    i = 0
    count = 0
    while i < len(data):
        b = data[i]
        if b >= 0xA0:  # Chinese 2-byte char
            count += 1
            i += 2
        elif b >= 0x20:  # ASCII printable
            count += 1
            i += 1
        elif b in NES_CTRL_EXTRA:
            i += 1 + NES_CTRL_EXTRA[b]
        else:
            i += 1
    return count


def has_two_choice(data):
    """Check if message contains TWO_CHOICE (0x1B)."""
    return 0x1B in data


def parse_otr_messages(otr_path):
    import zipfile
    messages = {}
    with zipfile.ZipFile(otr_path, 'r') as zf:
        target = None
        for name in zf.namelist():
            if 'ntsc_nes_message_data_static' in name:
                target = name
                break
        if not target:
            print("ERROR: Could not find ntsc_nes_message_data_static in OTR")
            sys.exit(1)
        raw = zf.read(target)

    offset = 64
    count = struct.unpack_from('<I', raw, offset)[0]
    offset += 4

    for i in range(count):
        if offset + 8 > len(raw):
            break
        text_id = struct.unpack_from('<H', raw, offset)[0]
        msg_type = raw[offset + 2]
        msg_size = struct.unpack_from('<I', raw, offset + 4)[0]
        offset += 8
        if offset + msg_size > len(raw):
            break
        msg_data = raw[offset:offset + msg_size]
        offset += msg_size
        messages[text_id] = msg_data
    return messages


def parse_chi_messages(cpp_path):
    messages = {}
    with open(cpp_path, 'r') as f:
        content = f.read()

    data_pattern = re.compile(
        r'static\s+const\s+u8\s+sCHIMsgData_(0x[0-9A-Fa-f]+)\[\]\s*=\s*\{([^}]+)\};'
    )
    for m in data_pattern.finditer(content):
        text_id = int(m.group(1), 16)
        hex_bytes = m.group(2)
        byte_values = []
        for token in hex_bytes.split(','):
            token = token.strip()
            if token and token.startswith('0x'):
                byte_values.append(int(token, 16))
        messages[text_id] = bytes(byte_values)
    return messages


def decode_eng_text(data):
    """Decode English NES message to readable text (approximate)."""
    i = 0
    result = []
    while i < len(data):
        b = data[i]
        if b >= 0x20 and b <= 0x7E:
            result.append(chr(b))
            i += 1
        elif b >= 0x7F and b < 0xA0:
            result.append('?')
            i += 1
        elif b == 0x01:
            result.append('\\n')
            i += 1
        elif b == 0x04:
            result.append('[BOX]')
            i += 1
        elif b == 0x02:
            result.append('[END]')
            i += 1
        elif b == 0x0B:
            result.append('[EVENT]')
            i += 1
        elif b == 0x1B:
            result.append('[TWO_CHOICE]')
            i += 1
        elif b in NES_CTRL_EXTRA:
            i += 1 + NES_CTRL_EXTRA[b]
        else:
            i += 1
    return ''.join(result)


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    shipwright = os.path.dirname(os.path.dirname(base))

    otr_path = os.path.join(shipwright, "oot.o2r")
    chi_path = os.path.join(shipwright, "soh", "soh", "z_message_CHI.cpp")

    if not os.path.exists(otr_path):
        for alt in [
            os.path.join(shipwright, "soh", "oot.o2r"),
            os.path.join(shipwright, "build-cmake", "soh", "oot.o2r"),
            os.path.join(shipwright, "build-switch", "soh", "oot.o2r"),
        ]:
            if os.path.exists(alt):
                otr_path = alt
                break

    print(f"OTR: {otr_path}")
    print(f"CHI: {chi_path}")
    print()

    eng_msgs = parse_otr_messages(otr_path)
    chi_msgs = parse_chi_messages(chi_path)
    print(f"English: {len(eng_msgs)} messages, Chinese: {len(chi_msgs)} messages\n")

    # Compare
    truncated = []  # (text_id, eng_chars, chi_chars, ratio, eng_bytes, chi_bytes, eng_text)
    missing_choice = []  # English has TWO_CHOICE but Chinese doesn't

    skip_ids = {0xFFFF, 0xFFFD}

    for text_id in sorted(eng_msgs.keys()):
        if text_id in skip_ids or text_id not in chi_msgs:
            continue

        eng_data = eng_msgs[text_id]
        chi_data = chi_msgs[text_id]

        eng_chars = count_eng_chars(eng_data)
        chi_chars = count_chi_chars(chi_data)

        # Skip very short messages (< 3 printable chars in English)
        if eng_chars < 3:
            continue

        ratio = chi_chars / eng_chars if eng_chars > 0 else 1.0

        # Flag if Chinese has less than 15% of English char count
        # Chinese is very compact (typical ratio ~25-35%), so only flag extreme cases
        if ratio < 0.15:
            eng_text = decode_eng_text(eng_data)[:80]
            truncated.append((text_id, eng_chars, chi_chars, ratio, len(eng_data), len(chi_data), eng_text))

        # Check TWO_CHOICE mismatch
        eng_has_choice = has_two_choice(eng_data)
        chi_has_choice = has_two_choice(chi_data)
        if eng_has_choice and not chi_has_choice:
            eng_text = decode_eng_text(eng_data)[:80]
            missing_choice.append((text_id, eng_text))

    # Report truncated messages
    print("=" * 100)
    print(f"TRUNCATED CHINESE MESSAGES (chi/eng char ratio < 0.40): {len(truncated)}")
    print("=" * 100)
    print(f"{'TextId':>8}  {'ENG':>4}  {'CHI':>4}  {'Ratio':>6}  {'EBytes':>6}  {'CBytes':>6}  English text")
    print("-" * 100)
    for text_id, eng_c, chi_c, ratio, eng_b, chi_b, eng_text in sorted(truncated, key=lambda x: x[3]):
        print(f"  0x{text_id:04X}  {eng_c:4d}  {chi_c:4d}  {ratio:5.1%}  {eng_b:6d}  {chi_b:6d}  {eng_text}")

    # Report missing TWO_CHOICE
    if missing_choice:
        print(f"\n{'=' * 100}")
        print(f"MISSING TWO_CHOICE (English has it, Chinese doesn't): {len(missing_choice)}")
        print(f"{'=' * 100}")
        for text_id, eng_text in missing_choice:
            print(f"  0x{text_id:04X}: {eng_text}")

    # Summary
    print(f"\n{'=' * 100}")
    print("SUMMARY")
    print(f"{'=' * 100}")
    print(f"  Messages compared:    {len(eng_msgs) - len(skip_ids)}")
    print(f"  Truncated (< 40%):    {len(truncated)}")
    print(f"  Missing TWO_CHOICE:   {len(missing_choice)}")


if __name__ == '__main__':
    main()

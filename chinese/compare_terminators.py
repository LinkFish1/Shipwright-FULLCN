#!/usr/bin/env python3
"""Compare English and Chinese message terminators for OoT SoH.

Parses:
- English messages from oot.o2r (OTR archive, text/nes_message_data_static/ntsc_nes_message_data_static)
- Chinese messages from z_message_CHI.cpp (hex byte arrays)

Reports mismatches in final terminator codes.
"""

import struct
import re
import sys
import os

# Control codes
CTRL_NAMES = {
    0x00: "PAD",
    0x01: "NEWLINE",
    0x02: "END",
    0x04: "BOX_BREAK",
    0x05: "COLOR",
    0x06: "SHIFT",
    0x07: "GOTO",  # textId u16
    0x08: "INSTANT_ON",
    0x09: "INSTANT_OFF/QUICKTEXT_OFF",
    0x0A: "PERSISTENT",
    0x0B: "EVENT",
    0x0C: "DELAY",
    0x0D: "AWAIT_BUTTON",
    0x0E: "FADE",
    0x0F: "NAME",
    0x10: "OCARINA",
    0x11: "FADE2",
    0x12: "SFX",
    0x13: "ICON",
    0x14: "SPEED",
    0x15: "BACKGROUND",
    0x16: "MARATHON_TIME",
    0x17: "RACE_TIME",
    0x18: "POINTS",
    0x19: "TOKENS",
    0x1A: "UNSKIPPABLE",
    0x1B: "TWO_CHOICE",
    0x1C: "THREE_CHOICE",
    0x1D: "FISH_INFO",
    0x1E: "HIGHSCORE",
    0x1F: "TIME",
}

# Control codes with extra parameter bytes (NES encoding)
NES_CTRL_EXTRA = {
    0x05: 1,  # COLOR: 1 byte
    0x06: 1,  # SHIFT: 1 byte
    0x07: 2,  # GOTO: 2 bytes (textId)
    0x0C: 1,  # DELAY: 1 byte
    0x0E: 1,  # FADE: 1 byte
    0x11: 2,  # FADE2: 2 bytes
    0x12: 2,  # SFX: 2 bytes
    0x13: 1,  # ICON: 1 byte
    0x14: 1,  # SPEED: 1 byte
    0x15: 3,  # BACKGROUND: 3 bytes
    0x1E: 1,  # HIGHSCORE: 1 byte
}


def find_nes_terminator(data):
    """Find the final terminator of a NES-encoded English message.

    Returns a list of control codes at the end of the message.
    Terminators: END(0x02), EVENT(0x0B), GOTO(0x07)
    Pre-terminators: QUICKTEXT_OFF(0x09), PERSISTENT(0x0A)
    """
    i = 0
    last_terminators = []

    while i < len(data):
        b = data[i]
        if b == 0x02:  # END
            last_terminators.append(0x02)
            break
        elif b == 0x0B:  # EVENT
            last_terminators.append(0x0B)
            # EVENT may be followed by END
            if i + 1 < len(data) and data[i + 1] == 0x02:
                last_terminators.append(0x02)
            break
        elif b == 0x07:  # GOTO
            last_terminators.append(0x07)
            break
        elif b in NES_CTRL_EXTRA:
            i += 1 + NES_CTRL_EXTRA[b]
        elif b < 0x20:  # other control code
            i += 1
        else:  # printable char
            last_terminators = []
            i += 1

    return last_terminators


def find_chi_terminator(data):
    """Find the final terminator of a Chinese message using iQue decoder simulation.

    iQue encoding:
    - 0x00-0x1F: control codes
    - 0x20-0x9E: ASCII/printable
    - >= 0xA0: high byte of 2-byte Chinese character

    Returns a list of control codes at the end of the message.
    """
    i = 0
    last_terminators = []

    while i < len(data):
        b = data[i]

        if b >= 0xA0:  # Chinese character (2 bytes)
            if i + 1 < len(data):
                i += 2
                last_terminators = []  # reset - we saw a printable char
            else:
                # Orphan high byte at end - problematic
                last_terminators = [("ORPHAN_HIGH", b)]
                break
        elif b == 0x02:  # END
            last_terminators.append(0x02)
            break
        elif b == 0x0B:  # EVENT
            last_terminators.append(0x0B)
            if i + 1 < len(data) and data[i + 1] == 0x02:
                last_terminators.append(0x02)
            break
        elif b == 0x07:  # GOTO
            if i + 2 < len(data):
                goto_target = (data[i + 1] << 8) | data[i + 2]
                last_terminators.append(0x07)
                i += 3
                # After GOTO, there's usually END
                if i < len(data) and data[i] == 0x02:
                    last_terminators.append(0x02)
                break
            else:
                i += 1
        elif b == 0x04:  # BOX_BREAK
            i += 1
            last_terminators = []  # not a final terminator per se, reset
        elif b in NES_CTRL_EXTRA:
            i += 1 + NES_CTRL_EXTRA[b]
        elif b < 0x20:  # other control code
            i += 1
        else:  # ASCII printable (0x20-0x9E)
            last_terminators = []
            i += 1

    return last_terminators


def find_chi_has_persistent(data):
    """Check if Chinese message has PERSISTENT (0x0A) before its terminator."""
    i = 0
    has_persistent = False

    while i < len(data):
        b = data[i]
        if b >= 0xA0:
            i += 2
        elif b == 0x0A:
            has_persistent = True
            i += 1
        elif b == 0x02 or b == 0x0B:
            break
        elif b in NES_CTRL_EXTRA:
            i += 1 + NES_CTRL_EXTRA[b]
        else:
            i += 1

    return has_persistent


def find_nes_has_persistent(data):
    """Check if English message has PERSISTENT (0x0A) before its terminator."""
    i = 0
    has_persistent = False

    while i < len(data):
        b = data[i]
        if b == 0x0A:
            has_persistent = True
            i += 1
        elif b == 0x02 or b == 0x0B:
            break
        elif b in NES_CTRL_EXTRA:
            i += 1 + NES_CTRL_EXTRA[b]
        else:
            i += 1

    return has_persistent


def parse_otr_messages(otr_path):
    """Parse English messages from oot.o2r OTR archive.

    The file is a ZIP-like archive. We need to find and extract
    text/nes_message_data_static/ntsc_nes_message_data_static
    """
    import zipfile

    messages = {}

    with zipfile.ZipFile(otr_path, 'r') as zf:
        # Find the message data file
        target = None
        for name in zf.namelist():
            if 'ntsc_nes_message_data_static' in name:
                target = name
                break

        if not target:
            print("ERROR: Could not find ntsc_nes_message_data_static in OTR")
            sys.exit(1)

        print(f"Found: {target}")
        raw = zf.read(target)

    # Parse the binary format
    # First 64 bytes: OTR resource header
    # Offset 64: LE u32 count
    offset = 64
    count = struct.unpack_from('<I', raw, offset)[0]
    print(f"Message count: {count}")
    offset += 4

    for i in range(count):
        if offset + 8 > len(raw):
            print(f"WARNING: Ran out of data at message {i}")
            break

        text_id = struct.unpack_from('<H', raw, offset)[0]
        msg_type = raw[offset + 2]
        pad = raw[offset + 3]
        msg_size = struct.unpack_from('<I', raw, offset + 4)[0]
        offset += 8

        if offset + msg_size > len(raw):
            print(f"WARNING: Message 0x{text_id:04X} size {msg_size} exceeds data")
            break

        msg_data = raw[offset:offset + msg_size]
        offset += msg_size

        messages[text_id] = {
            'type': msg_type,
            'data': msg_data,
        }

    return messages


def parse_chi_messages(cpp_path):
    """Parse Chinese messages from z_message_CHI.cpp."""
    messages = {}

    with open(cpp_path, 'r') as f:
        content = f.read()

    # Parse byte arrays: static const u8 sCHIMsgData_0xXXXX[] = { 0xHH, ... };
    data_pattern = re.compile(
        r'static\s+const\s+u8\s+sCHIMsgData_(0x[0-9A-Fa-f]+)\[\]\s*=\s*\{([^}]+)\};'
    )

    for m in data_pattern.finditer(content):
        text_id = int(m.group(1), 16)
        hex_bytes = m.group(2)
        # Parse hex bytes
        byte_values = []
        for token in hex_bytes.split(','):
            token = token.strip()
            if token and token.startswith('0x'):
                byte_values.append(int(token, 16))

        messages[text_id] = {
            'data': bytes(byte_values),
        }

    # Parse table entries for type info: { 0xXXXX, 0xTT, (const char*)sCHIMsgData_0xXXXX, SIZE },
    table_pattern = re.compile(
        r'\{\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),\s*\(const char\*\)sCHIMsgData_(0x[0-9A-Fa-f]+),\s*(\d+)\s*\}'
    )

    for m in table_pattern.finditer(content):
        text_id = int(m.group(1), 16)
        msg_type = int(m.group(2), 16)
        declared_size = int(m.group(4))

        if text_id in messages:
            messages[text_id]['type'] = msg_type
            messages[text_id]['declared_size'] = declared_size
            actual_size = len(messages[text_id]['data'])
            if actual_size != declared_size:
                print(f"  SIZE MISMATCH 0x{text_id:04X}: declared={declared_size}, actual={actual_size}")

    return messages


def terminator_name(code):
    if isinstance(code, tuple):
        return f"{code[0]}(0x{code[1]:02X})"
    return CTRL_NAMES.get(code, f"0x{code:02X}")


def terminator_list_str(terms):
    return " → ".join(terminator_name(t) for t in terms) if terms else "NONE"


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    shipwright = os.path.dirname(os.path.dirname(base))

    otr_path = os.path.join(shipwright, "oot.o2r")
    chi_path = os.path.join(shipwright, "soh", "soh", "z_message_CHI.cpp")

    if not os.path.exists(otr_path):
        # Try other locations
        for alt in [
            os.path.join(shipwright, "soh", "oot.o2r"),
            os.path.join(shipwright, "build-cmake", "soh", "oot.o2r"),
            os.path.join(shipwright, "OTRExporter", "oot.o2r"),
        ]:
            if os.path.exists(alt):
                otr_path = alt
                break

    print(f"OTR path: {otr_path}")
    print(f"CHI path: {chi_path}")
    print()

    # Parse both
    print("=== Parsing English messages from OTR ===")
    eng_msgs = parse_otr_messages(otr_path)
    print(f"Parsed {len(eng_msgs)} English messages")
    print()

    print("=== Parsing Chinese messages from CPP ===")
    chi_msgs = parse_chi_messages(chi_path)
    print(f"Parsed {len(chi_msgs)} Chinese messages")
    print()

    # Compare terminators
    print("=" * 80)
    print("=== TERMINATOR COMPARISON ===")
    print("=" * 80)

    # Categories of issues
    end_vs_event = []      # END vs EVENT mismatch
    missing_persistent = [] # English has PERSISTENT but Chinese doesn't
    extra_persistent = []   # Chinese has PERSISTENT but English doesn't
    end_eaten = []          # Chinese END might be eaten by Chinese char
    no_terminator = []      # Chinese has no terminator
    other_mismatch = []     # Other terminator mismatches
    chi_only = []           # Chinese-only messages
    eng_only = []           # English-only messages

    all_ids = sorted(set(list(eng_msgs.keys()) + list(chi_msgs.keys())))

    # Skip sentinel entries
    skip_ids = {0xFFFF, 0xFFFD}

    matched = 0
    total = 0

    for text_id in all_ids:
        if text_id in skip_ids:
            continue

        has_eng = text_id in eng_msgs
        has_chi = text_id in chi_msgs

        if has_eng and not has_chi:
            eng_only.append(text_id)
            continue
        if has_chi and not has_eng:
            chi_only.append(text_id)
            continue

        total += 1

        eng_data = eng_msgs[text_id]['data']
        chi_data = chi_msgs[text_id]['data']

        eng_term = find_nes_terminator(eng_data)
        chi_term = find_chi_terminator(chi_data)

        eng_pers = find_nes_has_persistent(eng_data)
        chi_pers = find_chi_has_persistent(chi_data)

        # Check for issues
        issues = []

        # 1. Terminator type mismatch
        eng_final = eng_term[-1] if eng_term else None
        chi_final = chi_term[-1] if chi_term else None

        if isinstance(chi_final, tuple):
            # Orphan high byte
            end_eaten.append((text_id, eng_term, chi_term))
            issues.append("END_EATEN")
        elif eng_final != chi_final:
            if eng_final == 0x0B and chi_final == 0x02:
                end_vs_event.append((text_id, "ENG=EVENT, CHI=END"))
                issues.append("EVENT→END")
            elif eng_final == 0x02 and chi_final == 0x0B:
                end_vs_event.append((text_id, "ENG=END, CHI=EVENT"))
                issues.append("END→EVENT")
            elif chi_final is None:
                no_terminator.append((text_id, eng_term, chi_term))
                issues.append("NO_TERM")
            else:
                other_mismatch.append((text_id, eng_term, chi_term))
                issues.append("OTHER")

        # 2. PERSISTENT mismatch
        if eng_pers and not chi_pers:
            missing_persistent.append(text_id)
            issues.append("MISSING_PERSISTENT")
        elif chi_pers and not eng_pers:
            extra_persistent.append(text_id)
            issues.append("EXTRA_PERSISTENT")

        if not issues:
            matched += 1

    # Report
    print(f"\nTotal compared: {total}")
    print(f"Matched: {matched}")
    print(f"Issues: {total - matched}")
    print()

    if end_vs_event:
        print(f"\n{'='*60}")
        print(f"END vs EVENT mismatches ({len(end_vs_event)}):")
        print(f"{'='*60}")
        for text_id, desc in end_vs_event:
            print(f"  0x{text_id:04X}: {desc}")
            # Show last few bytes of Chinese message
            chi_data = chi_msgs[text_id]['data']
            tail = ' '.join(f'{b:02X}' for b in chi_data[-10:])
            print(f"    CHI tail: ...{tail}")

    if missing_persistent:
        print(f"\n{'='*60}")
        print(f"Missing PERSISTENT in Chinese ({len(missing_persistent)}):")
        print(f"  English has 0x09+0x0A before END, Chinese doesn't")
        print(f"{'='*60}")
        for text_id in missing_persistent:
            chi_data = chi_msgs[text_id]['data']
            tail = ' '.join(f'{b:02X}' for b in chi_data[-10:])
            print(f"  0x{text_id:04X}: CHI tail: ...{tail}")

    if extra_persistent:
        print(f"\n{'='*60}")
        print(f"Extra PERSISTENT in Chinese ({len(extra_persistent)}):")
        print(f"{'='*60}")
        for text_id in extra_persistent:
            print(f"  0x{text_id:04X}")

    if end_eaten:
        print(f"\n{'='*60}")
        print(f"END possibly eaten by Chinese char ({len(end_eaten)}):")
        print(f"{'='*60}")
        for text_id, eng_term, chi_term in end_eaten:
            chi_data = chi_msgs[text_id]['data']
            tail = ' '.join(f'{b:02X}' for b in chi_data[-10:])
            print(f"  0x{text_id:04X}: ENG={terminator_list_str(eng_term)}, CHI={terminator_list_str(chi_term)}")
            print(f"    CHI tail: ...{tail}")

    if no_terminator:
        print(f"\n{'='*60}")
        print(f"No terminator in Chinese ({len(no_terminator)}):")
        print(f"{'='*60}")
        for text_id, eng_term, chi_term in no_terminator:
            chi_data = chi_msgs[text_id]['data']
            tail = ' '.join(f'{b:02X}' for b in chi_data[-10:])
            print(f"  0x{text_id:04X}: ENG={terminator_list_str(eng_term)}")
            print(f"    CHI tail: ...{tail}")

    if other_mismatch:
        print(f"\n{'='*60}")
        print(f"Other terminator mismatches ({len(other_mismatch)}):")
        print(f"{'='*60}")
        for text_id, eng_term, chi_term in other_mismatch:
            print(f"  0x{text_id:04X}: ENG={terminator_list_str(eng_term)}, CHI={terminator_list_str(chi_term)}")
            chi_data = chi_msgs[text_id]['data']
            tail = ' '.join(f'{b:02X}' for b in chi_data[-10:])
            print(f"    CHI tail: ...{tail}")

    if eng_only:
        print(f"\n{'='*60}")
        print(f"English-only messages ({len(eng_only)}):")
        print(f"{'='*60}")
        for text_id in eng_only[:20]:
            print(f"  0x{text_id:04X}")
        if len(eng_only) > 20:
            print(f"  ... and {len(eng_only) - 20} more")

    if chi_only:
        print(f"\n{'='*60}")
        print(f"Chinese-only messages ({len(chi_only)}):")
        print(f"{'='*60}")
        for text_id in chi_only[:20]:
            print(f"  0x{text_id:04X}")
        if len(chi_only) > 20:
            print(f"  ... and {len(chi_only) - 20} more")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"  Total messages compared: {total}")
    print(f"  Matched (no issues):     {matched}")
    print(f"  END↔EVENT mismatches:    {len(end_vs_event)}")
    print(f"  Missing PERSISTENT:      {len(missing_persistent)}")
    print(f"  Extra PERSISTENT:        {len(extra_persistent)}")
    print(f"  END eaten by CJK char:   {len(end_eaten)}")
    print(f"  No terminator:           {len(no_terminator)}")
    print(f"  Other mismatches:        {len(other_mismatch)}")
    print(f"  English-only:            {len(eng_only)}")
    print(f"  Chinese-only:            {len(chi_only)}")


if __name__ == '__main__':
    main()

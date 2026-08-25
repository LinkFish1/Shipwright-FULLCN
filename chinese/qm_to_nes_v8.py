#!/usr/bin/env python3
"""QM→NES converter v8.
- 139 icon messages: use xlsx translations with NTSC icon bytes
- 1977 non-icon messages: use 3DS QM Chinese (v6 logic)
- 3-byte Chinese encoding: 0x03 + high + low
"""
import struct, json, re, sys, openpyxl
from collections import Counter

with open('./tmp/oot3d_cn.qm', 'rb') as f:
    qm = f.read()
with open('./tmp/ntsc_messages_parsed.json', 'r', encoding='utf-8') as f:
    ntsc_msgs = json.load(f)
ntsc_by_id = {m['textId']: m for m in ntsc_msgs}

charmap = {}
with open('./tmp/charmap_chn.txt', 'r', encoding='utf-8') as f:
    for line in f:
        m = re.match(r"'(.)'\s*:\s*(0x[0-9A-Fa-f]+)", line.strip())
        if m:
            charmap[m.group(1)] = int(m.group(2), 16)
char_to_nes = {ord(ch): code for ch, code in charmap.items()}
print(f"Charmap: {len(charmap)} chars", file=sys.stderr)

# Fullwidth → ASCII
fullwidth_map = {}
for i in range(10): fullwidth_map[0xFF10 + i] = ord('0') + i
for i in range(26): fullwidth_map[0xFF21 + i] = ord('A') + i
for i in range(26): fullwidth_map[0xFF41 + i] = ord('a') + i
for src, dst in [(0xFF01,'!'),(0xFF08,'('),(0xFF09,')'),(0xFF0C,','),(0xFF1A,':'),(0xFF1B,';'),
    (0xFF1F,'?'),(0xFF0E,'.'),(0xFF3B,'['),(0xFF3D,']'),(0x3000,' '),(0xFF5E,'~'),
    (0x2026,'.'),(0x00B7,'.'),(0x2014,'-'),(0x2015,'-'),(0x2018,"'"),(0x2019,"'"),
    (0x201C,'"'),(0x201D,'"'),(0x3001,','),(0x3002,'.'),(0x300A,'<'),(0x300B,'>'),
    (0x300C,'['),(0x300D,']'),(0x300E,'['),(0x300F,']'),(0xFF02,'"'),(0xFF07,"'"),(0xFF06,'&')]:
    fullwidth_map[src] = ord(dst)

num_entries = struct.unpack('<I', qm[8:12])[0]
entry_size = 120
#CHI_CHAR_ESC = 0x03

# Icon tag → NES byte
ICON_TAG_MAP = {
    #'[C上]': 0x9F, '[C下]': 0xA0, '[C左]': 0xA1, '[C右]': 0xA2,
    #'[R]': 0xA3, '[Z]': 0xA4, '[摇杆]': 0xA5, '[D-Pad]': 0xA6,
    #'[B]': 0xA7, '[Z钮]': 0xA8, '[R钮]': 0xA9, '[L钮]': 0xAA,

    '[A]': 0xAA9F, '[B]': 0xAAA0, '[C]': 0xAAA1, '[L]': 0xAAA2,
    '[R]': 0xAAA3, '[Z]': 0xAAA4, '[↑]': 0xAAA5, '[↓]': 0xAAA6,
    '[←]': 0xAAA7, '[→]': 0xAAA8, '[▼]': 0xAAA9, '[+]': 0xAAAA,
    '[P]': 0xAAAB, #D-pad
    '[n]': 0x0F, #Link's name
    '[dd]': 0x0C28, #wait 28
}
# Control tags
CTRL_TAG_MAP = {
    '[换框]': 0x04, '[ICON]': None, '[TIME]': 0x1F,
    '[MARATHON]': 0x16, '[RACE]': 0x17, '[POINTS]': 0x18,
    '[TOKENS]': 0x19, '[FISH]': 0x1D,
}

def get_qm_entry(idx):
    off = 16 + idx * entry_size
    textId = struct.unpack('<I', qm[off:off+4])[0]
    typ = struct.unpack('<I', qm[off+8:off+12])[0]
    ypos = struct.unpack('<I', qm[off+12:off+16])[0]
    cn_slot_off = off + 16 + 10 * 8
    cn_data_off = struct.unpack('<I', qm[cn_slot_off:cn_slot_off+4])[0]
    cn_data_size = struct.unpack('<I', qm[cn_slot_off+4:cn_slot_off+8])[0]
    vals = []
    if cn_data_off > 0 and cn_data_size > 0 and cn_data_off + cn_data_size <= len(qm):
        for i in range(0, cn_data_size, 2):
            v = struct.unpack('<H', qm[cn_data_off+i:cn_data_off+i+2])[0]
            vals.append(v)
    return textId, typ, ypos, vals

# NTSC SFX IDs per textId
ntsc_sfx = {}
for m in ntsc_msgs:
    raw = bytes.fromhex(m['raw_hex'])
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0x12 and i+2 < len(raw):
            ntsc_sfx.setdefault(m['textId'], []).append((raw[i+1] << 8) | raw[i+2])
            i += 3; continue
        elif b == 0x05: i += 2; continue
        elif b == 0x06: i += 2; continue
        elif b == 0x07: i += 3; continue
        elif b == 0x0C: i += 2; continue
        elif b == 0x0E: i += 2; continue
        elif b == 0x11: i += 3; continue
        elif b == 0x13: i += 2; continue
        elif b == 0x14: i += 2; continue
        elif b == 0x15: i += 4; continue
        elif b == 0x1E: i += 2; continue
        i += 1

# --- Load xlsx translations for 139 icon messages ---
wb = openpyxl.load_workbook('./tmp/icon_messages_139_translation.xlsx')
ws = wb.active
xlsx_translations = {}
for row in range(2, ws.max_row + 1):
    tid_str = ws.cell(row=row, column=1).value
    translation = ws.cell(row=row, column=6).value
    if tid_str and translation and translation.strip():
        tid = int(tid_str, 16)
        xlsx_translations[tid] = translation.strip()
print(f"Xlsx translations: {len(xlsx_translations)} messages", file=sys.stderr)

def translate_to_nes(textId, text, ntsc_raw_hex):
    """Convert translated text (with icon tags) to NES bytes.
    Uses NTSC raw as source for control codes (QTE/QTD/COLOR/SFX/ITEM_ICON/etc),
    text portion replaced with Chinese translation."""
    # Strategy: parse NTSC raw to extract control code structure,
    # then build new message from translated text with icon bytes.
    # Since translation is based on NTSC English structure, we take
    # NTSC control codes and rebuild with Chinese text + icon bytes.

    ntsc_raw = bytes.fromhex(ntsc_raw_hex)
    out = []
    unmapped = []

    # Extract NTSC control codes in order (non-text bytes)
    # We need: UNSKIPPABLE, ITEM_ICON, QTE, QTD, COLOR, SFX, etc.
    # These are at specific positions in NTSC. We'll inject them.

    # Approach: scan NTSC for leading control codes per box,
    # then use translated text for content.

    # Simpler approach: parse the translated text directly.
    # Tags like [ICON], [换框], [C左], [二选一], [三选一] are explicit.
    # We need to also carry over NTSC's QTE/QTD, COLOR, SFX, UNSKIPPABLE, ITEM_ICON.

    # Extract NTSC per-box metadata
    boxes = []
    cur_box = {'pre': [], 'post': []}
    i = 0
    while i < len(ntsc_raw):
        b = ntsc_raw[i]
        if b == 0x02: break  # END
        elif b == 0x04:  # BOX_BREAK
            boxes.append(cur_box)
            cur_box = {'pre': [], 'post': []}
            i += 1
        elif b == 0x1A:  # UNSKIPPABLE
            cur_box['pre'].append(bytes([0x1A]))
            i += 1
        elif b == 0x13:  # ITEM_ICON
            cur_box['pre'].append(bytes([0x13, ntsc_raw[i+1]]))
            i += 2
        elif b == 0x08:  # QTE
            cur_box['pre'].append(bytes([0x08]))
            i += 1
        elif b == 0x09:  # QTD
            cur_box['post'].append(bytes([0x09]))
            i += 1
        elif b == 0x12:  # SFX
            cur_box['pre'].append(bytes([0x12, ntsc_raw[i+1], ntsc_raw[i+2]]))
            i += 3
        elif b == 0x0B:  # EVENT
            cur_box['post'].append(bytes([0x0B]))
            i += 1
        elif b == 0x0A:  # PERSISTENT
            cur_box['post'].append(bytes([0x0A]))
            i += 1
        elif b == 0x0D:  # AWAIT
            cur_box['post'].append(bytes([0x0D]))
            i += 1
        elif b == 0x0E:  # FADE
            cur_box['post'].append(bytes([0x0E, ntsc_raw[i+1]]))
            i += 2
        elif b == 0x11:  # FADE2
            cur_box['post'].append(bytes([0x11, ntsc_raw[i+1], ntsc_raw[i+2]]))
            i += 3
        elif b == 0x07:  # TEXTID
            cur_box['post'].append(bytes([0x07, ntsc_raw[i+1], ntsc_raw[i+2]]))
            i += 3
        elif b == 0x05:  # COLOR - skip, we handle inline
            i += 2
        elif b == 0x06:  # SHIFT - skip
            i += 2
        elif b == 0x14:  # TEXT_SPEED
            cur_box['pre'].append(bytes([0x14, ntsc_raw[i+1]]))
            i += 2
        elif b == 0x15:  # BACKGROUND
            cur_box['pre'].append(bytes([0x15, ntsc_raw[i+1], ntsc_raw[i+2], ntsc_raw[i+3]]))
            i += 4
        elif b == 0x1E:  # HIGHSCORE
            cur_box['post'].append(bytes([0x1E, ntsc_raw[i+1]]))
            i += 2
        elif b == 0x10:  # OCARINA
            cur_box['post'].append(bytes([0x10]))
            i += 1
        elif b == 0x1B:  # TWO_CHOICE
            cur_box['post'].append(bytes([0x1B]))
            i += 1
        elif b == 0x1C:  # THREE_CHOICE
            cur_box['post'].append(bytes([0x1C]))
            i += 1
        elif b == 0x0C:  # BOX_BREAK_DELAYED
            cur_box['post'].append(bytes([0x0C, ntsc_raw[i+1]]))
            i += 2
        else:
            i += 1
    boxes.append(cur_box)

    # Now parse translated text into boxes
    text_boxes = text.split('[换框]')

    # Build NES bytes
    for box_idx, tbox in enumerate(text_boxes):
        if box_idx > 0:
            out.append(0x04)  # BOX_BREAK

        # 确定使用哪个框的控制符
        if box_idx < len(boxes):
            cur_pre = boxes[box_idx]['pre']
            cur_post = boxes[box_idx]['post']
        else:
            # 新增框：使用原版最后一个框的控制符
            if boxes:
                cur_pre = boxes[-1]['pre']
                cur_post = boxes[-1]['post']
            else:
                cur_pre = []
                cur_post = []

        # Inject NTSC pre-controls
        for ctrl in cur_pre:
            out.extend(ctrl)

        # Parse text content
        tbox = tbox.strip()
        # Remove [ICON] tags (already handled by ITEM_ICON in pre-controls)
        tbox = tbox.replace('[ICON]', '')

        # Handle [二选一] and [三选一]
        has_choice = None
        if '[二选一]' in tbox:
            has_choice = 0x1B
            tbox = tbox.replace('[二选一]', '\n')
        if '[三选一]' in tbox:
            has_choice = 0x1C
            tbox = tbox.replace('[三选一]', '\n')

        # Process character by character, handling tags
        j = 0
        tbox_chars = tbox
        while j < len(tbox_chars):
            ch = tbox_chars[j]

            # Check for icon/control tags
            color_match = re.match(r'\[0x05 0x([0-9A-Fa-f]{2})\]', tbox_chars[j:])
            if color_match:
                color_byte = int(color_match.group(1), 16)
                out.append(0x05)
                out.append(color_byte)
                j += len(color_match.group(0))
                continue

            delay_box_match = re.match(r'\[0x0C 0x([0-9A-Fa-f]{2})\]', tbox_chars[j:])
            if delay_box_match:
                param = int(delay_box_match.group(1), 16)
                out.append(0x0C)
                out.append(param)
                j += len(delay_box_match.group(0))
                continue

            tag_found = False
            for tag, byte_val in {**ICON_TAG_MAP, **CTRL_TAG_MAP}.items():
                if tbox_chars[j:].startswith(tag):
                    if byte_val is not None:
                        # 处理多字节值
                        if byte_val > 0xFF:
                            # 如果是2字节值，拆分为高字节和低字节
                            out.append((byte_val >> 8) & 0xFF)
                            out.append(byte_val & 0xFF)
                        else:
                            # 单字节直接添加
                            out.append(byte_val)
                    j += len(tag)
                    tag_found = True
                    break
            if tag_found:
                continue

            if ch == '\n':
                out.append(0x01)  # NEWLINE
            elif ch == '\r':
                pass
            elif 0x20 <= ord(ch) <= 0x7E:
                out.append(ord(ch))  # ASCII
            else:
                cp = ord(ch)
                if cp in char_to_nes:
                    code = char_to_nes[cp]
                    out.extend([(code >> 8) & 0xFF, code & 0xFF])
                elif cp in fullwidth_map:
                    out.append(fullwidth_map[cp])
                else:
                    unmapped.append((cp, ch))
                    if ord('?') in char_to_nes:
                        code = char_to_nes[ord('?')]
                        out.extend([(code >> 8) & 0xFF, code & 0xFF])
                    else:
                        out.append(0x3F)
            j += 1

        # Inject choice control if present
        if has_choice:
            out.append(has_choice)

        # Inject NTSC post-controls (QTD, EVENT, PERSISTENT, FADE, TEXTID, etc.)
        for ctrl in cur_post:
            # Skip TWO_CHOICE/THREE_CHOICE if we already added from text
            if ctrl[0] in (0x1B, 0x1C) and has_choice:
                continue
            if ctrl[0] == 0x0C:   # 跳过延迟换框，由文本标签控制
                continue
            out.extend(ctrl)

    if not out or out[-1] != 0x02:
        out.append(0x02)
    return bytes(out), unmapped


def qm_to_nes(textId, vals):
    """Original v6 QM→NES converter for non-icon messages."""
    out = []
    i = 0
    unmapped_chars = []
    sfx_idx = 0

    while i < len(vals):
        v = vals[i]
        if v == 0x007F and i+1 < len(vals):
            esc = vals[i+1]; i += 2
            if esc == 0x0000: out.append(0x02)
            elif esc == 0x0001: out.append(0x04)
            elif esc == 0x0002: i += 1  # SHIFT drop
            elif esc == 0x0003:
                p = vals[i] if i < len(vals) else 0; i += 1
                out.extend([0x07, (p >> 8) & 0xFF, p & 0xFF])
            elif esc == 0x0004: out.append(0x08)
            elif esc == 0x0005: out.append(0x09)
            elif esc == 0x0006: p = vals[i] if i < len(vals) else 0; i += 1; out.append(0x0A)
            elif esc == 0x0007: out.append(0x0B)
            elif esc == 0x0008: p = vals[i] if i < len(vals) else 0x28; i += 1; out.extend([0x0C, p & 0xFF])
            elif esc == 0x0009: out.append(0x0D)
            elif esc == 0x000A: p = vals[i] if i < len(vals) else 0x3C; i += 1; out.extend([0x0E, p & 0xFF])
            elif esc == 0x000B: out.append(0x0F)
            elif esc == 0x000C: out.append(0x10)
            elif esc == 0x000D: p = vals[i] if i < len(vals) else 0; i += 1; out.extend([0x11, (p >> 8) & 0xFF, p & 0xFF])
            elif esc == 0x000E:
                i += 3
                if textId in ntsc_sfx and sfx_idx < len(ntsc_sfx[textId]):
                    sfx = ntsc_sfx[textId][sfx_idx]
                    out.extend([0x12, (sfx >> 8) & 0xFF, sfx & 0xFF])
                sfx_idx += 1
            elif esc == 0x000F: p = vals[i] if i < len(vals) else 0; i += 1; out.extend([0x13, p & 0xFF])
            elif esc == 0x0010: p = vals[i] if i < len(vals) else 0; i += 1; out.extend([0x14, p & 0xFF])
            elif esc == 0x0011:
                p1 = vals[i] if i < len(vals) else 0; i += 1
                p2 = vals[i] if i < len(vals) else 0; i += 1
                out.extend([0x15, p1 & 0xFF, (p2 >> 8) & 0xFF, p2 & 0xFF])
            elif esc == 0x0012: out.append(0x16)
            elif esc == 0x0013: out.append(0x17)
            elif esc == 0x0014: out.append(0x18)
            elif esc == 0x0015: out.append(0x19)
            elif esc == 0x0016: out.append(0x1D)
            elif esc == 0x0017: out.append(0x1F)
            elif esc == 0x0018: p = vals[i] if i < len(vals) else 0; i += 1; out.extend([0x1E, p & 0xFF])
            elif esc == 0x0019: out.append(0x1A)
            elif esc == 0x001A: i += 2; out.extend([0x01, 0x1B])
            elif esc == 0x001B: i += 3; out.append(0x1C)
            elif esc == 0x001C: out.append(0x01)
            elif esc == 0x001D: p = vals[i] if i < len(vals) else 0; i += 1; out.extend([0x05, 0x40 + (p & 0xFF) if p >= 0x0C00 else 0x40])
            elif esc == 0x001E: pass
            elif esc == 0x0023: i += 1
            elif esc == 0x0024: i += 1  # SHIFT alt drop
            elif esc == 0x0025:
                delay = vals[i] if i < len(vals) else 0; i += 1
                next_tid = vals[i] if i < len(vals) else 0; i += 1
                out.extend([0x0E, delay & 0xFF])
                out.extend([0x07, (next_tid >> 8) & 0xFF, next_tid & 0xFF])
            elif esc in (0x0029, 0x002A, 0x002B): pass
            else: print(f"  WARNING: Unknown ESC+0x{esc:04X} in textId 0x{textId:04X}", file=sys.stderr)
            continue
        elif v == 0x0000: out.append(0x02)
        elif 0x0020 <= v <= 0x007E: out.append(v)
        else:
            if v in char_to_nes:
                code = char_to_nes[v]
                out.extend([(code >> 8) & 0xFF, code & 0xFF])
            elif v in fullwidth_map:
                out.append(fullwidth_map[v])
            else:
                unmapped_chars.append((v, chr(v) if v < 0x10000 else '?'))
                if ord('？') in char_to_nes:
                    code = char_to_nes[ord('？')]
                    out.extend([(code >> 8) & 0xFF, code & 0xFF])
                else:
                    out.append(0x3F)
        i += 1

    if not out or out[-1] != 0x02:
        out.append(0x02)
    return bytes(out), unmapped_chars

# --- Process ---
qm_by_id = {}
for idx in range(num_entries):
    textId, typ, ypos, vals = get_qm_entry(idx)
    if vals:
        qm_by_id[textId] = (typ, ypos, vals)

converted = []
total_unmapped = Counter()
total_unmapped_examples = {}
icon_msg_count = 0
qm_msg_count = 0

for textId in sorted(ntsc_by_id.keys()):
    ntsc = ntsc_by_id[textId]

    if textId in xlsx_translations:
        # Use xlsx translation (139 icon messages)
        text = xlsx_translations[textId]
        if textId in qm_by_id:
            typ, ypos, _ = qm_by_id[textId]
        else:
            typ = ntsc['textboxType']
            ypos = ntsc['textboxYPos']
        nes_bytes, unmapped = translate_to_nes(textId, text, ntsc['raw_hex'])
        for v, ch in unmapped:
            total_unmapped[v] += 1
            if v not in total_unmapped_examples:
                total_unmapped_examples[v] = (textId, ch)
        converted.append({
            'textId': textId, 'type': typ, 'ypos': ypos,
            'nes_hex': nes_bytes.hex(), 'nes_len': len(nes_bytes),
            'source': 'xlsx_cn'
        })
        icon_msg_count += 1

    elif textId in qm_by_id:
        # Use QM Chinese (1977 non-icon messages)
        typ, ypos, vals = qm_by_id[textId]
        nes_bytes, unmapped = qm_to_nes(textId, vals)
        for v, ch in unmapped:
            total_unmapped[v] += 1
            if v not in total_unmapped_examples:
                total_unmapped_examples[v] = (textId, ch)
        converted.append({
            'textId': textId, 'type': typ, 'ypos': ypos,
            'nes_hex': nes_bytes.hex(), 'nes_len': len(nes_bytes),
            'source': '3ds_cn'
        })
        qm_msg_count += 1

    else:
        # EN fallback
        converted.append({
            'textId': textId, 'type': ntsc['textboxType'], 'ypos': ntsc['textboxYPos'],
            'nes_hex': ntsc['raw_hex'], 'nes_len': ntsc['raw_len'],
            'source': 'ntsc_en'
        })

en_count = sum(1 for c in converted if c['source'] == 'ntsc_en')
print(f"\nConverted {len(converted)} messages:", file=sys.stderr)
print(f"  {icon_msg_count} xlsx (icon messages with buttons)", file=sys.stderr)
print(f"  {qm_msg_count} QM (3DS Chinese)", file=sys.stderr)
print(f"  {en_count} EN fallback", file=sys.stderr)
print(f"Unmapped chars: {len(total_unmapped)} unique, {sum(total_unmapped.values())} total", file=sys.stderr)

if total_unmapped:
    print("\nTop 20 unmapped chars:", file=sys.stderr)
    for v, count in total_unmapped.most_common(20):
        tid, ch = total_unmapped_examples[v]
        print(f"  U+{v:04X} '{ch}' count={count} (first in 0x{tid:04X})", file=sys.stderr)

with open('./tmp/converted_messages_v8.json', 'w', encoding='utf-8') as f:
    json.dump(converted, f)

# Verify key messages
for c in converted:
    if c['textId'] in (0x0010, 0x0030, 0x0083, 0x100D, 0x0336):
        raw = bytes.fromhex(c['nes_hex'])
        print(f"\n0x{c['textId']:04X} ({c['source']}): {' '.join(f'{b:02X}' for b in raw[:60])}", file=sys.stderr)
        # Count icon bytes
        icons = [b for b in raw if b >= 0x96 and b <= 0xAA]
        print(f"  Icon bytes: {[f'0x{b:02X}' for b in icons]}", file=sys.stderr)

print(f"\nSaved to /tmp/converted_messages_v8.json", file=sys.stderr)

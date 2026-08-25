#!/usr/bin/env python3
"""
为包含居中标记（0x007F 0x001E）的 3DS 消息添加 N64 水平偏移（0x06 0x??）。
- 1个半角单位 = 7像素
- 0x0F (Link's name) 占 4 个单位
- 0x1E 0x03~0x06 (高分显示) 占 6 个单位
- 0x0C 被当作换行分隔符，前后文本分为两行，分别计算偏移
- 若消息包含 0x1B (二选一)，则最后 4 行不添加偏移
"""

import struct
import json
import sys

# ---------- QM 解析 ----------
def get_qm_entry(qm_data, idx, entry_size=120):
    off = 16 + idx * entry_size
    textId = struct.unpack('<I', qm_data[off:off+4])[0]
    typ = struct.unpack('<I', qm_data[off+8:off+12])[0]
    ypos = struct.unpack('<I', qm_data[off+12:off+16])[0]
    cn_slot_off = off + 16 + 10 * 8
    cn_data_off = struct.unpack('<I', qm_data[cn_slot_off:cn_slot_off+4])[0]
    cn_data_size = struct.unpack('<I', qm_data[cn_slot_off+4:cn_slot_off+8])[0]
    vals = []
    if cn_data_off > 0 and cn_data_size > 0 and cn_data_off + cn_data_size <= len(qm_data):
        for i in range(0, cn_data_size, 2):
            v = struct.unpack('<H', qm_data[cn_data_off+i:cn_data_off+i+2])[0]
            vals.append(v)
    return textId, typ, ypos, vals

def has_center_marker(vals):
    for i in range(len(vals)-1):
        if vals[i] == 0x007F and vals[i+1] == 0x001E:
            return True
    return False

# ---------- NES 字节解析与重建 ----------
def get_ctrl_param_len(b):
    if b in (0x05, 0x06, 0x0E, 0x13, 0x14, 0x1E):
        return 1
    elif b in (0x07, 0x11, 0x12):
        return 2
    elif b == 0x15:
        return 3
    else:
        return 0

def parse_nes_tokens(raw):
    """解析 NES 字节，返回 token 列表。分隔符包括 0x01, 0x04, 0x0C。"""
    tokens = []
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0x02:
            break
        # 分隔符（换行、换框、延迟换行）
        if b in (0x01, 0x04):
            tokens.append({'type': 'sep', 'byte': b, 'bytes': bytes([b])})
            i += 1
            continue
        if b == 0x0C:          # 带参数的延迟换行
            if i+1 < len(raw):
                param = raw[i+1]
                tokens.append({'type': 'sep', 'byte': b, 'bytes': bytes([b, param])})
                i += 2
                continue
            else:
                i += 1
                continue
        if b == 0x0F:          # Link's name，占 4 个半角单位
            tokens.append({'type': 'text', 'bytes': bytes([b]), 'width': 4})
            i += 1
            continue
        if b == 0x1E and i+1 < len(raw):
            param = raw[i+1]
            if param >= 0x03 and param <= 0x06:
                tokens.append({'type': 'text', 'bytes': bytes([b, param]), 'width': 6})
                i += 2
                continue
        if b < 0x20:
            if b == 0x06:      # 移除旧偏移
                i += 2
                continue
            param_len = get_ctrl_param_len(b)
            tokens.append({'type': 'ctrl', 'bytes': raw[i:i+1+param_len]})
            i += 1 + param_len
        elif b >= 0xA0:        # 双字节中文/图标
            if i+1 < len(raw):
                tokens.append({'type': 'text', 'bytes': raw[i:i+2], 'width': 2})
                i += 2
            else:
                i += 1
        else:                  # ASCII
            tokens.append({'type': 'text', 'bytes': bytes([b]), 'width': 1})
            i += 1
    return tokens

def split_boxes_lines(tokens):
    """将 token 列表按 0x04 (换框) 和 0x01 (换行) 分割，保留空行。"""
    boxes = []
    current_box = []
    current_line = []
    for tok in tokens:
        if tok['type'] == 'sep' and tok['byte'] == 0x04:
            # 结束当前行和当前框
            current_box.append(current_line)
            current_line = []
            boxes.append(current_box)
            current_box = []
        elif tok['type'] == 'sep' and tok['byte'] == 0x01:
            # 结束当前行（保留空行）
            current_box.append(current_line)
            current_line = []
        else:
            current_line.append(tok)
    # 处理最后一行和最后一个框
    current_box.append(current_line)
    if current_box:
        boxes.append(current_box)
    return boxes

def has_control_1b(raw_bytes):
    """检测是否存在独立的 0x1B 控制符（忽略双字节字符中的低字节）。"""
    i = 0
    while i < len(raw_bytes):
        b = raw_bytes[i]
        if b >= 0xA0 and i + 1 < len(raw_bytes):
            i += 2
            continue
        if b == 0x1B:
            return True
        i += 1
    return False

def count_total_lines(tokens):
    """统计所有框的行数总和（0x01, 0x0C, 0x04 均结束当前行）"""
    lines = 0
    in_line = False
    for tok in tokens:
        if tok['type'] == 'sep':
            # 遇到分隔符，结束当前行，下一行开始
            if in_line:
                lines += 1
                in_line = False
            # 如果是换框，新框的第一行还未开始，但行计数不变
            continue
        else:
            # 非分隔符，表示当前行有内容
            in_line = True
    # 如果最后一行有内容，也要计数
    if in_line:
        lines += 1
    return lines

def rebuild_with_center(raw_bytes):
    tokens = parse_nes_tokens(raw_bytes)
    has_choice = has_control_1b(raw_bytes)
    
    # ---- 统计总行数（用于跳过最后4行） ----
    total_lines = 0
    in_line = False
    for tok in tokens:
        if tok['type'] == 'sep':
            if tok['byte'] == 0x04:
                # 换框：结束当前行，但新框开始
                if in_line:
                    total_lines += 1
                    in_line = False
            else:  # 0x01 或 0x0C
                if in_line:
                    total_lines += 1
                    in_line = False
        else:
            in_line = True
    if in_line:
        total_lines += 1

    skip_last = 4 if has_choice else 0

    # ---- 构建新字节 ----
    new_bytes = bytearray()
    current_line = []
    line_counter = 0

    def flush_line():
        nonlocal line_counter
        if line_counter < total_lines - skip_last:
            width_units = sum(tok['width'] for tok in current_line if tok['type'] == 'text')
            offset = -11 + ((32 - width_units) * 7) // 2
            if offset < 0:
                offset = 0
            new_bytes.append(0x06)
            new_bytes.append(offset & 0xFF)
        for tok in current_line:
            new_bytes.extend(tok['bytes'])
        current_line.clear()
        line_counter += 1

    for tok in tokens:
        if tok['type'] == 'sep':
            if tok['byte'] == 0x04:
                # 换框：结束当前行，输出 0x04，重置框
                flush_line()
                new_bytes.append(0x04)
            else:  # 0x01 或 0x0C
                # 结束当前行，输出分隔符
                flush_line()
                new_bytes.extend(tok['bytes'])
        else:
            current_line.append(tok)

    if current_line:
        flush_line()

    new_bytes.append(0x02)
    return bytes(new_bytes)

# ---------- 主流程 ----------
def main():
    with open('./tmp/oot3d_cn.qm', 'rb') as f:
        qm = f.read()
    num_entries = struct.unpack('<I', qm[8:12])[0]
    qm_by_id = {}
    for idx in range(num_entries):
        textId, typ, ypos, vals = get_qm_entry(qm, idx)
        if vals:
            qm_by_id[textId] = vals
    print(f"Loaded {len(qm_by_id)} entries from QM", file=sys.stderr)

    with open('./tmp/converted_messages_v8.json', 'r', encoding='utf-8') as f:
        converted = json.load(f)

    new_converted = []
    for entry in converted:
        textId = entry['textId']
        source = entry['source']
        if source in ('3ds_cn', 'xlsx_cn') and textId in qm_by_id:
            vals = qm_by_id[textId]
            if has_center_marker(vals):
                raw_hex = entry['nes_hex']
                raw_bytes = bytes.fromhex(raw_hex)
                new_bytes = rebuild_with_center(raw_bytes)
                entry['nes_hex'] = new_bytes.hex()
                entry['nes_len'] = len(new_bytes)
                entry['center_applied'] = True
        new_converted.append(entry)

    out_path = './tmp/converted_messages_with_center.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(new_converted, f, indent=2)
    print(f"Saved {len(new_converted)} messages to {out_path}", file=sys.stderr)

if __name__ == '__main__':
    main()
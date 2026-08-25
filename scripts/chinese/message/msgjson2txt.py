#!/usr/bin/env python3
"""
将 project1 的 converted_messages_v8.json 转换为 project2 的 message_raw_cn_from_ique.txt
同时将 单字节图标 (0x9F-0xAA) 映射为 双字节图标 (0xAA9F-0xAAAB)
"""

import json
import sys
from pathlib import Path

# 项目1 单字节图标 → 项目2 双字节图标映射
# 注意：项目1的 [C上] 对应项目2的 (↑)，以此类推
ICON_REMAP = {
    0x9F: 0xAAA5,  # [C上] -> (↑)
    0xA0: 0xAAA6,  # [C下] -> (↓)
    0xA1: 0xAAA7,  # [C左] -> (←)
    0xA2: 0xAAA8,  # [C右] -> (→)
    0xA3: 0xAAA3,  # [R]   -> (R)
    0xA4: 0xAAA4,  # [Z]   -> (Z)
    0xA5: 0xAAAA,  # [摇杆] -> (+)
    0xA6: 0xAAAB,  # [D-Pad] -> (+) 
    0xA7: 0xAAA0,  # [B]   -> (B)
    0xA8: 0xAAA4,  # [Z钮] -> (Z)
    0xA9: 0xAAA3,  # [R钮] -> (R)
    0xAA: 0xAAA2,  # [L钮] -> (L)
}

def remap_icon_bytes(data: bytes) -> bytes:
    """安全地转换字节流，仅替换独立的单字节图标，不碰触 CJK 双字节序列。"""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        # 如果 >= 0xA0，视为 CJK 双字节字符的高字节，整体保留（不拆解）
        if b >= 0xA0:
            if i + 1 < n:
                # 双字节序列，原样复制（即使低字节恰好是 0x9F~0xAA，也绝对不替换）
                out.append(b)
                out.append(data[i+1])
                i += 2
            else:
                out.append(b)
                i += 1
        # 如果落在单字节图标区，且不是某个 CJK 字符的低字节（上面已过滤），则替换
        #elif 0x9F <= b <= 0xAA:
            #new_code = ICON_REMAP[b]
            #out.append((new_code >> 8) & 0xFF)   # 高字节，如 0xAA
            #out.append(new_code & 0xFF)          # 低字节，如 0xA5
            #i += 1
        else:
            # 普通控制码或 ASCII，保持不变
            out.append(b)
            i += 1
    return bytes(out)

def convert(input_json, output_txt):
    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    lines = []
    for item in data:
        text_id = item['textId']
        hex_str = item['nes_hex']  # 例如 "9f01a0..."
        
        # 将 hex 字符串转为字节对象
        raw_bytes = bytes.fromhex(hex_str)
        # 执行图标重映射
        remapped = remap_icon_bytes(raw_bytes)
        # 转回 hex 大写字符串
        new_hex = remapped.hex().upper()
        
        bytes_list = [f"0x{new_hex[i:i+2]}" for i in range(0, len(new_hex), 2)]
        line = f"0x{text_id:04X} = {{ {', '.join(bytes_list)} }};"
        lines.append(line)
    
    with open(output_txt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ 已写入 {len(lines)} 条消息到 {output_txt}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("用法: python bridge_v8_to_ique.py <converted_messages_v8.json> <输出.txt>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
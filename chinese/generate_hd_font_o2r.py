#!/usr/bin/env python3
"""Generate chinese_font_hd.o2r — HD texture mod for custom Chinese font glyphs.

Creates an .o2r mod file with 128×128 RGBA32 HD versions of the 1030 custom
Chinese characters, using the same binary format as OoT Reloaded HD pack:
- Paths: alt/textures/chinese_font/gMsgCharChnXXXXTex
- Binary format: OTR V1 with HByteScale/VPixelScale scale factors
- Image data: RGBA32 (128×128×4 = 65536 bytes per character)
- Flags: TEX_FLAG_LOAD_AS_RAW

The remaining 1131 characters reuse kanji OTR paths and are already covered
by OoT Reloaded's HD kanji textures.

Usage:
    pip install Pillow
    python generate_hd_font_o2r.py [--font FONT_PATH] [--output OUTPUT_PATH]

The generated .o2r file should be placed in the Switch SD card at:
    switch/soh/mods/chinese_font_hd.o2r

Requires Source Han Sans SC (思源黑体) or similar Chinese font.
Download: https://github.com/adobe-fonts/source-han-sans/releases
"""

import argparse
import os
import re
import struct
import sys
import zipfile
from PIL import Image, ImageDraw, ImageFont

# Paths relative to this script (tools/chinese/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
TBL_PATH = os.path.join(REPO_ROOT, 'soh', 'src', 'code', 'z_kanfont_chinese_tbl.inc')

# OTR binary format constants
OTR_HEADER_SIZE = 0x40
RESOURCE_TYPE_TEXTURE = 0x4F544558  # "OTEX" in little-endian
TEXTURE_TYPE_GRAYSCALE_4BPP = 5     # I4 = original format identifier
TEX_FLAG_LOAD_AS_RAW = 1

# HD texture parameters
HD_SIZE = 128
RENDER_SIZE = 256  # 2x supersampling for sharper strokes
FONT_SIZE = 216    # ~108pt × 2 for the 2x canvas
GLYPH_COLOR = (210, 210, 210, 255)  # gray210 to match OoT Reloaded HD kanji style

# Characters that need substitution (font lacks correct glyph)
CHAR_SUBSTITUTIONS = {
    '⋯': '…',  # U+22EF → U+2026 (Source Han Sans renders ⋯ as X placeholder)
}

# Scale factors: original 16×16 I4 → HD 128×128 RGBA32
# HByteScale = HD_bytes_per_row / orig_bytes_per_row = (128*4) / (16*0.5) = 64.0
# VPixelScale = HD_height / orig_height = 128/16 = 8.0
H_BYTE_SCALE = 64.0
V_PIXEL_SCALE = 8.0


def parse_custom_entries(tbl_path):
    """Parse z_kanfont_chinese_tbl.inc to find custom chinese_font entries."""
    with open(tbl_path, 'r') as f:
        content = f.read()

    entries = []
    pattern = r"^\s+(gMsgCharChn\w+Tex),\s*//\s*\[\d+\]\s+0x[0-9A-Fa-f]+\s+'(.)'"
    for line in content.split('\n'):
        m = re.match(pattern, line)
        if m:
            entries.append((m.group(1), m.group(2)))
    return entries


def generate_rgba_image(char, font, size):
    """Generate an RGBA image for a character using 2x supersampling + LANCZOS downscale.

    Renders at 2x resolution (256×256) then downscales to target size (128×128)
    using LANCZOS resampling. This produces much sharper strokes than direct
    rendering at the target resolution, because strokes are more likely to align
    with pixel boundaries at the higher resolution.
    """
    # Apply character substitution if needed
    char = CHAR_SUBSTITUTIONS.get(char, char)

    # Render at 2x resolution
    img = Image.new('RGBA', (RENDER_SIZE, RENDER_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox = font.getbbox(char)
    char_w = bbox[2] - bbox[0]
    char_h = bbox[3] - bbox[1]

    x = (RENDER_SIZE - char_w) // 2 - bbox[0]
    y = (RENDER_SIZE - char_h) // 2 - bbox[1]

    draw.text((x, y), char, fill=GLYPH_COLOR, font=font)

    # Downscale to target size with LANCZOS for sharp edges
    img = img.resize((size, size), Image.LANCZOS)
    return img.tobytes('raw', 'RGBA')


def build_otr_resource(rgba_data):
    """Build a complete OTR binary resource (header + V1 texture data)."""
    buf = bytearray()

    # OTR Header (64 bytes)
    buf += struct.pack('<B', 0)       # Endianness = Little
    buf += struct.pack('<B', 0)       # IsCustom
    buf += struct.pack('<BB', 0, 0)   # unused
    buf += struct.pack('<I', RESOURCE_TYPE_TEXTURE)
    buf += struct.pack('<I', 1)       # ResourceVersion = 1 (V1)
    buf += struct.pack('<Q', 0xDEADBEEFDEADBEEF)
    while len(buf) < OTR_HEADER_SIZE:
        buf += struct.pack('<I', 0)

    # V1 Texture Data
    buf += struct.pack('<I', TEXTURE_TYPE_GRAYSCALE_4BPP)
    buf += struct.pack('<I', HD_SIZE)
    buf += struct.pack('<I', HD_SIZE)
    buf += struct.pack('<I', TEX_FLAG_LOAD_AS_RAW)
    buf += struct.pack('<f', H_BYTE_SCALE)
    buf += struct.pack('<f', V_PIXEL_SCALE)
    buf += struct.pack('<I', len(rgba_data))
    buf += rgba_data

    return bytes(buf)


def main():
    parser = argparse.ArgumentParser(description='Generate HD Chinese font .o2r mod')
    parser.add_argument('--font', default=None,
                        help='Path to Chinese font file (e.g., SourceHanSansSC-Regular.otf)')
    parser.add_argument('--output', default=os.path.join(REPO_ROOT, 'chinese_font_hd.o2r'),
                        help='Output .o2r file path')
    args = parser.parse_args()

    if args.font is None:
        print("Error: --font is required. Provide a Chinese font file path.")
        print("  e.g., python generate_hd_font_o2r.py --font SourceHanSansSC-Regular.otf")
        print("  Download: https://github.com/adobe-fonts/source-han-sans/releases")
        sys.exit(1)

    if not os.path.exists(args.font):
        print(f"Error: Font file not found: {args.font}")
        sys.exit(1)

    if not os.path.exists(TBL_PATH):
        print(f"Error: Table file not found: {TBL_PATH}")
        sys.exit(1)

    entries = parse_custom_entries(TBL_PATH)
    print(f"Found {len(entries)} custom chinese_font entries")

    font = ImageFont.truetype(args.font, FONT_SIZE)
    print(f"Generating {HD_SIZE}×{HD_SIZE} RGBA32 HD textures...")

    with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('portVersion', '9.1.2')

        for i, (tex_name, char) in enumerate(entries):
            rgba_data = generate_rgba_image(char, font, HD_SIZE)
            otr_data = build_otr_resource(rgba_data)
            zf.writestr(f"alt/textures/chinese_font/{tex_name}", otr_data)

            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(entries)}...")

    size_mb = os.path.getsize(args.output) / 1024 / 1024
    print(f"Done: {args.output} ({size_mb:.1f} MB, {len(entries)} textures)")
    print(f"Place in: switch/soh/mods/chinese_font_hd.o2r")


if __name__ == "__main__":
    main()

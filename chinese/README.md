# Chinese Language Tools

Tools for generating Simplified Chinese message data and font glyphs for SoH.

## Files

| File | Description |
|------|-------------|
| `qm_to_nes_v8.py` | Converts 3DS QM Chinese text + xlsx translations → NES message format |
| `generate_font_glyphs.py` | Renders CJK characters from TTF font → I4 glyph data (16×16, 4bpp) |
| `charmap_chn.txt` | Character mapping table: Unicode → iQue 2-byte code (2193 entries) |
| `charmap_chn_extra.txt` | Extended character mappings (391 additional CJK characters) |
| `icon_messages_139_translation.xlsx` | Hand-translated messages containing button icon tags |

## Usage

### 1. Generate message data

```bash
# Edit paths in qm_to_nes_v8.py, then:
python qm_to_nes_v8.py
# Output: converted_messages_v8.json → transform to z_message_CHI.cpp
```

### 2. Generate font glyphs

```bash
pip install Pillow
python generate_font_glyphs.py \
  --font /path/to/CJKFont.ttf \
  --charmap charmap_chn.txt \
  --output-dir ./output/
# Output: z_kanfont_chinese_data.c
```

### 3. Copy generated files

```bash
cp z_message_CHI.cpp ../../soh/soh/
cp z_kanfont_chinese_data.c ../../soh/src/code/
```

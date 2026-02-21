import os

with open('senna_ai/ui/main_window.py', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Find insertion point
insert_line = -1
for i, line in enumerate(lines):
    if 'self._cards[key] = val_lbl' in line:
        # Look ahead for sector analysis
        for j in range(i+1, min(i+10, len(lines))):
            if 'SECTOR ANALYSIS' in lines[j]:
                insert_line = j - 1  # Insert before the sector header line
                break
        if insert_line != -1:
            break

if insert_line != -1:
    print(f'Found insertion point at line {insert_line}')
    
    # Insert track map code
    track_map_lines = [
        '\n',
        '        # Track Map Overlay (minimal 2D validation)\n',
        '        track_map_header = ttk.Frame(main, style="Dark.TFrame")\n',
        '        track_map_header.pack(fill="x", pady=(8, 2))\n',
        '        ttk.Label(track_map_header, text="TRACK MAP",\n',
        '                  font=("Segoe UI", 10, "bold"),\n',
        '                  foreground="#e94560", background="#1a1a2e").pack(side="left")\n',
        '        \n',
        '        # Track map canvas\n',
        '        self.track_map_canvas = tk.Canvas(\n',
        '            main, width=400, height=400,\n',
        '            bg="#0a0a1a", highlightthickness=0\n',
        '        )\n',
        '        self.track_map_canvas.pack(pady=(0, 8))\n',
        '        \n',
        '        # Track map state\n',
        '        self.track_map_bounds = None\n',
        '        self.track_map_initialized = False\n',
        '\n',
    ]
    
    # Insert the lines
    lines[insert_line:insert_line] = track_map_lines
    
    with open('senna_ai/ui/main_window.py', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print('Track map added successfully')
else:
    print('Could not find insertion point')

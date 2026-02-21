import os

with open('senna_ai/ui/main_window.py', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Find where to insert track map drawing logic
# Look for the composite target time section
insert_line = -1
for i, line in enumerate(lines):
    if 'self._cards["target"].config(text="�")' in line or 'self._cards["target"].config(text="—")' in line:
        # Insert after this line
        insert_line = i + 1
        break

if insert_line != -1:
    print(f'Found insertion point at line {insert_line}')
    
    # Insert track map drawing logic
    track_map_drawing = [
        '\n',
        '        # ── Track Map Drawing ──\n',
        '        if self.track_map_canvas and eng.reference_line:\n',
        '            # Initialize bounds if needed\n',
        '            if not self.track_map_initialized and eng.reference_line:\n',
        '                # Calculate bounds from reference line\n',
        '                xs = [p[0] for p in eng.reference_line]\n',
        '                ys = [p[1] for p in eng.reference_line]\n',
        '                if xs and ys:\n',
        '                    min_x, max_x = min(xs), max(xs)\n',
        '                    min_y, max_y = min(ys), max(ys)\n',
        '                    # Add 10% margin\n',
        '                    margin_x = (max_x - min_x) * 0.1\n',
        '                    margin_y = (max_y - min_y) * 0.1\n',
        '                    self.track_map_bounds = (\n',
        '                        min_x - margin_x, max_x + margin_x,\n',
        '                        min_y - margin_y, max_y + margin_y\n',
        '                    )\n',
        '                    self.track_map_initialized = True\n',
        '                    print(f"Track map bounds: {self.track_map_bounds}")\n',
        '            \n',
        '            # Clear canvas\n',
        '            self.track_map_canvas.delete("all")\n',
        '            \n',
        '            # Draw reference line (grey)\n',
        '            if eng.reference_line and self.track_map_bounds:\n',
        '                min_x, max_x, min_y, max_y = self.track_map_bounds\n',
        '                points = []\n',
        '                for x, y in eng.reference_line:\n',
        '                    x_norm = (x - min_x) / (max_x - min_x)\n',
        '                    y_norm = (y - min_y) / (max_y - min_y)\n',
        '                    x_canvas = 10 + x_norm * 380\n',
        '                    y_canvas = 10 + (1 - y_norm) * 380  # Flip Y so forward is up\n',
        '                    points.extend([x_canvas, y_canvas])\n',
        '                if len(points) >= 4:\n',
        '                    self.track_map_canvas.create_line(\n',
        '                        *points, fill="#666666", width=2, smooth=True\n',
        '                    )\n',
        '            \n',
        '            # Draw player trace (blue)\n',
        '            if hasattr(eng, "_all_points") and eng._all_points and self.track_map_bounds:\n',
        '                min_x, max_x, min_y, max_y = self.track_map_bounds\n',
        '                points = []\n',
        '                # Take last 100 points\n',
        '                for x, y in list(eng._all_points)[-100:]:\n',
        '                    x_norm = (x - min_x) / (max_x - min_x)\n',
        '                    y_norm = (y - min_y) / (max_y - min_y)\n',
        '                    x_canvas = 10 + x_norm * 380\n',
        '                    y_canvas = 10 + (1 - y_norm) * 380\n',
        '                    points.extend([x_canvas, y_canvas])\n',
        '                if len(points) >= 4:\n',
        '                    self.track_map_canvas.create_line(\n',
        '                        *points, fill="#4fc3f7", width=1.5, smooth=True\n',
        '                    )\n',
        '            \n',
        '            # Draw current position (red dot)\n',
        '            if eng.live_x is not None and eng.live_z is not None and self.track_map_bounds:\n',
        '                min_x, max_x, min_y, max_y = self.track_map_bounds\n',
        '                x_norm = (eng.live_x - min_x) / (max_x - min_x)\n',
        '                y_norm = (eng.live_z - min_y) / (max_y - min_y)\n',
        '                x_canvas = 10 + x_norm * 380\n',
        '                y_canvas = 10 + (1 - y_norm) * 380\n',
        '                self.track_map_canvas.create_oval(\n',
        '                    x_canvas - 4, y_canvas - 4,\n',
        '                    x_canvas + 4, y_canvas + 4,\n',
        '                    fill="#e94560", outline="white", width=1\n',
        '                )\n',
        '\n',
    ]
    
    # Insert the lines
    lines[insert_line:insert_line] = track_map_drawing
    
    with open('senna_ai/ui/main_window.py', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print('Track map drawing logic added successfully')
else:
    print('Could not find insertion point')
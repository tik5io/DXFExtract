#gcode_visualizer.py
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import Arc
import tkinter as tk
import re
import math
import logging

logging.basicConfig(level=logging.INFO, format='[GCODE_VIS_APP] %(message)s')

class GcodeVisualizer:
    """
    A Matplotlib-based G-code visualizer embedded in a Tkinter frame.
    It can parse G-code, draw tool paths, and highlight specific segments
    based on DXF entity IDs or block types.
    """
    def __init__(self, master_frame):
        self.master_frame = master_frame
        self.gcode_lines = [] # Stores parsed G-code segments data for drawing
        self.dxf_id_map = {} # Maps G-code line index (from AppGUI) to DXF ID
        self.block_colors = {} # Colors for block highlighting (e.g., 'ORDERED_TRAJECTORY': 'blue')

        self.figure, self.ax = plt.subplots(figsize=(8, 6)) # Create a Matplotlib figure and axes
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.master_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, self.master_frame)
        self.toolbar.update()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.drawn_objects = [] # Stores matplotlib line/patch objects for easy clearing/updating
        self.highlighted_objects = [] # Stores currently highlighted objects

        self._configure_plot()

        logging.info("[GCODE_VIS_APP] GcodeVisualizer initialized.")

    def _configure_plot(self):
        """Configures initial plot settings."""
        self.ax.set_xlabel("X-axis")
        self.ax.set_ylabel("Y-axis")
        self.ax.set_title("G-code Tool Path Visualization")
        self.ax.set_aspect('equal', adjustable='box') # Maintain aspect ratio
        self.ax.grid(True) # Add grid for better orientation

    def update_gcode(self, gcode_string, dxf_id_map, block_colors):
        """
        Updates the visualizer with new G-code and DXF mapping.
        Parses the G-code, clears previous drawing, and draws the new path.

        Args:
            gcode_string (str): The complete G-code program string.
            dxf_id_map (dict): Mapping from G-code line number to DXF entity ID.
            block_colors (dict): Dictionary defining colors for different blocks.
        """
        logging.info("[GCODE_VIS_APP] Updating G-code visualizer...")
        self.dxf_id_map = dxf_id_map
        self.block_colors = block_colors
        self._parse_gcode(gcode_string)
        self._draw_gcode()
        self.canvas.draw_idle() # Redraw the canvas after updates
        logging.info("[GCODE_VIS_APP] G-code visualizer updated.")

    def _parse_gcode(self, gcode_string):
        """
        Parses the G-code string into a list of geometric segments (lines/arcs).
        Each segment includes its type, coordinates, and the G-code line index.
        """
        self.gcode_lines = []
        current_x, current_y = 0.0, 0.0 # Initialize current position

        lines = gcode_string.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            # Regular expressions to find G-code commands and coordinates
            # X, Y for absolute coordinates
            # I, J for relative arc center offsets
            g00_g01_match = re.search(r'(G00|G01)\s*(?:X([+\-]?\d*\.?\d+))?\s*(?:Y([+\-]?\d*\.?\d+))?', line)
            g02_g03_match = re.search(r'(G02|G03)\s*(?:X([+\-]?\d*\.?\d+))?\s*(?:Y([+\-]?\d*\.?\d+))?\s*(?:I([+\-]?\d*\.?\d+))?\s*(?:J([+\-]?\d*\.?\d+))?', line)

            parsed_segment = None

            if g00_g01_match:
                cmd = g00_g01_match.group(1)
                new_x = float(g00_g01_match.group(2)) if g00_g01_match.group(2) else current_x
                new_y = float(g00_g01_match.group(3)) if g00_g01_match.group(3) else current_y
                
                # Only add if movement occurred or if it's the very first movement
                if (new_x != current_x or new_y != current_y) or (not self.gcode_lines and cmd == "G00"):
                    parsed_segment = {
                        'type': 'LINE',
                        'cmd': cmd,
                        'start_x': current_x,
                        'start_y': current_y,
                        'end_x': new_x,
                        'end_y': new_y,
                        'gcode_line_idx': i
                    }
                    current_x, current_y = new_x, new_y

            elif g02_g03_match:
                cmd = g02_g03_match.group(1)
                end_x = float(g02_g03_match.group(2)) if g02_g03_match.group(2) else current_x
                end_y = float(g02_g03_match.group(3)) if g02_g03_match.group(3) else current_y
                i_offset = float(g02_g03_match.group(4)) if g02_g03_match.group(4) else 0.0
                j_offset = float(g02_g03_match.group(5)) if g02_g03_match.group(5) else 0.0

                center_x = current_x + i_offset
                center_y = current_y + j_offset
                radius = math.hypot(i_offset, j_offset)

                if radius > 1e-6: # Avoid arcs with zero radius
                    # Calculate start and end angles for the arc
                    start_angle = math.degrees(math.atan2(current_y - center_y, current_x - center_x))
                    end_angle = math.degrees(math.atan2(end_y - center_y, end_y - center_x)) # Fix: math.atan2(end_y - center_y, end_x - center_x)

                    is_full_circle = math.isclose(current_x, end_x, abs_tol=1e-6) and \
                                     math.isclose(current_y, end_y, abs_tol=1e-6) and \
                                     math.isclose(radius, math.hypot(current_x - center_x, current_y - center_y), abs_tol=1e-6)

                    parsed_segment = {
                        'type': 'ARC',
                        'cmd': cmd,
                        'start_x': current_x,
                        'start_y': current_y,
                        'end_x': end_x,
                        'end_y': end_y,
                        'center_x': center_x,
                        'center_y': center_y,
                        'radius': radius,
                        'start_angle': start_angle,
                        'end_angle': end_angle,
                        'is_clockwise': (cmd == "G02"),
                        'is_full_circle': is_full_circle,
                        'gcode_line_idx': i
                    }
                    current_x, current_y = end_x, end_y
                else:
                    logging.warning(f"Skipping arc on line {i} due to near-zero radius: {line}")
                    # If radius is too small, treat as a point move
                    parsed_segment = {
                        'type': 'LINE', # Treat as a point move
                        'cmd': 'G00',
                        'start_x': current_x,
                        'start_y': current_y,
                        'end_x': end_x,
                        'end_y': end_y,
                        'gcode_line_idx': i
                    }
                    current_x, current_y = end_x, end_y


            if parsed_segment:
                self.gcode_lines.append(parsed_segment)

        logging.info(f"[GCODE_VIS_APP] Parsed {len(self.gcode_lines)} G-code segments.")


    def _draw_gcode(self):
        """Clears the plot and redraws all G-code segments."""
        self.ax.clear()
        self._configure_plot() # Re-apply plot settings
        self.drawn_objects = [] # Reset drawn objects list

        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')
        
        # Determine default line properties for non-highlighted segments
        default_color = 'gray'
        default_linewidth = 1.0

        for segment in self.gcode_lines:
            line_obj = None
            if segment['type'] == 'LINE':
                # Draw lines (G00, G01)
                line_obj, = self.ax.plot([segment['start_x'], segment['end_x']],
                                         [segment['start_y'], segment['end_y']],
                                         color=default_color, linewidth=default_linewidth,
                                         picker=True) # Enable picking for potential future use
            elif segment['type'] == 'ARC':
                cx, cy = segment['center_x'], segment['center_y']
                sx, sy = segment['start_x'], segment['start_y']
                ex, ey = segment['end_x'], segment['end_y']
                is_cw = segment['is_clockwise']

                if segment['is_full_circle']:
                    theta1 = 0
                    theta2 = -360 if is_cw else 360
                else:
                    theta1, theta2 = self.compute_arc_angles(cx, cy, sx, sy, ex, ey, is_cw)

                arc_patch = Arc(
                    (cx, cy),
                    2 * segment['radius'],
                    2 * segment['radius'],
                    angle=0,
                    theta1=theta1,
                    theta2=theta2,
                    color=default_color,
                    linewidth=default_linewidth,
                    picker=True
                )
                self.ax.add_patch(arc_patch)
                line_obj = arc_patch

            # Add the segment to the drawn objects list        
            if line_obj:
                line_obj.set_zorder(1) # Ensure default lines are behind highlights
                self.drawn_objects.append(line_obj)

            # Update plot limits
            min_x = min(min_x, segment['start_x'], segment['end_x'])
            max_x = max(max_x, segment['start_x'], segment['end_x'])
            min_y = min(min_y, segment['start_y'], segment['end_y'])
            max_y = max(max_y, segment['start_y'], segment['end_y'])

        # Set tight limits and add a small padding
        if self.gcode_lines:
            padding_x = (max_x - min_x) * 0.1 if (max_x - min_x) > 0 else 1.0
            padding_y = (max_y - min_y) * 0.1 if (max_y - min_y) > 0 else 1.0
            self.ax.set_xlim(min_x - padding_x, max_x + padding_x)
            self.ax.set_ylim(min_y - padding_y, max_y + padding_y)
        else:
            self.ax.set_xlim(-10, 10) # Default if no lines
            self.ax.set_ylim(-10, 10)

        self.canvas.draw_idle()
        logging.info("[GCODE_VIS_APP] G-code path drawn.")

    def compute_arc_angles(self,cx, cy, sx, sy, ex, ey, is_cw):
        def angle_from_center(x, y):
            return math.degrees(math.atan2(y - cy, x - cx)) % 360

        start_angle = angle_from_center(sx, sy)
        end_angle = angle_from_center(ex, ey)

        if is_cw:
            # Invert angles for CW motion since Matplotlib draws CCW
            theta1 = end_angle
            theta2 = start_angle
            if theta2 > theta1:
                theta2 -= 360  # Ensure CW sweep
        else:
            theta1 = start_angle
            theta2 = end_angle
            if theta2 < theta1:
                theta2 += 360  # Ensure CCW sweep

        return theta1, theta2

    def highlight_gcode_line(self, highlight_id=None):
        """
        Highlights specific G-code segments on the plot.

        Args:
            highlight_id (str or None): The ID to highlight. Can be a DXF ID (e.g., 'L1', 'A5', 'C2'),
                                        a block ID ('ORDERED_TRAJECTORY', 'ISOLATED_CIRCLES'),
                                        or None to clear highlights.
        """
        logging.info(f"[GCODE_VIS_APP] Handling highlight for: {highlight_id}")

        # Clear existing highlights
        for obj in self.highlighted_objects:
            if isinstance(obj, plt.Line2D):
                obj.set_color('gray')
                obj.set_linewidth(1.0)
                obj.set_zorder(1)
            elif isinstance(obj, Arc):
                obj.set_edgecolor('gray')
                obj.set_linewidth(1.0)
                obj.set_zorder(1)
        self.highlighted_objects = []

        if highlight_id is None:
            self.canvas.draw_idle()
            logging.info("[GCODE_VIS_APP] Highlight cleared.")
            return

        # PATCH: Accepte une liste d'IDs ou un seul ID
        if isinstance(highlight_id, list):
            highlight_ids = set(highlight_id)
        else:
            highlight_ids = {highlight_id}

        highlight_color = self.block_colors.get("HIGHLIGHT", 'orange')

        # Surligne tous les segments dont le dxf_id_map est dans highlight_ids
        for i, segment in enumerate(self.gcode_lines):
            associated_dxf_id = self.dxf_id_map.get(segment['gcode_line_idx'])
            if associated_dxf_id in highlight_ids:
                if i < len(self.drawn_objects):
                    obj = self.drawn_objects[i]
                    if isinstance(obj, plt.Line2D):
                        obj.set_color(highlight_color)
                        obj.set_linewidth(2.5)
                        obj.set_zorder(2)
                    elif isinstance(obj, Arc):
                        obj.set_edgecolor(highlight_color)
                        obj.set_linewidth(2.5)
                        obj.set_zorder(2)
                    self.highlighted_objects.append(obj)

        self.canvas.draw_idle() # Redraw the canvas to show highlights

# Example usage (for testing this module independently if needed)
if __name__ == '__main__':
    root = tk.Tk()
    root.title("G-code Visualizer Test")
    root.geometry("800x600")

    visualizer_frame = tk.Frame(root, borderwidth=2, relief="groove")
    visualizer_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

    gcode_vis = GcodeVisualizer(visualizer_frame)

    # Example G-code for testing
    test_gcode = """
N0 G90 G21 G17 G40 G49 G80
N10 G00 X0.0000 Y0.0000
N20 G01 X10.0000 Y0.0000 ; LINE DXF ID: L1
N30 G01 X10.0000 Y10.0000 ; LINE DXF ID: L2
N40 G03 X0.0000 Y10.0000 I-5.0000 J0.0000 ; ARC DXF ID: A3 (full half circle)
N50 G00 X0.0000 Y0.0000 ; Jump to DXF ID: JUMP_TO_DXF_L1
N60 ; Start of DXF Isolated Circles
N70 G00 X15.0000 Y5.0000 ; Jump to CIRCLE DXF ID: C4
N80 G03 X15.0000 Y5.0000 I0.0000 J-5.0000 ; Full CIRCLE DXF ID: C4
N90 M02 ; Program End
"""
    # Simplified dxf_id_map for this test G-code
    test_dxf_id_map = {
        0: "INIT_SETUP",
        1: "INIT_POSITION",
        2: "PATH_COMMENT_LINES_ARCS",
        3: "L1",
        4: "L2",
        5: "A3",
        6: "JUMP_TO_DXF_1", # This would map to L1
        7: "PATH_COMMENT_CIRCLES",
        8: "JUMP_TO_CIRCLE_4", # This would map to C4
        9: "C4",
        10: "PROGRAM_END"
    }

    # Example block colors
    test_block_colors = {
        "ORDERED_TRAJECTORY": "blue",
        "ISOLATED_CIRCLES": "red",
        "HIGHLIGHT": "orange"
    }

    gcode_vis.update_gcode(test_gcode, test_dxf_id_map, test_block_colors)

    # Add some buttons for testing highlights
    button_frame = tk.Frame(root)
    button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)

    def highlight_line1():
        gcode_vis.highlight_gcode_line("L1")

    def highlight_arc3():
        gcode_vis.highlight_gcode_line("A3")

    def highlight_circle4():
        gcode_vis.highlight_gcode_line("C4")
    
    def highlight_ordered():
        gcode_vis.highlight_gcode_line("ORDERED_TRAJECTORY")

    def highlight_isolated():
        gcode_vis.highlight_gcode_line("ISOLATED_CIRCLES")

    def clear_highlight():
        gcode_vis.highlight_gcode_line(None)

    tk.Button(button_frame, text="Highlight L1", command=highlight_line1).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Highlight A3", command=highlight_arc3).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Highlight C4", command=highlight_circle4).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Highlight Ordered Trajectory", command=highlight_ordered).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Highlight Isolated Circles", command=highlight_isolated).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Clear Highlight", command=clear_highlight).pack(side=tk.LEFT, padx=5)

    root.mainloop()
# gcode_visualizer.py
import matplotlib.pyplot as plt
import re
import math
import sys

class GcodeVisualizer:
    """
    Handles the visualization of ISO G-code paths using Matplotlib.
    """
    def __init__(self, ax):
        self.ax = ax
        # self.ax.set_title("Visualisation du Trajet CNC (G-code ISO)", fontsize=14)
        #self.ax.set_xlabel("X Coordonnée")
        #self.ax.set_ylabel("Y Coordonnée")
        #self.ax.grid(True)
        self.ax.set_aspect('equal', adjustable='box')

        #self._legend_labels = set()
        self.connection_tolerance = 1e-3 # Used for G00 jumps and now for arc start/end precision

        self.plotted_elements = [] # Stores all plotted artists for reset/highlight
        self.gcode_line_map = {} # Maps G-code line index to plotted_elements index

        self.current_highlighted_elements = [] # Stores currently highlighted artists
        self._original_colors = {}
        self._original_linewidths = {}
        self._original_markersizes = {}

    def reset_plot(self):
        """Clears the current plot and resets internal states."""
        self.ax.clear()
        self.ax.set_title("Visualisation du Trajet CNC (G-code ISO)", fontsize=14)
        self.ax.set_xlabel("X Coordonnée")
        self.ax.set_ylabel("Y Coordonnée")
        self.ax.grid(True)
        self.ax.set_aspect('equal', adjustable='box')
        self._legend_labels = set()
        self.plotted_elements = []
        self.gcode_line_map = {}
        self.current_highlighted_elements = []
        self._original_colors = {}
        self._original_linewidths = {}
        self._original_markersizes = {}
        self.ax.figure.canvas.draw_idle()

    def _add_plot_label(self, label):
        """Helper to add unique labels to the legend."""
        if label not in self._legend_labels:
            self._legend_labels.add(label)
            return label
        return None

    def _parse_gcode_line(self, line):
        """Parses a single G-code line into its components."""
        parsed_data = {
            'command': None, 'X': None, 'Y': None, 'I': None, 'J': None
        }
        line_clean = re.sub(r'N\d+\s*', '', line).split(';')[0].strip()
        if not line_clean: return None
        parts = line_clean.split()
        if not parts: return None
        parsed_data['command'] = parts[0]
        for part in parts[1:]:
            if part.startswith('X'): parsed_data['X'] = float(part[1:])
            elif part.startswith('Y'): parsed_data['Y'] = float(part[1:])
            elif part.startswith('I'): parsed_data['I'] = float(part[1:])
            elif part.startswith('J'): parsed_data['J'] = float(part[1:])
        return parsed_data

    def visualize(self, gcode_string):
        """
        Visualizes the given G-code string on the Matplotlib axes.
        """
        self.reset_plot()

        current_x, current_y = 0.0, 0.0
        start_point_marked = False
        end_point_of_path = (None, None)

        gcode_lines = gcode_string.strip().split('\n')
        
        self.plotted_elements = []
        self.gcode_line_map = {}

        for i, line_str in enumerate(gcode_lines):
            parsed = self._parse_gcode_line(line_str)
            
            if parsed is None or parsed['command'] is None:
                # Map this G-code line to an empty list of artists if it's just a comment or empty
                self.gcode_line_map[i] = len(self.plotted_elements)
                self.plotted_elements.append([]) 
                continue

            command = parsed['command']
            target_x = parsed['X'] if parsed['X'] is not None else current_x
            target_y = parsed['Y'] if parsed['Y'] is not None else current_y

            current_plotted_artists = []

            if not start_point_marked:
                artist_start_marker = self.ax.plot(current_x, current_y, 'o', color='gold', markersize=10,
                                     label=self._add_plot_label(f'Départ'))[0]
                artist_start_text = self.ax.text(current_x + 0.05, current_y + 0.05, f'D({current_x:.2f},{current_y:.2f})', color='gold', fontsize=8, ha='left', va='bottom')
                current_plotted_artists.extend([artist_start_marker, artist_start_text])
                start_point_marked = True

            if command == 'G00':
                line_artist = self.ax.plot([current_x, target_x], [current_y, target_y], 'r--', alpha=0.7,
                                           label=self._add_plot_label('G00 (Rapide)'))[0]
                marker_artist = self.ax.plot(target_x, target_y, 'ro', markersize=4)[0]
                text_artist = self.ax.text(target_x + 0.05, target_y + 0.05, f'R({target_x:.2f},{target_y:.2f})', color='red', fontsize=7, ha='left', va='bottom')
                current_plotted_artists.extend([line_artist, marker_artist, text_artist])

            elif command == 'G01':
                line_artist = self.ax.plot([current_x, target_x], [current_y, target_y], 'b-', linewidth=2,
                                           label=self._add_plot_label('G01 (Linéaire)'))[0]
                marker_artist = self.ax.plot(target_x, target_y, 'bo', markersize=4)[0]
                text_artist = self.ax.text(target_x + 0.05, target_y + 0.05, f'L({target_x:.2f},{target_y:.2f})', color='blue', fontsize=7, ha='left', va='bottom')
                current_plotted_artists.extend([line_artist, marker_artist, text_artist])

            elif command == 'G02' or command == 'G03':
                i_offset = parsed['I'] if parsed['I'] is not None else 0.0
                j_offset = parsed['J'] if parsed['J'] is not None else 0.0
                center_x = current_x + i_offset
                center_y = current_y + j_offset
                
                # --- DEBUG PROMPT: Arc Definition ---
                print(f"\n--- DEBUG ARC (Ligne G-code {i+1}) ---")
                print(f"  Commande: {command}")
                print(f"  Point de départ (current): ({current_x:.4f}, {current_y:.4f})")
                print(f"  Point d'arrivée (target): ({target_x:.4f}, {target_y:.4f})")
                print(f"  Offsets I,J: ({i_offset:.4f}, {j_offset:.4f})")
                print(f"  Centre de l'arc (calculé): ({center_x:.4f}, {center_y:.4f})")
                
                # Handle potential degenerate arcs (start and end points are effectively the same)
                if math.hypot(target_x - current_x, target_y - current_y) < self.connection_tolerance:
                    print("  Arc Dégénéré: Point de départ et d'arrivée sont identiques (ou très proches).")
                    point_artist = self.ax.plot(current_x, current_y, 'o', color='gray', markersize=4)[0]
                    text_artist = self.ax.text(current_x + 0.05, current_y + 0.05, f'Arc Dégénéré ({current_x:.2f},{current_y:.2f})', color='gray', fontsize=7, ha='left', va='bottom')
                    current_plotted_artists.extend([point_artist, text_artist])
                    current_x, current_y = target_x, target_y 
                    self.gcode_line_map[i] = len(self.plotted_elements)
                    self.plotted_elements.append(current_plotted_artists)
                    continue

                radius = math.hypot(current_x - center_x, current_y - center_y) # Radius from start to center
                print(f"  Rayon (calculé depuis le départ): {radius:.4f}")

                # Calculate start and end angles relative to the calculated center
                start_angle_rad = math.atan2(current_y - center_y, current_x - center_x)
                end_angle_rad = math.atan2(target_y - center_y, target_x - center_x)

                # --- DEBUG PROMPT: Initial Angles ---
                print(f"  Angle de départ (start_angle_rad - atan2 brut): {math.degrees(start_angle_rad):.2f}° ({start_angle_rad:.4f} rad)")
                print(f"  Angle de fin (end_angle_rad - atan2 brut): {math.degrees(end_angle_rad):.2f}° ({end_angle_rad:.4f} rad)")

                # Calculate initial raw angular difference
                raw_angle_diff = end_angle_rad - start_angle_rad
                print(f"  Différence d'angle brute (raw_angle_diff): {math.degrees(raw_angle_diff):.2f}° ({raw_angle_diff:.4f} rad)")

                # Ensure the angles cover the correct sweep direction (CW or CCW)
                # The logic aims to ensure `end_angle_rad - start_angle_rad` has the correct sign and magnitude.
                
                if command == 'G02': # Clockwise (CW)
                    # If raw_angle_diff is positive (implies CCW sweep), we need to make it negative (CW).
                    # A small positive raw_angle_diff means the angle crosses 0 anti-clockwise.
                    # We need it to cross 0 clockwise. E.g., start = -170 deg, end = 170 deg (raw_diff = 340 deg CCW).
                    # If command G02, we want -340 deg CW.
                    if raw_angle_diff > self.connection_tolerance:
                        end_angle_rad -= 2 * math.pi
                    
                    # Special handling for 180-degree arcs or full circles that might
                    # otherwise be misinterpreted. If the raw difference is close to pi,
                    # ensure it's not converted to a -3pi or similar.
                    # This check is crucial for the "turn too many" problem for 180deg arcs.
                    # If the absolute difference is around PI (180deg), we must not adjust by 2PI
                    # unless it's a full circle (start=end).
                    # A robust way is to normalize the difference to (-pi, pi] first and then adjust.
                    
                    # Let's try the common technique used in CAM: normalize to shortest path, then adjust
                    # Normalized shortest path difference (always between -pi and +pi)
                    shortest_diff = (end_angle_rad - start_angle_rad + math.pi) % (2 * math.pi) - math.pi
                    
                    if shortest_diff == 0.0 and (abs(i_offset) > self.connection_tolerance or abs(j_offset) > self.connection_tolerance):
                        # Full circle case (start == end, non-zero I,J)
                        # For G02, force -2pi sweep
                        end_angle_rad = start_angle_rad - (2 * math.pi)
                        print("  Cas: Cercle Complet CW (Départ=Arrivée). Forçage balayage -360°.")
                    elif shortest_diff > 0 and command == 'G02': # Shortest path is CCW, but we need CW
                        end_angle_rad = start_angle_rad + (shortest_diff - 2 * math.pi)
                        print(f"  Ajustement G02: Balayage CCW (positif) initial détecté. Ajusté à CW (-2PI).")
                    elif shortest_diff < 0 and command == 'G03': # Shortest path is CW, but we need CCW
                        # This case is for G03, but here we are in G02 block.
                        # This condition should not trigger for G02. It's for G03.
                        pass # No action needed for G02 if shortest_diff is negative (already CW)
                    
                else: # G03 - Counter-clockwise (CCW)
                    # If raw_angle_diff is negative (implies CW sweep), we need to make it positive (CCW).
                    # A small negative raw_angle_diff means the angle crosses 0 clockwise.
                    # We need it to cross 0 anti-clockwise. E.g., start = 170 deg, end = -170 deg (raw_diff = -340 deg CW).
                    # If command G03, we want +340 deg CCW.
                    if raw_angle_diff < -self.connection_tolerance:
                        end_angle_rad += 2 * math.pi

                    # Similar logic for 180-degree or full circles for G03
                    shortest_diff = (end_angle_rad - start_angle_rad + math.pi) % (2 * math.pi) - math.pi

                    if shortest_diff == 0.0 and (abs(i_offset) > self.connection_tolerance or abs(j_offset) > self.connection_tolerance):
                        # Full circle case
                        end_angle_rad = start_angle_rad + (2 * math.pi)
                        print("  Cas: Cercle Complet CCW (Départ=Arrivée). Forçage balayage +360°.")
                    elif shortest_diff < 0 and command == 'G03': # Shortest path is CW, but we need CCW
                        end_angle_rad = start_angle_rad + (shortest_diff + 2 * math.pi)
                        print(f"  Ajustement G03: Balayage CW (négatif) initial détecté. Ajusté à CCW (+2PI).")
                    elif shortest_diff > 0 and command == 'G02':
                        # This case is for G02, but here we are in G03 block.
                        pass # No action needed for G03 if shortest_diff is positive (already CCW)
                
                # --- DEBUG PROMPT: Adjusted Angles ---
                print(f"  Angle de départ (final pour plot): {math.degrees(start_angle_rad):.2f}° ({start_angle_rad:.4f} rad)")
                print(f"  Angle de fin (final pour plot, après ajustement): {math.degrees(end_angle_rad):.2f}° ({end_angle_rad:.4f} rad)")
                print(f"  Balayage final (end - start): {math.degrees(end_angle_rad - start_angle_rad):.2f}° ({end_angle_rad - start_angle_rad:.4f} rad)")


                num_arc_points = 50
                angles = [start_angle_rad + (end_angle_rad - start_angle_rad) * t / num_arc_points for t in range(num_arc_points + 1)]
                
                arc_x = [center_x + radius * math.cos(angle) for angle in angles]
                arc_y = [center_y + radius * math.sin(angle) for angle in angles]

                # Ensure arc path ends precisely at target_x, target_y (minor adjustment for float precision)
                # This helps if the calculated end_angle_rad leads to slight deviation
                if (abs(arc_x[-1] - target_x) > self.connection_tolerance or
                    abs(arc_y[-1] - target_y) > self.connection_tolerance):
                    print(f"  ATTENTION: Ajustement final du point d'arrivée de l'arc (précision): "
                          f"({arc_x[-1]:.4f}, {arc_y[-1]:.4f}) -> ({target_x:.4f}, {target_y:.4f})")
                    arc_x[-1] = target_x
                    arc_y[-1] = target_y

                line_color = 'g-' if command == 'G02' else 'c-'
                marker_color = 'go' if command == 'G02' else 'co'
                label_text = 'G02 (Circulaire CW)' if command == 'G02' else 'G03 (Circulaire CCW)'
                text_color = 'green' if command == 'G02' else 'cyan'

                line_artist = self.ax.plot(arc_x, arc_y, line_color, linewidth=2,
                                           label=self._add_plot_label(label_text))[0]
                center_marker_artist = self.ax.plot(center_x, center_y, 'x', color='purple', markersize=8,
                                                    label=self._add_plot_label('Centre Arc'))[0]
                center_text_artist = self.ax.text(center_x + 0.05, center_y + 0.05, f'C({center_x:.2f},{center_y:.2f})', color='purple', fontsize=7, ha='left', va='bottom')
                target_marker_artist = self.ax.plot(target_x, target_y, marker_color, markersize=4)[0]
                target_text_artist = self.ax.text(target_x + 0.05, target_y + 0.05, f'A({target_x:.2f},{target_y:.2f})', color=text_color, fontsize=7, ha='left', va='bottom')
                current_plotted_artists.extend([line_artist, center_marker_artist, center_text_artist, target_marker_artist, target_text_artist])
            
            # Map the current G-code line index to the artists just plotted
            self.gcode_line_map[i] = len(self.plotted_elements)
            self.plotted_elements.append(current_plotted_artists)

            current_x, current_y = target_x, target_y
            end_point_of_path = (current_x, current_y)
        
        # Mark the end point of the entire path
        if end_point_of_path[0] is not None:
            artist_end_marker = self.ax.plot(end_point_of_path[0], end_point_of_path[1], 's', color='darkred', markersize=10,
                                 label=self._add_plot_label(f'Fin'))[0]
            artist_end_text = self.ax.text(end_point_of_path[0] + 0.05, end_point_of_path[1] + 0.05, f'Fin\n({end_point_of_path[0]:.2f},{end_point_of_path[1]:.2f})', color='darkred', fontsize=8, ha='left', va='bottom')

        self.ax.legend(loc='best', fontsize=9)
        self.ax.figure.canvas.draw_idle()


    def highlight_elements(self, gcode_line_index, color='yellow', linewidth_scale=2.0, marker_size_scale=1.5):
        """
        Highlights the plot elements corresponding to a specific G-code line.
        Resets previous highlights.
        """
        # Reset previous highlights
        for element in self.current_highlighted_elements:
            if element in self._original_colors:
                if isinstance(element, plt.Line2D):
                    element.set_color(self._original_colors[element])
                    if element in self._original_linewidths:
                        element.set_linewidth(self._original_linewidths[element])
                    if element in self._original_markersizes and hasattr(element, 'set_markersize'):
                        element.set_markersize(self._original_markersizes[element])
                elif isinstance(element, plt.Text):
                    element.set_color(self._original_colors[element])
                elif isinstance(element, plt.Artist): # Handles markers, etc.
                    if hasattr(element, 'get_markerfacecolor') and element.get_markerfacecolor() not in ['none', (0.0, 0.0, 0.0, 0.0)]:
                        element.set_markerfacecolor(self._original_colors[element])
                    if hasattr(element, 'get_markeredgecolor'):
                        element.set_markeredgecolor(self._original_colors[element])
                    if hasattr(element, 'set_markersize') and element in self._original_markersizes:
                        element.set_markersize(self._original_markersizes[element])
                            
        self.current_highlighted_elements = []

        # Apply new highlight
        if gcode_line_index in self.gcode_line_map:
            plot_elements_idx = self.gcode_line_map[gcode_line_index]
            
            if plot_elements_idx < len(self.plotted_elements):
                artists_to_highlight = self.plotted_elements[plot_elements_idx]
                
                for element in artists_to_highlight:
                    if isinstance(element, plt.Line2D):
                        self._original_colors[element] = element.get_color()
                        self._original_linewidths[element] = element.get_linewidth()
                        self._original_markersizes[element] = element.get_markersize() if hasattr(element, 'get_markersize') else 0
                        
                        element.set_color(color)
                        element.set_linewidth(element.get_linewidth() * linewidth_scale)
                        if hasattr(element, 'set_markersize') and element.get_markersize() > 0:
                            element.set_markersize(element.get_markersize() * marker_size_scale)
                    elif isinstance(element, plt.Text):
                        self._original_colors[element] = element.get_color()
                        element.set_color(color)
                    elif isinstance(element, plt.Artist):
                        if hasattr(element, 'get_markerfacecolor') and element.get_markerfacecolor() not in ['none', (0.0, 0.0, 0.0, 0.0)]:
                            self._original_colors[element] = element.get_markerfacecolor()
                            element.set_markerfacecolor(color)
                        elif hasattr(element, 'get_markeredgecolor'):
                            self._original_colors[element] = element.get_markeredgecolor()
                            element.set_markeredgecolor(color)
                        
                        if hasattr(element, 'set_markersize') and hasattr(element, 'get_markersize'):
                            self._original_markersizes[element] = element.get_markersize()
                            element.set_markersize(element.get_markersize() * marker_size_scale)
                    self.current_highlighted_elements.append(element)
        self.ax.figure.canvas.draw_idle()
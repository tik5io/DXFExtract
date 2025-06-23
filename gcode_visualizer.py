#gcode_visualizer.py
"""
This module provides a class for visualizing ISO G-code paths using Matplotlib. 
It includes methods for parsing G-code, plotting the paths, and highlighting specific elements.
It is designed to be used in a Jupyter notebook or any Python environment with Matplotlib installed
and configured.
"""


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
        # Remove title, xlabel, ylabel
        # self.ax.set_title("Visualisation du Trajet CNC (G-code ISO)", fontsize=14)
        # self.ax.set_xlabel("X Coordonnée")
        # self.ax.set_ylabel("Y Coordonnée")
        self.ax.grid(True)
        self.ax.set_aspect('equal', adjustable='box')
        # Remove axis ticks and labels
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.set_xticklabels([])
        self.ax.set_yticklabels([])

        self._legend_labels = set()
        self.connection_tolerance = 1e-4 # Used for G00 jumps and now for arc start/end precision

        self.plotted_elements = [] # Stores all plotted artists for reset/highlight
        self.gcode_line_map = {} # Maps G-code line index to plotted_elements index

        self.current_highlighted_elements = [] # Stores currently highlighted artists
        self._original_colors = {}
        self._original_linewidths = {}
        self._original_markersizes = {}

    def reset_plot(self):
        """Clears the current plot and resets internal states."""
        self.ax.clear()
        # Remove title, xlabel, ylabel
        # self.ax.set_title("Visualisation du Trajet CNC (G-code ISO)", fontsize=14)
        # self.ax.set_xlabel("X Coordonnée")
        # self.ax.set_ylabel("Y Coordonnée")
        self.ax.grid(True)
        self.ax.set_aspect('equal', adjustable='box')
        # Remove axis ticks and labels
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.set_xticklabels([])
        self.ax.set_yticklabels([])

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
        # We're removing the legend, so this function is no longer needed to manage legend labels.
        # However, it's good practice to keep the original structure if it's called elsewhere
        # and just make it return None if the label isn't actually used for plotting a legend.
        return None # No labels for legend

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

    def visualize(self, gcode_string, dxf_segment_id_map=None):
        """
        Visualizes the given G-code string on the Matplotlib axes.
        Args:
            gcode_string (str): The G-code content as a string.
            dxf_segment_id_map (dict, optional): A dictionary mapping G-code line index
                                                 to the original DXF segment ID.
                                                 Used for displaying IDs on the plot.
                                                 Defaults to None.
        """
        if dxf_segment_id_map is None:
            dxf_segment_id_map = {}

        self.reset_plot()

        current_x, current_y = 0.0, 0.0
        start_point_marked = False
        end_point_of_path = (None, None)

        gcode_lines = gcode_string.strip().split('\n')
        
        self.plotted_elements = []
        self.gcode_line_map = {}

        for i, line_str in enumerate(gcode_lines):
            parsed = self._parse_gcode_line(line_str)
            
            # Get the original DXF segment ID for this G-code line, if available
            original_dxf_id = dxf_segment_id_map.get(i, 'N/A')
            dxf_id_label = f' (DXF ID: {original_dxf_id})' if original_dxf_id != 'N/A' else ''

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
                # Removed label argument from plot to prevent it from showing in a legend
                artist_start_marker = self.ax.plot(current_x, current_y, 'o', color='gold', markersize=10)[0]
                # Removed text labels for clarity
                # artist_start_text = self.ax.text(current_x + 0.05, current_y + 0.05, 
                #                                  f'D(X:{current_x:.2f},Y:{current_y:.2f}) - Ligne 1', 
                #                                  color='gold', fontsize=8, ha='left', va='bottom')
                current_plotted_artists.extend([artist_start_marker]) # Only marker
                start_point_marked = True

            if command == 'G00':
                line_artist = self.ax.plot([current_x, target_x], [current_y, target_y], 'r--', alpha=0.7)[0]
                marker_artist = self.ax.plot(target_x, target_y, 'ro', markersize=4)[0]
                # Removed text labels for clarity
                # text_artist = self.ax.text(target_x + 0.05, target_y + 0.05, 
                #                            f'G00 (Ligne {i+1}){dxf_id_label}\n'
                #                            f'Départ(X:{current_x:.2f},Y:{current_y:.2f})\n'
                #                            f'Fin(X:{target_x:.2f},Y:{target_y:.2f})', 
                #                            color='red', fontsize=7, ha='left', va='bottom')
                current_plotted_artists.extend([line_artist, marker_artist]) # Only line and marker

            elif command == 'G01':
                line_artist = self.ax.plot([current_x, target_x], [current_y, target_y], 'b-', linewidth=2)[0]
                marker_artist = self.ax.plot(target_x, target_y, 'bo', markersize=4)[0]
                # Removed text labels for clarity
                # text_artist = self.ax.text(target_x + 0.05, target_y + 0.05, 
                #                            f'G01 (Ligne {i+1}){dxf_id_label}\n'
                #                            f'Départ(X:{current_x:.2f},Y:{current_y:.2f})\n'
                #                            f'Fin(X:{target_x:.2f},Y:{target_y:.2f})', 
                #                            color='blue', fontsize=7, ha='left', va='bottom')
                current_plotted_artists.extend([line_artist, marker_artist]) # Only line and marker

            elif command == 'G02' or command == 'G03':
                i_offset = parsed['I'] if parsed['I'] is not None else 0.0
                j_offset = parsed['J'] if parsed['J'] is not None else 0.0
                center_x = current_x + i_offset
                center_y = current_y + j_offset

                # --- DEBUG PROMPT: Arc Definition ---
                print(f"\n--- DEBUG ARC (Ligne G-code {i+1}) ---")
                print(f"   Commande: {command}")
                print(f"   Point de départ (current): ({current_x:.4f}, {current_y:.4f})")
                print(f"   Point d'arrivée (target): ({target_x:.4f}, {target_y:.4f})")
                print(f"   Offsets I,J: ({i_offset:.4f}, {j_offset:.4f})")
                print(f"   Centre de l'arc (calculé): ({center_x:.4f}, {center_y:.4f})")

                # Calculate radius from start point to center
                radius = math.hypot(current_x - center_x, current_y - center_y)
                print(f"   Rayon (calculé depuis le départ): {radius:.4f}")

                is_start_end_same = math.hypot(target_x - current_x, target_y - current_y) < self.connection_tolerance

                start_angle_rad = math.atan2(current_y - center_y, current_x - center_x)
                end_angle_rad = math.atan2(target_y - center_y, target_x - center_x)

                # --- DEBUG PROMPT: Initial Angles ---
                print(f"   Angle de départ (start_angle_rad - atan2 brut): {math.degrees(start_angle_rad):.2f}° ({start_angle_rad:.4f} rad)")
                print(f"   Angle de fin (end_angle_rad - atan2 brut): {math.degrees(end_angle_rad):.2f}° ({end_angle_rad:.4f} rad)")

                # Handle full circles vs. partial arcs
                if is_start_end_same and radius > self.connection_tolerance:
                    print("   Détecté: Cercle Complet (départ=arrivée, rayon > 0).")
                    if command == 'G02': # CW full circle
                        end_angle_rad = start_angle_rad - (2 * math.pi)
                    else: # G03 - CCW full circle
                        end_angle_rad = start_angle_rad + (2 * math.pi)
                elif is_start_end_same and radius <= self.connection_tolerance:
                    print("   Arc Vraiment Dégénéré: Point de départ et d'arrivée sont identiques et rayon nul (ou très proche).")
                    point_artist = self.ax.plot(current_x, current_y, 'o', color='gray', markersize=4)[0]
                    # Removed text label for clarity
                    # text_artist = self.ax.text(current_x + 0.05, current_y + 0.05,
                    #                                    f'Arc Dégénéré (Ligne {i+1}){dxf_id_label}\n'
                    #                                    f'(X:{current_x:.2f},Y:{current_y:.2f})',
                    #                                    color='gray', fontsize=7, ha='left', va='bottom')
                    current_plotted_artists.extend([point_artist]) # Only marker
                    self.gcode_line_map[i] = len(self.plotted_elements)
                    self.plotted_elements.append(current_plotted_artists)
                    continue

                else: # Partial arc, ensure correct sweep direction
                    angle_diff = end_angle_rad - start_angle_rad

                    if command == 'G02': # Clockwise (CW)
                        if angle_diff > self.connection_tolerance:
                            end_angle_rad -= 2 * math.pi
                            print(f"   Ajustement G02 (CCW -> CW): end_angle_rad = {math.degrees(end_angle_rad):.2f}°")
                        elif angle_diff < -2*math.pi + self.connection_tolerance:
                            end_angle_rad += 2 * math.pi
                            print(f"   Ajustement G02 (trop CCW -> CW): end_angle_rad = {math.degrees(end_angle_rad):.2f}°")

                    else: # G03 - Counter-clockwise (CCW)
                        if angle_diff < -self.connection_tolerance:
                            end_angle_rad += 2 * math.pi
                            print(f"   Ajustement G03 (CW -> CCW): end_angle_rad = {math.degrees(end_angle_rad):.2f}°")
                        elif angle_diff > 2*math.pi - self.connection_tolerance:
                            end_angle_rad -= 2 * math.pi
                            print(f"   Ajustement G03 (trop CW -> CCW): end_angle_rad = {math.degrees(end_angle_rad):.2f}°")

                angle_diff_final = end_angle_rad - start_angle_rad
                print(f"   Balayage final (end - start): {math.degrees(angle_diff_final):.2f}° ({angle_diff_final:.4f} rad)")
                
                print(f"   Angle de départ (final pour plot): {math.degrees(start_angle_rad):.2f}° ({start_angle_rad:.4f} rad)")
                print(f"   Angle de fin (final pour plot, après ajustement): {math.degrees(end_angle_rad):.2f}° ({end_angle_rad:.4f} rad)")
                print(f"   Balayage final (end - start): {math.degrees(end_angle_rad - start_angle_rad):.2f}° ({end_angle_rad - start_angle_rad:.4f} rad)")

                num_arc_points = 50
                angles = [start_angle_rad + (end_angle_rad - start_angle_rad) * t / num_arc_points for t in range(num_arc_points + 1)]
                
                arc_x = [center_x + radius * math.cos(angle) for angle in angles]
                arc_y = [center_y + radius * math.sin(angle) for angle in angles]

                if (abs(arc_x[-1] - target_x) > self.connection_tolerance or
                    abs(arc_y[-1] - target_y) > self.connection_tolerance):
                    print(f"   ATTENTION: Ajustement final du point d'arrivée de l'arc (précision): "
                          f"({arc_x[-1]:.4f}, {arc_y[-1]:.4f}) -> ({target_x:.4f}, {target_y:.4f})")
                    arc_x[-1] = target_x
                    arc_y[-1] = target_y
                
                print(f"   Nombre de points de l'arc générés : {len(arc_x)}")
                if len(arc_x) > 1:
                    print(f"   Premier point de l'arc: ({arc_x[0]:.4f}, {arc_y[0]:.4f})")
                    print(f"   Dernier point de l'arc: ({arc_x[-1]:.4f}, {arc_y[-1]:.4f})")
                    print(f"   Distance entre le premier et le dernier point (théorique) : {math.hypot(arc_x[-1] - arc_x[0], arc_y[-1] - arc_y[0]):.4f}")
                    print(f"   Distance entre le premier point et le point de départ G-code : {math.hypot(arc_x[0] - current_x, arc_y[0] - current_y):.4f}")
                    print(f"   Distance entre le dernier point et le point d'arrivée G-code : {math.hypot(arc_x[-1] - target_x, arc_y[-1] - target_y):.4f}")
                else:
                    print("   L'arc ne contient pas assez de points pour un tracé significatif.")


                line_color = 'g-' if command == 'G02' else 'c-'
                marker_color = 'go' if command == 'G02' else 'co'
                # Removed labels, so these variables are no longer used for the plot label itself
                # label_text = 'G02 (Circulaire CW)' if command == 'G02' else 'G03 (Circulaire CCW)' 
                # text_color = 'green' if command == 'G02' else 'cyan'

                line_artist = self.ax.plot(arc_x, arc_y, line_color, linewidth=2)[0]
                
                center_marker_artist = self.ax.plot(center_x, center_y, 'x', color='purple', markersize=8)[0]
                
                target_marker_artist = self.ax.plot(target_x, target_y, marker_color, markersize=4)[0]
                
                current_plotted_artists.extend([line_artist, center_marker_artist, target_marker_artist])
            
            self.gcode_line_map[i] = len(self.plotted_elements)
            self.plotted_elements.append(current_plotted_artists)

            current_x, current_y = target_x, target_y
            end_point_of_path = (current_x, current_y)
        
        if end_point_of_path[0] is not None:
            artist_end_marker = self.ax.plot(end_point_of_path[0], end_point_of_path[1], 's', color='darkred', markersize=10)[0]
            current_plotted_artists.extend([artist_end_marker]) # Add end marker to the last set of plotted artists if any
            # For the end marker, we'll store it separately if there were no previous plotted artists,
            # to ensure it's still accessible for highlighting.
            if i not in self.gcode_line_map or not self.plotted_elements[self.gcode_line_map[i]]:
                self.gcode_line_map[i] = len(self.plotted_elements)
                self.plotted_elements.append([artist_end_marker])
            else:
                 self.plotted_elements[self.gcode_line_map[i]].append(artist_end_marker)


        # self.ax.legend(loc='best', fontsize=9) # Removed legend
        self.ax.figure.canvas.draw_idle()

    def clear_highlights(self):
        """
        Resets all current highlights on the plot elements.
        """
        for element in self.current_highlighted_elements:
            if element in self._original_colors:
                if isinstance(element, plt.Line2D):
                    element.set_color(self._original_colors[element])
                    if element in self._original_linewidths:
                        element.set_linewidth(self._original_linewidths[element])
                    if element in self._original_markersizes and hasattr(element, 'set_markersize'):
                        element.set_markersize(self._original_markersizes[element])
                elif isinstance(element, plt.Text): # Text labels are removed, so this branch won't be hit for main plotting, but keep for highlight
                    element.set_color(self._original_colors[element])
                elif isinstance(element, plt.Artist): # Handles markers, etc.
                    if hasattr(element, 'get_markerfacecolor') and element.get_markerfacecolor() not in ['none', (0.0, 0.0, 0.0, 0.0)]:
                        element.set_markerfacecolor(self._original_colors[element])
                    if hasattr(element, 'get_markeredgecolor'):
                        element.set_markeredgecolor(self._original_colors[element])
                    if hasattr(element, 'set_markersize') and element in self._original_markersizes:
                        element.set_markersize(self._original_markersizes[element])
                            
        self.current_highlighted_elements = []
        self._original_colors = {}
        self._original_linewidths = {}
        self._original_markersizes = {}
        self.ax.figure.canvas.draw_idle()


    def highlight_elements(self, gcode_line_index, color='yellow', linewidth_scale=2.0, marker_size_scale=1.5):
        """
        Highlights the plot elements corresponding to a specific G-code line.
        Resets previous highlights.
        """
        self.clear_highlights() # Call the new clear_highlights method

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
                    elif isinstance(element, plt.Text): # This will only apply if text labels are added back or for specific debug text
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
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, ttk
import math
import re
import sys
import copy
import os 
import ezdxf
# from PIL import Image, ImageTk # Uncomment if you want to use PIL for resizing images (requires pip install Pillow)

# --- Votre classe DxfToIsoConverter (pas de changements majeurs) ---
class DxfToIsoConverter:
    """
    A class to convert DXF LINE and ARC entities into ISO G-code,
    with options for automated or assisted path ordering.
    Automatically adds G00 jumps if discontinuities are detected.
    """
    def __init__(self, connection_tolerance=1e-4):
        self.connection_tolerance = connection_tolerance

    def _extract_dxf_entities(self, dxf_filepath):
        entities_data = {}
        current_id = 1
        try:
            doc = ezdxf.readfile(dxf_filepath)
            msp = doc.modelspace()
            for entity in msp:
                cloned_entity = entity.copy() # Create a shallow copy of the ezdxf entity
                
                if entity.dxftype() == 'LINE':
                    start = cloned_entity.dxf.start
                    end = cloned_entity.dxf.end
                    entities_data[current_id] = {
                        'type': 'LINE',
                        'original_ezdxf_entity': cloned_entity,
                        'coords': {
                            'start': (start.x, start.y),
                            'end': (end.x, end.y)
                        },
                        'reversed': False,
                        'original_id': current_id, # Keep track of the original DXF ID for reference
                        'id_display': f"Segment {current_id} (L)" # For display in Listbox
                    }
                    current_id += 1
                elif entity.dxftype() == 'ARC':
                    center = cloned_entity.dxf.center
                    arc_start_point = cloned_entity.start_point
                    arc_end_point = cloned_entity.end_point
                    entities_data[current_id] = {
                        'type': 'ARC',
                        'original_ezdxf_entity': cloned_entity,
                        'coords': {
                            'center': (center.x, center.y),
                            'start_point': (arc_start_point.x, arc_start_point.y),
                            'end_point': (arc_end_point.x, arc_end_point.y),
                            'radius': cloned_entity.dxf.radius,
                            'start_angle': cloned_entity.dxf.start_angle,
                            'end_angle': cloned_entity.dxf.end_angle
                        },
                        'reversed': False,
                        'original_id': current_id, # Keep track of the original DXF ID for reference
                        'id_display': f"Segment {current_id} (A)" # For display in Listbox
                    }
                    current_id += 1
        except FileNotFoundError:
            messagebox.showerror("Erreur", f"Fichier DXF '{dxf_filepath}' introuvable.")
            return None
        except ezdxf.DXFError as e:
            messagebox.showerror("Erreur DXF", f"Erreur de lecture du fichier DXF: {e}\nAssurez-vous que le fichier est valide.")
            return None
        except Exception as e:
            messagebox.showerror("Erreur", f"Une erreur inattendue est survenue lors de l'extraction DXF: {e}")
            return None
        messagebox.showinfo("DXF Chargé", f"{len(entities_data)} entités extraites du DXF.")
        return entities_data

    def _reverse_segment_direction_internal(self, entity_data):
        """
        Internally reverses the direction of a segment (LINE or ARC).
        Updates the original_ezdxf_entity's DXF properties and the 'coords' dictionary.
        This modifies the passed `entity_data` dictionary in place.
        """
        entity = entity_data['original_ezdxf_entity']

        if entity_data['type'] == 'LINE':
            start_point_orig = entity.dxf.start
            entity.dxf.start = entity.dxf.end
            entity.dxf.end = start_point_orig

            entity_data['coords']['start'] = (entity.dxf.start.x, entity.dxf.start.y)
            entity_data['coords']['end'] = (entity.dxf.end.x, entity.dxf.end.y)

        elif entity_data['type'] == 'ARC':
            start_angle_orig = entity.dxf.start_angle
            entity.dxf.start_angle = entity.dxf.end_angle
            entity.dxf.end_angle = start_angle_orig

            entity_data['coords']['start_point'] = (entity.start_point.x, entity.start_point.y)
            entity_data['coords']['end_point'] = (entity.end_point.x, entity.end_point.y)
            entity_data['coords']['start_angle'] = entity.dxf.start_angle
            entity_data['coords']['end_angle'] = entity.dxf.end_angle

        entity_data['reversed'] = not entity_data['reversed']
        base_id_display = f"Segment {entity_data['original_id']} ({'L' if entity_data['type'] == 'LINE' else 'A'})"
        if entity_data['reversed']:
            entity_data['id_display'] = f"{base_id_display} [R]"
        else:
            entity_data['id_display'] = base_id_display


    def _get_best_candidate_info(self, reference_point, entities_to_search):
        best_match_id = None
        best_should_reverse = False
        min_distance = float('inf')

        for entity_id, data in entities_to_search.items():
            segment_start = None
            segment_end = None

            if data['type'] == 'LINE':
                segment_start = data['coords']['start']
                segment_end = data['coords']['end']
            elif data['type'] == 'ARC':
                segment_start = data['coords']['start_point']
                segment_end = data['coords']['end_point']

            dist_to_start = math.hypot(reference_point[0] - segment_start[0],
                                       reference_point[1] - segment_start[1])

            dist_to_end = math.hypot(reference_point[0] - segment_end[0],
                                     reference_point[1] - segment_end[1])

            if dist_to_start < min_distance:
                min_distance = dist_to_start
                best_match_id = entity_id
                best_should_reverse = False

            if dist_to_end < min_distance:
                min_distance = dist_to_end
                best_match_id = entity_id
                best_should_reverse = True

        return (best_match_id, best_should_reverse, min_distance)

    def _generate_iso_gcode(self, output_filepath, ordered_segments_data_list, initial_start_point=(0.0, 0.0)):
        current_x = initial_start_point[0]
        current_y = initial_start_point[1]
        gcode_lines = []

        if ordered_segments_data_list:
            first_segment_data = ordered_segments_data_list[0]
            if first_segment_data['type'] == 'LINE':
                segment_start_x, segment_start_y = first_segment_data['coords']['start']
            else: # ARC
                segment_start_x, segment_start_y = first_segment_data['coords']['start_point']
            
            if math.hypot(current_x - segment_start_x, current_y - segment_start_y) > sys.float_info.epsilon:
                gcode_lines.append(f"G00 X{segment_start_x:.4f} Y{segment_start_y:.4f}")
                current_x, current_y = segment_start_x, segment_start_y

        for i, segment_data in enumerate(ordered_segments_data_list):
            entity_type = segment_data['type']
            coords = segment_data['coords']

            if entity_type == 'LINE':
                segment_start_x, segment_start_y = coords['start']
                segment_end_x, segment_end_y = coords['end']
            elif entity_type == 'ARC':
                segment_start_x, segment_start_y = coords['start_point']
                segment_end_x, segment_end_y = coords['end_point']

            if i > 0:
                distance_to_segment_start = math.hypot(current_x - segment_start_x, current_y - segment_start_y)
                if distance_to_segment_start > self.connection_tolerance:
                    gcode_lines.append(f"G00 X{segment_start_x:.4f} Y{segment_start_y:.4f}")
                    current_x, current_y = segment_start_x, segment_start_y

            if entity_type == 'LINE':
                gcode_lines.append(f"G01 X{segment_end_x:.4f} Y{segment_end_y:.4f}")
            elif entity_type == 'ARC':
                arc_center_x = coords['center'][0]
                arc_center_y = coords['center'][1]
                i_rel = arc_center_x - current_x
                j_rel = arc_center_y - current_y
                if segment_data['reversed']:
                    gcode_command = "G02" # Clockwise
                else:
                    gcode_command = "G03" # Counter-clockwise
                gcode_lines.append(f"{gcode_command} X{segment_end_x:.4f} Y{segment_end_y:.4f} I{i_rel:.4f} J{j_rel:.4f}")

            current_x, current_y = segment_end_x, segment_end_y

        gcode_lines.append("M02")

        final_gcode_lines_with_numbers = []
        line_num = 10
        for line in gcode_lines:
            final_gcode_lines_with_numbers.append(f"N{line_num} {line}")
            line_num += 10
        
        try:
            if output_filepath:
                with open(output_filepath, 'w') as f:
                    f.write("\n".join(final_gcode_lines_with_numbers))
            return "\n".join(final_gcode_lines_with_numbers)
        except Exception as e:
            messagebox.showerror("Erreur de génération", f"Erreur lors de la génération du fichier ISO G-code: {e}")
            return None


# --- Votre classe IsoPathVisualizer (pas de changements majeurs) ---
class IsoPathVisualizer:
    def __init__(self, ax):
        self.ax = ax
        self.ax.set_title("Visualisation du Trajet CNC (G-code ISO)", fontsize=14)
        self.ax.set_xlabel("X Coordonnée")
        self.ax.set_ylabel("Y Coordonnée")
        self.ax.grid(True)
        self.ax.set_aspect('equal', adjustable='box')

        self._legend_labels = set()
        self.connection_tolerance = 1e-4

        self.plotted_elements = []
        self.gcode_line_map = {}

        self.current_highlighted_elements = []

        self._original_colors = {}
        self._original_linewidths = {}
        self._original_markersizes = {}

    def reset_plot(self):
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
        if label not in self._legend_labels:
            self._legend_labels.add(label)
            return label
        return None

    def _parse_gcode_line(self, line):
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
                radius = math.hypot(i_offset, j_offset)

                start_angle_rad = math.atan2(current_y - center_y, current_x - center_x)
                end_angle_rad = math.atan2(target_y - center_y, target_x - center_y)

                start_angle_rad_norm = (start_angle_rad + 2 * math.pi) % (2 * math.pi)
                end_angle_rad_norm = (end_angle_rad + 2 * math.pi) % (2 * math.pi)

                if command == 'G02': # Clockwise
                    if end_angle_rad_norm > start_angle_rad_norm:
                        end_angle_rad -= 2 * math.pi
                    line_color = 'g-'
                    marker_color = 'go'
                    label_text = 'G02 (Circulaire CW)'
                    text_color = 'green'
                else: # G03 - Counter-clockwise
                    if end_angle_rad_norm < start_angle_rad_norm:
                        end_angle_rad += 2 * math.pi
                    line_color = 'c-'
                    marker_color = 'co'
                    label_text = 'G03 (Circulaire CCW)'
                    text_color = 'cyan'

                num_arc_points = 50
                angles = [start_angle_rad + (end_angle_rad - start_angle_rad) * t / num_arc_points for t in range(num_arc_points + 1)]
                arc_x = [center_x + radius * math.cos(angle) for angle in angles]
                arc_y = [center_y + radius * math.sin(angle) for angle in angles]

                if (abs(arc_x[-1] - target_x) > self.connection_tolerance or
                    abs(arc_y[-1] - target_y) > self.connection_tolerance):
                    arc_x.append(target_x)
                    arc_y.append(target_y)

                line_artist = self.ax.plot(arc_x, arc_y, line_color, linewidth=2,
                                           label=self._add_plot_label(label_text))[0]
                center_marker_artist = self.ax.plot(center_x, center_y, 'x', color='purple', markersize=8,
                                                    label=self._add_plot_label('Centre Arc'))[0]
                center_text_artist = self.ax.text(center_x + 0.05, center_y + 0.05, f'C({center_x:.2f},{center_y:.2f})', color='purple', fontsize=7, ha='left', va='bottom')
                target_marker_artist = self.ax.plot(target_x, target_y, marker_color, markersize=4)[0]
                target_text_artist = self.ax.text(target_x + 0.05, target_y + 0.05, f'A({target_x:.2f},{target_y:.2f})', color=text_color, fontsize=7, ha='left', va='bottom')
                current_plotted_artists.extend([line_artist, center_marker_artist, center_text_artist, target_marker_artist, target_text_artist])
            
            self.gcode_line_map[i] = len(self.plotted_elements)
            self.plotted_elements.append(current_plotted_artists)

            current_x, current_y = target_x, target_y
            end_point_of_path = (current_x, current_y)
        
        if end_point_of_path[0] is not None:
            artist_end_marker = self.ax.plot(end_point_of_path[0], end_point_of_path[1], 's', color='darkred', markersize=10,
                                 label=self._add_plot_label(f'Fin'))[0]
            artist_end_text = self.ax.text(end_point_of_path[0] + 0.05, end_point_of_path[1] + 0.05, f'Fin\n({end_point_of_path[0]:.2f},{end_point_of_path[1]:.2f})', color='darkred', fontsize=8, ha='left', va='bottom')

        self.ax.legend(loc='best', fontsize=9)
        self.ax.figure.canvas.draw_idle()


    def highlight_elements(self, gcode_line_index, color='yellow', linewidth_scale=2.0, marker_size_scale=1.5):
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
                elif isinstance(element, plt.Artist):
                    if hasattr(element, 'get_markerfacecolor') and element.get_markerfacecolor() not in ['none', (0.0, 0.0, 0.0, 0.0)]:
                        element.set_markerfacecolor(self._original_colors[element])
                    if hasattr(element, 'get_markeredgecolor'):
                        element.set_markeredgecolor(self._original_colors[element])
                    if hasattr(element, 'set_markersize') and hasattr(element, 'get_markersize'):
                            self._original_markersizes[element] = element.get_markersize()
                            element.set_markersize(self._original_markersizes[element])
                    
                    # Ensure marker color reset for all relevant artists (e.g. 'o', 'x', 's')
                    if hasattr(element, 'get_markerfacecolor'):
                        element.set_markerfacecolor(self._original_colors[element])
                    if hasattr(element, 'get_markeredgecolor'):
                        element.set_markeredgecolor(self._original_colors[element])
                            
        self.current_highlighted_elements = []

        if gcode_line_index in self.gcode_line_map:
            plot_elements_idx = self.gcode_line_map[gcode_line_index]
            
            if plot_elements_idx < len(self.plotted_elements):
                artists_to_highlight = self.plotted_elements[plot_elements_idx]
                
                for element in artists_to_highlight:
                    if isinstance(element, plt.Line2D):
                        self._original_colors[element] = element.get_color()
                        self._original_linewidths[element] = element.get_linewidth()
                        if hasattr(element, 'get_markersize') and element.get_markersize() > 0:
                             self._original_markersizes[element] = element.get_markersize()
                        element.set_color(color)
                        element.set_linewidth(element.get_linewidth() * linewidth_scale)
                        if hasattr(element, 'set_markersize') and element.get_markersize() > 0:
                            element.set_markersize(element.get_markersize() * marker_size_scale)
                    elif isinstance(element, plt.Text):
                        self._original_colors[element] = element.get_color()
                        element.set_color(color)
                    elif isinstance(element, plt.Artist):
                        # Store and set color for markers
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


# --- Application GUI Tkinter ---
class GcodeViewerApp:
    def __init__(self, root):
        self.root = root
        root.title("DXF to ISO G-code Viewer")

        self.dxf_converter = DxfToIsoConverter(connection_tolerance=1e-4)
        self.current_dxf_entities = {} 
        self.ordered_segments_for_gui = [] 

        # --- Load Icons ---
        # NOTE: For best results, use GIF files that are already sized appropriately (e.g., 20x20 or 24x24 pixels).
        # Tkinter's PhotoImage does not have built-in high-quality resizing for all image types.
        # If you need advanced resizing for PNGs or JPEGs, consider using the Pillow library (pip install Pillow).
        # Example with Pillow:
        # from PIL import Image, ImageTk
        # original_image = Image.open(icon_path)
        # resized_image = original_image.resize((24, 24), Image.LANCZOS) # Use LANCZOS for better quality
        # self.icons[name] = ImageTk.PhotoImage(resized_image)
        
        self.icons = {}
        icon_names = {
            "arrow_up": "arrow_up.gif",
            "arrow_down": "arrow_down.gif",
            "reverse": "reverse.gif",
            "delete": "delete.gif"
        }
        for name, filename in icon_names.items():
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                icon_path = os.path.join(script_dir, filename)
                
                if os.path.exists(icon_path):
                    self.icons[name] = tk.PhotoImage(file=icon_path)
                else:
                    messagebox.showwarning("Icône manquante", f"Fichier d'icône '{filename}' introuvable à l'emplacement '{icon_path}'. Les boutons seront sans icône.")
                    self.icons[name] = None
            except Exception as e:
                messagebox.showwarning("Erreur Icône", f"Erreur de chargement de l'icône '{filename}': {e}. Le bouton sera sans icône.")
                self.icons[name] = None


        # --- Main Layout Frames ---
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Top Section: Segment List and Controls
        self.top_section_frame = ttk.LabelFrame(self.main_frame, text="Ordre des Éléments", padding="5")
        self.top_section_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))

        # Listbox for segments
        self.listbox_frame = ttk.Frame(self.top_section_frame)
        self.listbox_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.segment_listbox = tk.Listbox(self.listbox_frame, width=40, height=15, selectmode=tk.SINGLE, font=("TkFixedFont", 10))
        self.segment_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.segment_listbox.bind("<Double-Button-1>", self.on_listbox_double_click)
        
        self.listbox_scrollbar = ttk.Scrollbar(self.listbox_frame, orient=tk.VERTICAL, command=self.segment_listbox.yview)
        self.listbox_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.segment_listbox.config(yscrollcommand=self.listbox_scrollbar.set)

        # Buttons for list manipulation (right of listbox)
        self.list_controls_frame = ttk.Frame(self.top_section_frame, padding="2") # Reduced padding
        self.list_controls_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))

        # Use icon if available, otherwise fallback to text
        # Added 'width' to buttons to control their size if no image or small image
        self.move_up_button = ttk.Button(self.list_controls_frame, text="Monter", command=self.move_segment_up, 
                                         image=self.icons["arrow_up"],
                                         compound=tk.LEFT if self.icons["arrow_up"] else tk.NONE,
                                         width=8) # Adjusted width
        self.move_up_button.pack(fill=tk.X, pady=1) # Reduced pady

        self.move_down_button = ttk.Button(self.list_controls_frame, text="Descendre", command=self.move_segment_down,
                                           image=self.icons["arrow_down"],
                                           compound=tk.LEFT if self.icons["arrow_down"] else tk.NONE,
                                           width=8) # Adjusted width
        self.move_down_button.pack(fill=tk.X, pady=1)

        self.reverse_button = ttk.Button(self.list_controls_frame, text="Inverser Sens", command=self.reverse_selected_segment,
                                         image=self.icons["reverse"],
                                         compound=tk.LEFT if self.icons["reverse"] else tk.NONE,
                                         width=8) # Adjusted width
        self.reverse_button.pack(fill=tk.X, pady=1)

        self.delete_button = ttk.Button(self.list_controls_frame, text="Supprimer", command=self.delete_selected_segment,
                                        image=self.icons["delete"],
                                        compound=tk.LEFT if self.icons["delete"] else tk.NONE,
                                        width=8) # Adjusted width
        self.delete_button.pack(fill=tk.X, pady=1)

        # Bottom Section: G-code Text and Plot (two columns)
        self.bottom_section_frame = ttk.Frame(self.main_frame)
        self.bottom_section_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(5,0))

        # G-code Frame (left, narrow column)
        self.gcode_frame = ttk.LabelFrame(self.bottom_section_frame, text="Code G-code Généré", padding="5")
        self.gcode_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 5))

        self.gcode_text = scrolledtext.ScrolledText(self.gcode_frame, wrap=tk.WORD, width=50, height=15, font=("Courier New", 10))
        self.gcode_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.gcode_text.bind("<ButtonRelease-1>", self.on_gcode_text_click)
        self.gcode_text.tag_configure("highlight", background="lightblue")

        # Plot Frame (right, expands)
        self.plot_frame = ttk.LabelFrame(self.bottom_section_frame, text="Visualisation du Trajet", padding="5")
        self.plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        # Matplotlib Integration
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_frame)
        self.toolbar.update()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.visualizer = IsoPathVisualizer(self.ax)

        # --- Initialisation au démarrage ---
        # Programme l'appel à load_dxf_file après que la fenêtre soit rendue
        root.after(100, self.load_dxf_file_on_startup)


    def _update_segment_listbox(self):
        """Clears and repopulates the segment listbox from self.ordered_segments_for_gui."""
        self.segment_listbox.delete(0, tk.END)
        for segment_data in self.ordered_segments_for_gui:
            self.segment_listbox.insert(tk.END, segment_data['id_display'])

    def load_dxf_file_on_startup(self):
        """Called once at startup to prompt for DXF file."""
        self.load_dxf_file() 

    def load_dxf_file(self):
        filepath = filedialog.askopenfilename(
            title="Sélectionner un fichier DXF",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")]
        )
        if filepath:
            self.current_dxf_file = filepath
            self.current_dxf_entities = self.dxf_converter._extract_dxf_entities(filepath)
            
            # Debugging print to confirm entities are loaded
            print(f"Loaded {len(self.current_dxf_entities)} entities from DXF.") 

            if self.current_dxf_entities is None or not self.current_dxf_entities: # Extraction failed or no entities found
                self.current_dxf_file = None
                self.current_dxf_entities = {}
                self.gcode_text.delete(1.0, tk.END)
                self.visualizer.reset_plot()
                self.ordered_segments_for_gui = []
                self._update_segment_listbox()
                # messagebox.showerror("Erreur de chargement", "Impossible de charger les entités DXF ou aucune entité valide trouvée. Veuillez vérifier le fichier.") # Removed for less popups
            else:
                self.ordered_segments_for_gui = [] # Clear previous order
                self.generate_gcode_auto(start_entity_data=None) # Trigger auto-generation
        else:
            # If user cancels file selection, and no file was previously loaded, close app
            if not hasattr(self, 'current_dxf_file') or not self.current_dxf_file:
                messagebox.showinfo("Annulé", "Aucun fichier DXF sélectionné. L'application va se fermer.")
                self.root.destroy()
            else: 
                # User cancelled, but a file was already loaded, do nothing
                pass

    def generate_gcode_auto(self, start_entity_data=None):
        if not self.current_dxf_entities:
            # This is fine, if no entities, just clear display
            self.gcode_text.delete(1.0, tk.END)
            self.visualizer.reset_plot()
            self.ordered_segments_for_gui = []
            self._update_segment_listbox()
            # messagebox.showwarning("Avertissement", "Aucune entité DXF à traiter pour la génération automatique.") # Removed for less popups
            return

        remaining_entities_copy = {}
        for original_id, data in self.current_dxf_entities.items():
            copied_data = copy.deepcopy(data)
            copied_data['original_ezdxf_entity'] = data['original_ezdxf_entity'].copy()
            remaining_entities_copy[original_id] = copied_data

        ordered_segments_local = []
        current_active_point = list((0.0, 0.0))

        if start_entity_data:
            target_original_id = start_entity_data['original_id']
            if target_original_id in remaining_entities_copy:
                first_segment_data = remaining_entities_copy.pop(target_original_id)
                if start_entity_data['reversed'] != first_segment_data['reversed']:
                    self.dxf_converter._reverse_segment_direction_internal(first_segment_data)
                
                ordered_segments_local.append(first_segment_data)
                
                if first_segment_data['type'] == 'LINE':
                    current_active_point[0] = first_segment_data['coords']['end'][0]
                    current_active_point[1] = first_segment_data['coords']['end'][1]
                elif first_segment_data['type'] == 'ARC':
                    current_active_point[0] = first_segment_data['coords']['end_point'][0]
                    current_active_point[1] = first_segment_data['coords']['end_point'][1]
            else:
                messagebox.showwarning("Erreur de Démarrage", "L'élément de départ sélectionné n'a pas pu être trouvé pour la régénération. Tentative de démarrage par défaut.")
                self.generate_gcode_auto(start_entity_data=None) 
                return
        else:
            initial_segment_id, initial_should_reverse, _ = self.dxf_converter._get_best_candidate_info(current_active_point, remaining_entities_copy)
            if initial_segment_id is not None:
                first_segment_data = remaining_entities_copy.pop(initial_segment_id)
                if initial_should_reverse:
                    self.dxf_converter._reverse_segment_direction_internal(first_segment_data)
                ordered_segments_local.append(first_segment_data)
                
                if first_segment_data['type'] == 'LINE':
                    current_active_point[0] = first_segment_data['coords']['end'][0]
                    current_active_point[1] = first_segment_data['coords']['end'][1]
                elif first_segment_data['type'] == 'ARC':
                    current_active_point[0] = first_segment_data['coords']['end_point'][0]
                    current_active_point[1] = first_segment_data['coords']['end_point'][1]
            else:
                # This block is hit if current_dxf_entities is not empty, but _get_best_candidate_info finds nothing.
                # This could happen if, e.g., the DXF contains only non-LINE/ARC entities.
                messagebox.showwarning("Génération G-code", "Aucun segment LINE ou ARC valide trouvé pour démarrer la conversion automatique. La liste restera vide.")
                self.ordered_segments_for_gui = []
                self._update_segment_listbox()
                self.gcode_text.delete(1.0, tk.END)
                self.visualizer.reset_plot()
                return

        while remaining_entities_copy:
            next_match_id, next_should_reverse, connection_dist = self.dxf_converter._get_best_candidate_info(current_active_point, remaining_entities_copy)
            if next_match_id is not None:
                next_segment_data = remaining_entities_copy.pop(next_match_id)
                if next_should_reverse:
                    self.dxf_converter._reverse_segment_direction_internal(next_segment_data)
                ordered_segments_local.append(next_segment_data)
                
                if next_segment_data['type'] == 'LINE':
                    current_active_point[0] = next_segment_data['coords']['end'][0]
                    current_active_point[1] = next_segment_data['coords']['end'][1]
                elif next_segment_data['type'] == 'ARC':
                    current_active_point[0] = next_segment_data['coords']['end_point'][0]
                    current_active_point[1] = next_segment_data['coords']['end_point'][1]
            else:
                # No more connected segments found
                break

        self.ordered_segments_for_gui = ordered_segments_local
        self._update_segment_listbox()
        self.generate_gcode_reordered()


    def generate_gcode_reordered(self):
        """Generates G-code based on the current order in self.ordered_segments_for_gui."""
        if not self.ordered_segments_for_gui:
            self.gcode_text.delete(1.0, tk.END)
            self.visualizer.reset_plot()
            return
        
        generated_gcode = self.dxf_converter._generate_iso_gcode("temp_path.iso", self.ordered_segments_for_gui, (0.0, 0.0))
        if generated_gcode:
            self.gcode_text.delete(1.0, tk.END)
            self.gcode_text.insert(tk.END, generated_gcode)
            self.visualizer.visualize(generated_gcode)


    def on_gcode_text_click(self, event):
        index = self.gcode_text.index(tk.CURRENT)
        line_num = int(float(index))
        gcode_line_index = line_num - 1 
        
        self.gcode_text.tag_remove("highlight", 1.0, tk.END)
        self.gcode_text.tag_add("highlight", f"{line_num}.0", f"{line_num}.end")

        self.visualizer.highlight_elements(gcode_line_index)

    def on_listbox_double_click(self, event):
        selected_indices = self.segment_listbox.curselection()
        if not selected_indices:
            return

        selected_index = selected_indices[0]
        selected_segment_data = self.ordered_segments_for_gui[selected_index]
        
        if messagebox.askyesno("Recommencer Auto", f"Voulez-vous régénérer le chemin automatiquement en commençant par '{selected_segment_data['id_display']}' ?\n(Toutes les modifications manuelles de l'ordre seront perdues.)"):
            self.generate_gcode_auto(start_entity_data=copy.deepcopy(selected_segment_data))


    def move_segment_up(self):
        selected_indices = self.segment_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Déplacement", "Veuillez sélectionner un segment à déplacer.")
            return

        idx = selected_indices[0]
        if idx > 0:
            segment = self.ordered_segments_for_gui.pop(idx)
            self.ordered_segments_for_gui.insert(idx - 1, segment)
            self._update_segment_listbox()
            self.segment_listbox.selection_set(idx - 1)
            self.generate_gcode_reordered()

    def move_segment_down(self):
        selected_indices = self.segment_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Déplacement", "Veuillez sélectionner un segment à déplacer.")
            return

        idx = selected_indices[0]
        if idx < len(self.ordered_segments_for_gui) - 1:
            segment = self.ordered_segments_for_gui.pop(idx)
            self.ordered_segments_for_gui.insert(idx + 1, segment)
            self._update_segment_listbox()
            self.segment_listbox.selection_set(idx + 1)
            self.generate_gcode_reordered()

    def reverse_selected_segment(self):
        selected_indices = self.segment_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Inverser", "Veuillez sélectionner un segment à inverser.")
            return

        idx = selected_indices[0]
        segment_data = self.ordered_segments_for_gui[idx]
        
        self.dxf_converter._reverse_segment_direction_internal(segment_data)
        
        self.segment_listbox.delete(idx)
        self.segment_listbox.insert(idx, segment_data['id_display'])
        self.segment_listbox.selection_set(idx) # Re-select the item at its current position
        
        self.generate_gcode_reordered()

    def delete_selected_segment(self):
        selected_indices = self.segment_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Supprimer", "Veuillez sélectionner un segment à supprimer.")
            return

        idx = selected_indices[0]
        segment_to_delete = self.ordered_segments_for_gui[idx]
        
        if messagebox.askyesno("Supprimer Segment", f"Êtes-vous sûr de vouloir supprimer le segment '{segment_to_delete['id_display']}' de la liste ?"):
            self.ordered_segments_for_gui.pop(idx)
            self._update_segment_listbox()
            self.generate_gcode_reordered()


if __name__ == "__main__":
    root = tk.Tk()
    app = GcodeViewerApp(root)
    root.mainloop()
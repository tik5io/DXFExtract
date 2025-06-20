import matplotlib.pyplot as plt
import math
import re # For parsing G-code lines
import sys # For sys.float_info.epsilon
import ezdxf # Make sure you have this installed: pip install ezdxf

class DxfToIsoConverter:
    """
    A class to convert DXF LINE and ARC entities into ISO G-code,
    with options for automated or assisted path ordering.
    Automatically adds G00 jumps if discontinuities are detected.
    """
    def __init__(self, connection_tolerance=1e-4):
        """
        Initializes the converter.

        Args:
            connection_tolerance (float): Maximum distance between two points
                                         to be considered connected. If the distance
                                         exceeds this, a G00 jump will be inserted.
        """
        self.connection_tolerance = connection_tolerance
        # These are instance variables used primarily by the automated 'convert' method
        # or for internal tracking during extraction.
        self.ordered_segments = [] 
        self.remaining_entities = {}

    def _extract_dxf_entities(self, dxf_filepath):
        """
        Extracts LINE and ARC entities from a DXF file.
        Stores original entity and its properties (start, end, center, radius, angles).
        """
        entities_data = {}
        current_id = 1
        
        print(f"Extracting entities from: {dxf_filepath}")

        try:
            doc = ezdxf.readfile(dxf_filepath)
            msp = doc.modelspace()

            for entity in msp:
                if entity.dxftype() == 'LINE':
                    # Clone entity to allow modification without affecting doc
                    cloned_entity = entity.copy() 
                    start = cloned_entity.dxf.start
                    end = cloned_entity.dxf.end
                    entities_data[current_id] = {
                        'type': 'LINE',
                        'original_entity': cloned_entity,
                        'coords': {
                            'start': (start.x, start.y),
                            'end': (end.x, end.y)
                        },
                        'reversed': False
                    }
                    current_id += 1
                elif entity.dxftype() == 'ARC':
                    cloned_entity = entity.copy()
                    center = cloned_entity.dxf.center
                    arc_start_point = cloned_entity.start_point
                    arc_end_point = cloned_entity.end_point

                    entities_data[current_id] = {
                        'type': 'ARC',
                        'original_entity': cloned_entity,
                        'coords': {
                            'center': (center.x, center.y),
                            'start_point': (arc_start_point.x, arc_start_point.y),
                            'end_point': (arc_end_point.x, arc_end_point.y),
                            'radius': cloned_entity.dxf.radius,
                            'start_angle': cloned_entity.dxf.start_angle,
                            'end_angle': cloned_entity.dxf.end_angle
                        },
                        'reversed': False
                    }
                    current_id += 1
                # Other entities are ignored.

        except FileNotFoundError:
            print(f"Error: DXF file '{dxf_filepath}' not found.")
            return None
        except ezdxf.DXFError as e:
            print(f"Error reading DXF file: {e}")
            print("Ensure the file is a valid and uncorrupted DXF.")
            return None
        except Exception as e:
            print(f"An unexpected error occurred during DXF extraction: {e}")
            return None

        print(f"Extracted {len(entities_data)} entities.")
        return entities_data

    def _reverse_segment_direction_internal(self, entity_data):
        """
        Internally reverses the direction of a segment (LINE or ARC).
        Updates the original_entity's DXF properties and the 'coords' dictionary.
        """
        entity = entity_data['original_entity']
        
        if entity_data['type'] == 'LINE':
            start_point_orig = entity.dxf.start
            entity.dxf.start = entity.dxf.end
            entity.dxf.end = start_point_orig
            
            # Mettre à jour les coordonnées dans le dictionnaire 'coords'
            entity_data['coords']['start'] = (entity.dxf.start.x, entity.dxf.start.y)
            entity_data['coords']['end'] = (entity.dxf.end.x, entity.dxf.end.y)
            
        elif entity_data['type'] == 'ARC':
            start_angle_orig = entity.dxf.start_angle
            entity.dxf.start_angle = entity.dxf.end_angle
            entity.dxf.end_angle = start_angle_orig
            
            # Ces propriétés (start_point/end_point) sont calculées dynamiquement par ezdxf
            # en fonction des angles et du centre, donc les récupérer à nouveau.
            entity_data['coords']['start_point'] = (entity.start_point.x, entity.start_point.y)
            entity_data['coords']['end_point'] = (entity.end_point.x, entity.end_point.y)
            entity_data['coords']['start_angle'] = entity.dxf.start_angle # Update stored angles
            entity_data['coords']['end_angle'] = entity.dxf.end_angle

        entity_data['reversed'] = not entity_data['reversed']

    def _get_best_candidate_info(self, reference_point, entities_to_search):
        """
        Finds the best segment candidate (closest connection) from a given set of entities
        to the reference_point.

        Args:
            reference_point (tuple): (x, y) coordinates to connect from.
            entities_to_search (dict): Dictionary of segments to search through.

        Returns:
            tuple: (best_segment_id, should_reverse, connection_distance)
                   Returns (None, False, float('inf')) if no candidates.
        """
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

    def _generate_iso_gcode(self, output_filepath, ordered_segments, initial_start_point=(0.0, 0.0)):
        """
        Generates an ISO G-code file from the provided ordered segments.
        Uses G01 for lines and G02 for clockwise arcs.
        Automatically inserts G00 jumps if disconnections are detected.
        """
        current_x = initial_start_point[0]
        current_y = initial_start_point[1]

        try:
            with open(output_filepath, 'w') as f:
                line_num = 10
                
                # If there are no segments, just write program end
                if not ordered_segments:
                    f.write("N9999 M02\n")
                    print("No segments to generate G-code for.")
                    return True

                for i, segment_data in enumerate(ordered_segments):
                    entity_type = segment_data['type']
                    # entity = segment_data['original_entity'] # This is the ezdxf entity object
                    
                    # Ensure we use the current state of coords from segment_data dictionary
                    # as it reflects any reversals.
                    coords = segment_data['coords'] 

                    # Determine the true start and end points of the current segment
                    # These coordinates are already updated by _reverse_segment_direction_internal if needed
                    if entity_type == 'LINE':
                        segment_start_x = coords['start'][0]
                        segment_start_y = coords['start'][1]
                        segment_end_x = coords['end'][0]
                        segment_end_y = coords['end'][1]
                    elif entity_type == 'ARC':
                        segment_start_x = coords['start_point'][0]
                        segment_start_y = coords['start_point'][1]
                        segment_end_x = coords['end_point'][0]
                        segment_end_y = coords['end_point'][1]
                    
                    # Check for discontinuity (except for the very first implicit move)
                    distance_to_segment_start = math.hypot(current_x - segment_start_x, current_y - segment_start_y)
                    
                    if i == 0:
                        # For the first segment, always generate a G00 to its start
                        # unless it's already exactly at the initial_start_point.
                        # Using a small epsilon for float comparison
                        if distance_to_segment_start > sys.float_info.epsilon:
                            f.write(f"N{line_num} G00 X{segment_start_x:.4f} Y{segment_start_y:.4f}\n")
                            line_num += 10
                    else:
                        # For subsequent segments, if current position is not connected
                        # to the segment's start within tolerance, insert G00.
                        if distance_to_segment_start > self.connection_tolerance:
                            print(f"  --> Warning: Discontinuity detected before segment {i+1}. Inserting G00 jump to ({segment_start_x:.4f}, {segment_start_y:.4f}).")
                            f.write(f"N{line_num} G00 X{segment_start_x:.4f} Y{segment_start_y:.4f}\n")
                            line_num += 10

                    # Update current position to the start of the current segment for G-code calculation
                    current_x = segment_start_x
                    current_y = segment_start_y

                    # Generate G-code for the segment
                    if entity_type == 'LINE':
                        f.write(f"N{line_num} G01 X{segment_end_x:.4f} Y{segment_end_y:.4f}\n")
                    elif entity_type == 'ARC':
                        arc_center_x = coords['center'][0] # Use coords from dictionary
                        arc_center_y = coords['center'][1] # Use coords from dictionary
                        
                        # Calculate relative I, J from current_x, current_y (segment_start_x, segment_start_y) to center
                        i_rel = arc_center_x - current_x
                        j_rel = arc_center_y - current_y

                        # Determine G-code command (G02 for CW, G03 for CCW) based on 'reversed' flag
                        # DXF arcs are inherently defined CCW from start_angle to end_angle.
                        # If the segment was reversed, we want to traverse it CW (G02).
                        # If not reversed, we traverse it CCW (G03).
                        if segment_data['reversed']:
                            gcode_command = "G02" # Clockwise
                        else:
                            gcode_command = "G03" # Counter-clockwise
                        
                        f.write(f"N{line_num} {gcode_command} X{segment_end_x:.4f} Y{segment_end_y:.4f} I{i_rel:.4f} J{j_rel:.4f}\n")
                    
                    # Update current position to the end of the current segment for the next iteration
                    current_x = segment_end_x
                    current_y = segment_end_y
                    line_num += 10
                
                f.write("N9999 M02\n") # Program end

            print(f"ISO G-code file '{output_filepath}' generated successfully.")
            return True
        except Exception as e:
            print(f"Error generating ISO G-code file: {e}")
            return False

    def convert(self, dxf_filepath, iso_output_filepath, start_point=(0.0, 0.0)):
        """
        Automatically converts a DXF file to an ISO G-code file,
        ordering segments to form a continuous path. This is the fully automated mode.

        Args:
            dxf_filepath (str): Path to the input DXF file.
            iso_output_filepath (str): Path for the generated ISO G-code file.
            start_point (tuple): (x, y) coordinates of the initial tool position.

        Returns:
            bool: True if conversion was successful, False otherwise.
        """
        remaining_entities = self._extract_dxf_entities(dxf_filepath)
        if not remaining_entities:
            return False

        ordered_segments = []
        current_active_point = list(start_point) 

        # 1. Find the first segment (closest to the initial start_point)
        # This part of the automated conversion will still try to connect
        # to the closest end for the *first* segment it picks.
        # This is behavior for FULLY AUTOMATED conversion, not interactive.
        first_segment_id, first_should_reverse, _ = self._get_best_candidate_info(start_point, remaining_entities)

        if first_segment_id is not None:
            first_segment_data = remaining_entities.pop(first_segment_id)
            if first_should_reverse:
                self._reverse_segment_direction_internal(first_segment_data)
            ordered_segments.append(first_segment_data)
            
            # The *actual* current_active_point after the first segment's move
            if first_segment_data['type'] == 'LINE':
                current_active_point[0] = first_segment_data['coords']['end'][0]
                current_active_point[1] = first_segment_data['coords']['end'][1]
            elif first_segment_data['type'] == 'ARC':
                current_active_point[0] = first_segment_data['coords']['end_point'][0]
                current_active_point[1] = first_segment_data['coords']['end_point'][1]
            print(f"First segment (ID {first_segment_id}) selected automatically. Current position: ({current_active_point[0]:.4f}, {current_active_point[1]:.4f})")
        else:
            print("No segments found in DXF file that can be selected as the first segment for automated processing.")
            return False

        # 2. Iteratively find subsequent connecting segments
        while remaining_entities:
            next_match_id, next_should_reverse, connection_dist = self._get_best_candidate_info(current_active_point, remaining_entities)
            
            if next_match_id is not None: # We always pick the closest, even if it requires a jump
                next_segment_data = remaining_entities.pop(next_match_id)

                if next_should_reverse:
                    self._reverse_segment_direction_internal(next_segment_data) 
                
                ordered_segments.append(next_segment_data)
                
                if next_segment_data['type'] == 'LINE':
                    current_active_point[0] = next_segment_data['coords']['end'][0]
                    current_active_point[1] = next_segment_data['coords']['end'][1]
                elif next_segment_data['type'] == 'ARC':
                    current_active_point[0] = next_segment_data['coords']['end_point'][0]
                    current_active_point[1] = next_segment_data['coords']['end_point'][1]
                
            else:
                print(f"Warning: No more segments could be connected to point ({current_active_point[0]:.4f}, {current_active_point[1]:.4f}).")
                print("Remaining entities will not be processed by this automated run.")
                break # Stop ordering if no more segments can be found, even if far apart.

        if remaining_entities:
            print(f"Note: {len(remaining_entities)} entities could not be connected automatically and were skipped.")

        return self._generate_iso_gcode(iso_output_filepath, ordered_segments, start_point)

    @staticmethod
    def display_available_entities(entities_data):
        """Displays available entities with their IDs and coordinates to the console."""
        if not entities_data:
            print("\nNo more entities available for reordering.")
            return False
        
        print("\n--- Available Elements for Reordering ---")
        for entity_id, data in entities_data.items():
            coords = data['coords']
            is_reversed_flag = "[REVERSED]" if data['reversed'] else ""
            
            if data['type'] == 'LINE':
                print(f"  ID {entity_id}: LINE {is_reversed_flag} - Start(X={coords['start'][0]:.4f}, Y={coords['start'][1]:.4f}) / End(X={coords['end'][0]:.4f}, Y={coords['end'][1]:.4f})")
            elif data['type'] == 'ARC':
                # For display, show DXF's raw angles, but note they might be reversed for toolpath
                original_start_angle = data['original_entity'].dxf.start_angle
                original_end_angle = data['original_entity'].dxf.end_angle
                print(f"  ID {entity_id}: ARC {is_reversed_flag} - Center(X={coords['center'][0]:.4f}, Y={coords['center'][1]:.4f}) / Start(X={coords['start_point'][0]:.4f}, Y={coords['start_point'][1]:.4f}) / End(X={coords['end_point'][0]:.4f}, Y={coords['end_point'][1]:.4f}) (Angles: {original_start_angle:.2f}° to {original_end_angle:.2f}°)")
        print("-----------------------------------------")
        return True


class IsoPathVisualizer:
    """
    A class to visualize CNC paths from ISO G-code files.
    It interprets G00, G01, G02, and G03 commands to render the tool's trajectory.
    """
    def __init__(self):
        self.fig, self.ax = plt.subplots(figsize=(10, 8))
        self.ax.set_title("Visualisation du Trajet CNC (G-code ISO)", fontsize=14)
        self.ax.set_xlabel("X Coordonnée")
        self.ax.set_ylabel("Y Coordonnée")
        self.ax.grid(True)
        self.ax.set_aspect('equal', adjustable='box')

        # To avoid duplicate labels in legend
        self._legend_labels = set()
        self.connection_tolerance = 1e-4 # Use a tolerance for arc end point check

    def _add_plot_label(self, label):
        """Adds a label to the set of seen labels to avoid duplicates in the legend."""
        if label not in self._legend_labels:
            self._legend_labels.add(label)
            return label
        return None

    def _parse_gcode_line(self, line):
        """
        Parses a single G-code line to extract command and coordinates.
        Returns a dictionary with parsed data.
        """
        parsed_data = {
            'command': None,
            'X': None,
            'Y': None,
            'I': None,
            'J': None
        }
        
        # Remove line number (N...) and comments (;)
        line = re.sub(r'N\d+\s*', '', line).split(';')[0].strip()
        if not line:
            return None

        parts = line.split()
        if not parts:
            return None

        # Extract command (e.g., G00, G01, G02, G03)
        parsed_data['command'] = parts[0]

        # Extract X, Y, I, J values
        for part in parts[1:]:
            if part.startswith('X'):
                parsed_data['X'] = float(part[1:])
            elif part.startswith('Y'):
                parsed_data['Y'] = float(part[1:])
            elif part.startswith('I'):
                parsed_data['I'] = float(part[1:])
            elif part.startswith('J'):
                parsed_data['J'] = float(part[1:])
        
        return parsed_data

    def visualize(self, iso_filepath):
        """
        Reads an ISO G-code file and plots the CNC path.

        Args:
            iso_filepath (str): Path to the input ISO G-code file.
        """
        current_x, current_y = 0.0, 0.0  # Tool starts at origin (0,0) as per typical CNC initial state

        # Markers for key points
        start_point_marked = False
        end_point_of_path = (None, None)

        print(f"Reading and visualizing G-code from: {iso_filepath}")

        try:
            with open(iso_filepath, 'r') as f:
                gcode_lines = f.readlines()

            for i, line in enumerate(gcode_lines):
                parsed = self._parse_gcode_line(line)
                if parsed is None or parsed['command'] is None:
                    continue

                command = parsed['command']
                target_x = parsed['X'] if parsed['X'] is not None else current_x
                target_y = parsed['Y'] if parsed['Y'] is not None else current_y

                # Mark the overall start point once, based on the initial current_x,y
                if not start_point_marked:
                    self.ax.plot(current_x, current_y, 'o', color='gold', markersize=10, 
                                 label=self._add_plot_label(f'Départ'))
                    self.ax.text(current_x + 0.05, current_y + 0.05, f'D({current_x:.2f},{current_y:.2f})', color='gold', fontsize=8, ha='left', va='bottom')
                    start_point_marked = True

                # Determine G-code type and plot
                if command == 'G00':  # Rapid traverse
                    self.ax.plot([current_x, target_x], [current_y, target_y], 'r--', alpha=0.7, 
                                 label=self._add_plot_label('G00 (Rapide)'))
                    # Mark the target point of the rapid move
                    self.ax.plot(target_x, target_y, 'ro', markersize=4)
                    self.ax.text(target_x + 0.05, target_y + 0.05, f'R({target_x:.2f},{target_y:.2f})', color='red', fontsize=7, ha='left', va='bottom')

                elif command == 'G01':  # Linear interpolation
                    self.ax.plot([current_x, target_x], [current_y, target_y], 'b-', linewidth=2, 
                                 label=self._add_plot_label('G01 (Linéaire)'))
                    # Mark the target point of the linear move
                    self.ax.plot(target_x, target_y, 'bo', markersize=4)
                    self.ax.text(target_x + 0.05, target_y + 0.05, f'L({target_x:.2f},{target_y:.2f})', color='blue', fontsize=7, ha='left', va='bottom')

                elif command == 'G02' or command == 'G03':  # Circular interpolation (G02 CW, G03 CCW)
                    i_offset = parsed['I'] if parsed['I'] is not None else 0.0
                    j_offset = parsed['J'] if parsed['J'] is not None else 0.0
                    
                    center_x = current_x + i_offset
                    center_y = current_y + j_offset
                    
                    radius = math.hypot(i_offset, j_offset)

                    # Calculate start and end angles
                    start_angle_rad = math.atan2(current_y - center_y, current_x - center_x)
                    end_angle_rad = math.atan2(target_y - center_y, target_x - center_y)

                    # Normalize angles to [0, 2*PI)
                    start_angle_rad = (start_angle_rad + 2 * math.pi) % (2 * math.pi)
                    end_angle_rad = (end_angle_rad + 2 * math.pi) % (2 * math.pi)
                    
                    if command == 'G02': # Clockwise
                        # For G02 (clockwise), if end angle is 'ahead' of start angle (CCW),
                        # we subtract 2*pi from end angle to force a clockwise sweep.
                        if end_angle_rad >= start_angle_rad:
                            end_angle_rad -= 2 * math.pi
                        
                        line_color = 'g-' # Green for G02
                        marker_color = 'go'
                        label_text = 'G02 (Circulaire CW)'
                        text_color = 'green'
                    else: # G03 - Counter-clockwise
                        # For G03 (counter-clockwise), if end angle is 'behind' start angle (CW),
                        # we add 2*pi to end angle to force a counter-clockwise sweep.
                        if end_angle_rad <= start_angle_rad:
                            end_angle_rad += 2 * math.pi

                        line_color = 'c-' # Cyan for G03
                        marker_color = 'co'
                        label_text = 'G03 (Circulaire CCW)'
                        text_color = 'cyan'
                    
                    num_arc_points = 50
                    angles = [start_angle_rad + (end_angle_rad - start_angle_rad) * t / num_arc_points for t in range(num_arc_points + 1)]
                    
                    arc_x = [center_x + radius * math.cos(angle) for angle in angles]
                    arc_y = [center_y + radius * math.sin(angle) for angle in angles]

                    # Ensure the actual target point is the very last point in the arc
                    # to compensate for potential floating point inaccuracies.
                    if (abs(arc_x[-1] - target_x) > self.connection_tolerance or
                        abs(arc_y[-1] - target_y) > self.connection_tolerance):
                        arc_x.append(target_x)
                        arc_y.append(target_y)

                    self.ax.plot(arc_x, arc_y, line_color, linewidth=2, 
                                 label=self._add_plot_label(label_text))
                    
                    # Mark the arc center
                    self.ax.plot(center_x, center_y, 'x', color='purple', markersize=8, 
                                 label=self._add_plot_label('Centre Arc'))
                    self.ax.text(center_x + 0.05, center_y + 0.05, f'C({center_x:.2f},{center_y:.2f})', color='purple', fontsize=7, ha='left', va='bottom')
                    
                    # Mark the target point of the arc
                    self.ax.plot(target_x, target_y, marker_color, markersize=4)
                    self.ax.text(target_x + 0.05, target_y + 0.05, f'A({target_x:.2f},{target_y:.2f})', color=text_color, fontsize=7, ha='left', va='bottom')

                # Update current position for the next command
                current_x = target_x
                current_y = target_y
                
                end_point_of_path = (current_x, current_y)

            # Mark the very last point of the path
            if end_point_of_path[0] is not None:
                self.ax.plot(end_point_of_path[0], end_point_of_path[1], 's', color='darkred', markersize=10, 
                             label=self._add_plot_label(f'Fin'))
                self.ax.text(end_point_of_path[0] + 0.05, end_point_of_path[1] + 0.05, f'Fin\n({end_point_of_path[0]:.2f},{end_point_of_path[1]:.2f})', color='darkred', fontsize=8, ha='left', va='bottom')


            self.ax.legend(loc='best', fontsize=9)
            plt.show()
            print(f"Visualization complete for '{iso_filepath}'.")

        except FileNotFoundError:
            print(f"Error: ISO G-code file '{iso_filepath}' not found.")
        except Exception as e:
            print(f"An error occurred during G-code visualization: {e}")


# --- Combined Main Execution (for demonstration) ---
if __name__ == "__main__":
    # --- Part 1: DXF to ISO Conversion (interactive) ---
    input_dxf_file = "exporttraj.dxf" # Your DXF file
    output_iso_file = "output_interactive_path.iso" # Output ISO file for both processes
    initial_start_point = (0.0, 0.0) # Starting point for the tool

    # Initialize converter with a connection tolerance for G00 jumps
    dxf_converter = DxfToIsoConverter(connection_tolerance=1e-4) 

    all_entities_dxf = dxf_converter._extract_dxf_entities(input_dxf_file)

    if all_entities_dxf is None:
        sys.exit("Exiting due to DXF extraction failure.")

    ordered_segments_for_iso = []
    # Create a copy so we can pop items without affecting the original all_entities if needed
    remaining_entities_dxf = all_entities_dxf.copy() 

    current_active_point_dxf = list(initial_start_point) # Mutable list for current position

    sequence_step = 1
    
    print("\n--- Starting Interactive Path Reordering (DXF to ISO) ---")
    print("Goal: Build your CNC path. A G00 (rapid traverse) will be inserted if jumps occur.")
    print("--------------------------------------------")
    print("Available Commands:")
    print("  <ID>        : Selects and adds the segment to the ordered path.")
    print("  S<ID>       : Reverses the direction of a segment (e.g., S1).")
    print("  END         : Finishes the ordering and generates the final ISO G-code.")
    print("  [ID]        : Press Enter to auto-select the proposed ID (if available).")
    print("--------------------------------------------")

    while True:
        # Call static method directly from the class
        if not DxfToIsoConverter.display_available_entities(remaining_entities_dxf):
            print("All segments have been ordered.")
            break

        print(f"Current active point: (X={current_active_point_dxf[0]:.4f}, Y={current_active_point_dxf[1]:.4f})")

        # --- Propose the best candidate ---
        best_candidate_id, best_should_reverse, connection_distance = dxf_converter._get_best_candidate_info(current_active_point_dxf, remaining_entities_dxf)
        
        if best_candidate_id is not None:
            proposal_text = f"Proposal: ID {best_candidate_id} (Connects from {'END' if best_should_reverse else 'START'} with distance {connection_distance:.4f})."
            if connection_distance > dxf_converter.connection_tolerance:
                 proposal_text += " This connection is **disconnected** and will cause a G00 jump."
            print(f"  {proposal_text}")
        else:
            print("  No direct connecting segments found among remaining entities.")

        selected_id = None # Initialize selected_id for current loop iteration
        action_performed = False

        user_input = input(f"Step {sequence_step}: Enter command (ID / S<ID> / END / [{best_candidate_id if best_candidate_id is not None else ''}]) : ").strip().upper()

        if user_input == "END":
            break # Exit the loop to generate G-code
        elif user_input.startswith('S') and len(user_input) > 1:
            try:
                segment_id_to_reverse = int(user_input[1:])
                if segment_id_to_reverse in remaining_entities_dxf:
                    dxf_converter._reverse_segment_direction_internal(remaining_entities_dxf[segment_id_to_reverse])
                    print(f"Segment ID {segment_id_to_reverse} direction reversed.")
                else:
                    print(f"Error: ID '{segment_id_to_reverse}' not valid or already selected.")
            except ValueError:
                print("Invalid 'S<ID>' format. ID must be a number.")
            continue # Continue loop to redisplay options after reversal
        elif user_input == "": # User pressed Enter for auto-selection
            if best_candidate_id is not None:
                selected_id = best_candidate_id
                print(f"  > Auto-selecting ID {selected_id} (proposal).")
            else:
                print("No segment proposed and no ID entered. Please enter a valid ID, 'S<ID>', or 'END'.")
                continue # No valid action, ask again
        else: # User entered an explicit ID
            try:
                selected_id = int(user_input)
                if selected_id not in remaining_entities_dxf:
                    print(f"Error: ID '{selected_id}' not valid or already selected. Please choose an ID from the list.")
                    continue # Invalid ID, ask again
            except ValueError:
                print("Invalid input. Please enter a segment ID, 'S<ID>', or 'END'.")
                continue # Invalid input, ask again

        # --- Common logic for processing a selected_id ---
        if selected_id is not None:
            selected_entity_data = remaining_entities_dxf.pop(selected_id) # Remove from remaining

            should_reverse_for_connection = False # Default: no auto-reversal unless specified
            
            if sequence_step == 1:
                # For the very first segment selected by the user,
                # we always use its current direction (as extracted or manually reversed by S<ID>).
                # We do NOT perform automatic reversal based on initial_start_point closeness.
                print(f"  First segment selected (ID {selected_id}). Using its current direction.")
            else:
                # For subsequent segments, apply the closest-connection logic from the *previous* segment's end.
                seg_start = selected_entity_data['coords']['start'] if selected_entity_data['type'] == 'LINE' else selected_entity_data['coords']['start_point']
                seg_end = selected_entity_data['coords']['end'] if selected_entity_data['type'] == 'LINE' else selected_entity_data['coords']['end_point']

                dist_to_seg_start = math.hypot(current_active_point_dxf[0] - seg_start[0], current_active_point_dxf[1] - seg_start[1])
                dist_to_seg_end = math.hypot(current_active_point_dxf[0] - seg_end[0], current_active_point_dxf[1] - seg_end[1])

                if dist_to_seg_end < dist_to_seg_start:
                    should_reverse_for_connection = True
                print(f"  Connecting segment {selected_id}. Auto-reverse for connection: {should_reverse_for_connection}.")

            # Apply reversal if needed.
            # Only reverse if current state is not already desired.
            if should_reverse_for_connection and not selected_entity_data['reversed']:
                dxf_converter._reverse_segment_direction_internal(selected_entity_data)
                print(f"Segment ID {selected_id} automatically reversed for optimal connection.")
            elif not should_reverse_for_connection and selected_entity_data['reversed']:
                dxf_converter._reverse_segment_direction_internal(selected_entity_data)
                print(f"Segment ID {selected_id} automatically un-reversed for optimal connection.")
            
            ordered_segments_for_iso.append(selected_entity_data) # Add to ordered list
            
            # Update active point to the END of the selected segment for the next iteration
            if selected_entity_data['type'] == 'LINE':
                current_active_point_dxf[0] = selected_entity_data['coords']['end'][0]
                current_active_point_dxf[1] = selected_entity_data['coords']['end'][1]
            elif selected_entity_data['type'] == 'ARC':
                current_active_point_dxf[0] = selected_entity_data['coords']['end_point'][0]
                current_active_point_dxf[1] = selected_entity_data['coords']['end_point'][1]
            
            print(f"  --> Updated current active point to: (X:{current_active_point_dxf[0]:.4f}, Y:{current_active_point_dxf[1]:.4f})")
            
            sequence_step += 1
            print(f"Selected ID {selected_id}. Path now has {len(ordered_segments_for_iso)} segments.")
            action_performed = True # Indicate that a segment was processed

        # If no valid action was performed (e.g., invalid input, or no proposal was there for empty input),
        # the loop continues without advancing sequence_step or processing a segment.
        # This is implicitly handled by the `continue` statements above.
    
    # Generate final ISO file from the ordered segments
    if ordered_segments_for_iso:
        print("\n--- Generating final ISO G-code ---")
        dxf_converter._generate_iso_gcode(output_iso_file, ordered_segments_for_iso, initial_start_point)
    else:
        print("\nNo segments were selected for ordering. The ISO file has not been generated.")

    print("\nInteractive reordering process finished.")
    print("--------------------------------------------\n")

    # --- Part 2: ISO File Visualization ---
    print("\n--- Starting ISO G-code Visualization ---")
    visualizer = IsoPathVisualizer()
    visualizer.visualize(output_iso_file)
    print("ISO G-code visualization complete.")
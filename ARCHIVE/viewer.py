import matplotlib.pyplot as plt
import math
import re # For parsing G-code lines
from ARCHIVE.DxfToIsoConverter import DxfToIsoConverter


class IsoPathVisualizer:
    """
    A class to visualize CNC paths from ISO G-code files.
    It interprets G00, G01, and G02 commands to render the tool's trajectory.
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

        # Extract command (e.g., G00, G01, G02)
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
        current_x, current_y = 0.0, 0.0  # Tool starts at origin (0,0)
        overall_path_x = [current_x]
        overall_path_y = [current_y]

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

                # Mark the overall start point once
                if not start_point_marked:
                    self.ax.plot(current_x, current_y, 'o', color='gold', markersize=10, 
                                 label=self._add_plot_label(f'Départ (X:{current_x:.4f}, Y:{current_y:.4f})'))
                    self.ax.text(current_x + 0.05, current_y + 0.05, f'D(X:{current_x:.2f},Y:{current_y:.2f})', color='gold', fontsize=8, ha='left', va='bottom')
                    start_point_marked = True

                # Determine G-code type and plot
                if command == 'G00':  # Rapid traverse
                    self.ax.plot([current_x, target_x], [current_y, target_y], 'r--', alpha=0.7, 
                                 label=self._add_plot_label('G00 (Rapide)'))
                    # Mark the target point of the rapid move
                    self.ax.plot(target_x, target_y, 'ro', markersize=4)
                    self.ax.text(target_x + 0.05, target_y + 0.05, f'R(X:{target_x:.2f},Y:{target_y:.2f})', color='red', fontsize=7, ha='left', va='bottom')

                elif command == 'G01':  # Linear interpolation
                    self.ax.plot([current_x, target_x], [current_y, target_y], 'b-', linewidth=2, 
                                 label=self._add_plot_label('G01 (Linéaire)'))
                    # Mark the target point of the linear move
                    self.ax.plot(target_x, target_y, 'bo', markersize=4)
                    self.ax.text(target_x + 0.05, target_y + 0.05, f'L(X:{target_x:.2f},Y:{target_y:.2f})', color='blue', fontsize=7, ha='left', va='bottom')

                elif command == 'G02':  # Circular interpolation (clockwise)
                    i_offset = parsed['I'] if parsed['I'] is not None else 0.0
                    j_offset = parsed['J'] if parsed['J'] is not None else 0.0
                    
                    center_x = current_x + i_offset
                    center_y = current_y + j_offset
                    
                    radius = math.hypot(i_offset, j_offset)

                    # Calculate start and end angles
                    start_angle_rad = math.atan2(current_y - center_y, current_x - center_x)
                    end_angle_rad = math.atan2(target_y - center_y, target_x - center_y)
                    
                    # Adjust angles for G02 (clockwise sweep)
                    # Matplotlib's arc generation is counter-clockwise by default.
                    # For a G02 (clockwise) arc, if the end angle is 'ahead' of the start angle (CCW),
                    # we subtract 2*pi from the end angle to force a clockwise sweep.
                    if end_angle_rad >= start_angle_rad:
                        end_angle_rad -= 2 * math.pi
                    
                    num_arc_points = 50
                    angles = [start_angle_rad + (end_angle_rad - start_angle_rad) * t / num_arc_points for t in range(num_arc_points + 1)]
                    
                    arc_x = [center_x + radius * math.cos(angle) for angle in angles]
                    arc_y = [center_y + radius * math.sin(angle) for angle in angles]

                    self.ax.plot(arc_x, arc_y, 'g-', linewidth=2, 
                                 label=self._add_plot_label('G02 (Circulaire CW)'))
                    
                    # Mark the arc center
                    self.ax.plot(center_x, center_y, 'x', color='purple', markersize=8, 
                                 label=self._add_plot_label('Centre Arc'))
                    self.ax.text(center_x + 0.05, center_y + 0.05, f'C(X:{center_x:.2f},Y:{center_y:.2f})', color='purple', fontsize=7, ha='left', va='bottom')
                    
                    # Mark the target point of the arc
                    self.ax.plot(target_x, target_y, 'go', markersize=4)
                    self.ax.text(target_x + 0.05, target_y + 0.05, f'A(X:{target_x:.2f},Y:{target_y:.2f})', color='green', fontsize=7, ha='left', va='bottom')

                # Update current position for the next command
                current_x = target_x
                current_y = target_y
                
                # Add current point to overall path history
                overall_path_x.append(current_x)
                overall_path_y.append(current_y)
                end_point_of_path = (current_x, current_y)

            # Plot the overall trajectory history as a dotted line
            self.ax.plot(overall_path_x, overall_path_y, 'k:', alpha=0.5, label=self._add_plot_label('Trajet Complet'))

            # Mark the very last point of the path
            if end_point_of_path[0] is not None:
                self.ax.plot(end_point_of_path[0], end_point_of_path[1], 's', color='darkred', markersize=10, 
                             label=self._add_plot_label(f'Fin (X:{end_point_of_path[0]:.4f}, Y:{end_point_of_path[1]:.4f})'))
                self.ax.text(end_point_of_path[0] + 0.05, end_point_of_path[1] + 0.05, f'Fin\n(X:{end_point_of_path[0]:.2f},Y:{end_point_of_path[1]:.2f})', color='darkred', fontsize=8, ha='left', va='bottom')


            self.ax.legend(loc='best', fontsize=9)
            plt.show()
            print(f"Visualization complete for '{iso_filepath}'.")

        except FileNotFoundError:
            print(f"Error: ISO G-code file '{iso_filepath}' not found.")
        except Exception as e:
            print(f"An error occurred during G-code visualization: {e}")


# --- Combined Main Execution (for demonstration) ---
if __name__ == "__main__":
    # --- Part 1: DXF to ISO Conversion (interactive, as before) ---
    input_dxf_file = "exporttraj.dxf" # Your DXF file
    output_iso_file = "output_interactive_path.iso"
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
    print("--------------------------------------------")

    while True:
        if not display_available_entities(remaining_entities_dxf):
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

        user_input = input(f"Step {sequence_step}: Enter command (ID / S<ID> / END) : ").strip().upper()

        if user_input == "END":
            break
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
            continue # Continue loop to redisplay options

        else: # User entered an ID to select
            try:
                selected_id = int(user_input)
                if selected_id in remaining_entities_dxf:
                    selected_entity_data = remaining_entities_dxf.pop(selected_id) # Remove from remaining

                    # Determine if the selected segment needs reversal for optimal connection
                    seg_start = selected_entity_data['coords']['start'] if selected_entity_data['type'] == 'LINE' else selected_entity_data['coords']['start_point']
                    seg_end = selected_entity_data['coords']['end'] if selected_entity_data['type'] == 'LINE' else selected_entity_data['coords']['end_point']

                    # Calculate distance from current_active_point to both ends of the selected segment
                    dist_to_seg_start = math.hypot(current_active_point_dxf[0] - seg_start[0], current_active_point_dxf[1] - seg_start[1])
                    dist_to_seg_end = math.hypot(current_active_point_dxf[0] - seg_end[0], current_active_point_dxf[1] - seg_end[1])

                    should_reverse_for_connection = False
                    if dist_to_seg_end < dist_to_seg_start:
                        should_reverse_for_connection = True
                    
                    # If this is the very first segment, connect to its closest end from initial_start_point
                    if sequence_step == 1:
                         dist_from_initial_to_seg_start = math.hypot(initial_start_point[0] - seg_start[0], initial_start_point[1] - seg_start[1])
                         dist_from_initial_to_seg_end = math.hypot(initial_start_point[0] - seg_end[0], initial_start_point[1] - seg_end[1])
                         if dist_from_initial_to_seg_end < dist_from_initial_to_seg_start:
                             should_reverse_for_connection = True
                         else:
                             should_reverse_for_connection = False # Connect to start

                    # Apply reversal if needed
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
                    
                    sequence_step += 1
                    print(f"Selected ID {selected_id}. Path now has {len(ordered_segments_for_iso)} segments.")
                else:
                    print(f"Error: ID '{selected_id}' not valid or already selected. Please choose an ID from the list.")
            except ValueError:
                print("Invalid input. Please enter a segment ID, 'S<ID>', or 'END'.")
    
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
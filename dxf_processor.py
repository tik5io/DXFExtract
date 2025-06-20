import ezdxf
import math
import sys
import copy
import tkinter as tk
from tkinter import messagebox
import itertools

class DxfProcessor:
    """
    Handles DXF file processing, entity extraction, segment manipulation (reversing direction),
    and ISO G-code generation.
    """
    def __init__(self, connection_tolerance=1e-4):
        self.connection_tolerance = connection_tolerance
        self.unique_id_counter = itertools.count(1) # For generating unique IDs across runs

    def extract_dxf_entities(self, dxf_filepath):
        """
        Extracts LINE, ARC, and CIRCLE entities from a DXF file.
        Assigns a unique ID (1-based) to each entity.
        Returns a dictionary of entities_data {id: {type, coords, original_ezdxf_entity, id_display, reversed, original_id}}.
        For arcs, calculates 'is_clockwise' based on start/end angles.
        For circles, stores center and radius.
        Returns None on error.
        """
        entities_data = {}
        
        try:
            doc = ezdxf.readfile(dxf_filepath)
            msp = doc.modelspace()

            for entity in msp:
                entity_id = next(self.unique_id_counter) 
                cloned_entity = entity.copy() 

                if entity.dxftype() == 'LINE':
                    start_point = cloned_entity.dxf.start.xyz[:2] # X, Y only
                    end_point = cloned_entity.dxf.end.xyz[:2]     # X, Y only
                    entities_data[entity_id] = {
                        'id': entity_id,
                        'type': 'LINE',
                        'original_ezdxf_entity': cloned_entity,
                        'coords': {
                            'start_point': start_point,
                            'end_point': end_point
                        },
                        'reversed': False,
                        'original_id': entity_id,
                        'id_display': f"L{entity_id}: ({start_point[0]:.2f},{start_point[1]:.2f})->({end_point[0]:.2f},{end_point[1]:.2f})"
                    }
                elif entity.dxftype() == 'ARC':
                    center = cloned_entity.dxf.center.xyz[:2]
                    radius = cloned_entity.dxf.radius
                    start_angle_deg = cloned_entity.dxf.start_angle
                    end_angle_deg = cloned_entity.dxf.end_angle

                    start_point = cloned_entity.start_point.xyz[:2]
                    end_point = cloned_entity.end_point.xyz[:2]
                    
                    # Determine arc direction for G-code (G02=CW, G03=CCW)
                    # Normalize angles to [0, 360)
                    norm_start_angle = start_angle_deg % 360
                    norm_end_angle = end_angle_deg % 360

                    is_clockwise = False
                    if norm_start_angle < norm_end_angle:
                        if (norm_end_angle - norm_start_angle) > 180:
                            is_clockwise = True
                        else:
                            is_clockwise = False
                    elif norm_start_angle > norm_end_angle:
                        if (norm_start_angle - norm_end_angle) < 180:
                             is_clockwise = True
                        else:
                            is_clockwise = False
                    else: # start_angle == end_angle
                        is_clockwise = False # Default to CCW for full circles initially

                    entities_data[entity_id] = {
                        'id': entity_id,
                        'type': 'ARC',
                        'original_ezdxf_entity': cloned_entity,
                        'coords': {
                            'center': center,
                            'start_point': start_point,
                            'end_point': end_point,
                            'radius': radius,
                            'start_angle': start_angle_deg,
                            'end_angle': end_angle_deg,
                            'is_clockwise': is_clockwise
                        },
                        'reversed': False,
                        'original_id': entity_id,
                        'id_display': f"A{entity_id}: R{radius:.2f} ({start_point[0]:.2f},{start_point[1]:.2f})->({end_point[0]:.2f},{end_point[1]:.2f})"
                    }
                elif entity.dxftype() == 'CIRCLE': # <-- Added CIRCLE handling
                    center = cloned_entity.dxf.center.xyz[:2]
                    radius = cloned_entity.dxf.radius
                    entities_data[entity_id] = {
                        'id': entity_id,
                        'type': 'CIRCLE',
                        'original_ezdxf_entity': cloned_entity,
                        'coords': {
                            'center': center,
                            'radius': radius
                        },
                        'reversed': False, # Not directly applicable, but kept for consistency
                        'original_id': entity_id,
                        'id_display': f"C{entity_id}: R{radius:.2f} (Center:{center[0]:.2f},{center[1]:.2f})"
                    }
            
            messagebox.showinfo("DXF Chargé", f"{len(entities_data)} entités extraites du DXF.")
            return entities_data

        except FileNotFoundError:
            messagebox.showerror("Erreur", f"Fichier DXF '{dxf_filepath}' introuvable.")
            return None
        except ezdxf.DXFError as e:
            messagebox.showerror("Erreur DXF", f"Erreur de lecture du fichier DXF: {e}\nAssurez-vous que le fichier est valide.")
            return None
        except Exception as e:
            messagebox.showerror("Erreur", f"Une erreur inattendue est survenue lors de l'extraction DXF: {e}")
            return None

    def reverse_segment_direction(self, entity_data):
        """
        Reverses the direction of a segment (LINE or ARC).
        Updates the original_ezdxf_entity's DXF properties and the 'coords' dictionary.
        This modifies the passed `entity_data` dictionary in place.
        Does nothing for CIRCLE entities as their direction is inherent.
        """
        entity = entity_data['original_ezdxf_entity']

        if entity_data['type'] == 'LINE':
            start_point_orig = entity.dxf.start
            entity.dxf.start = entity.dxf.end
            entity.dxf.end = start_point_orig

            entity_data['coords']['start_point'] = (entity.dxf.start.x, entity.dxf.start.y)
            entity_data['coords']['end_point'] = (entity.dxf.end.x, entity.dxf.end.y)

        elif entity_data['type'] == 'ARC':
            start_angle_orig = entity.dxf.start_angle
            entity.dxf.start_angle = entity.dxf.end_angle
            entity.dxf.end_angle = start_angle_orig

            entity_data['coords']['start_point'] = (entity.start_point.x, entity.start_point.y)
            entity_data['coords']['end_point'] = (entity.end_point.x, entity.end_point.y)
            entity_data['coords']['start_angle'] = entity.dxf.start_angle
            entity_data['coords']['end_angle'] = entity.dxf.end_angle
            
            entity_data['coords']['is_clockwise'] = not entity_data['coords']['is_clockwise']
        # No reversal needed for CIRCLE

        entity_data['reversed'] = not entity_data['reversed']
        
        # Update id_display to reflect the new direction/reversal
        if entity_data['type'] == 'LINE':
            current_start_pt = entity_data['coords']['start_point']
            current_end_pt = entity_data['coords']['end_point']
            entity_data['id_display'] = (f"L{entity_data['original_id']} ({current_start_pt[0]:.2f},{current_start_pt[1]:.2f})->"
                                         f"({current_end_pt[0]:.2f},{current_end_pt[1]:.2f})"
                                         f"{' [R]' if entity_data['reversed'] else ''}")
        elif entity_data['type'] == 'ARC':
            current_start_pt = entity_data['coords']['start_point']
            current_end_pt = entity_data['coords']['end_point']
            radius = entity_data['coords']['radius']
            entity_data['id_display'] = (f"A{entity_data['original_id']}: R{radius:.2f} ({current_start_pt[0]:.2f},{current_start_pt[1]:.2f})->"
                                         f"({current_end_pt[0]:.2f},{current_end_pt[1]:.2f})"
                                         f"{' [R]' if entity_data['reversed'] else ''}")


    def _get_best_candidate_info(self, reference_point, entities_to_search):
        """
        Internal helper to find the best next segment for automated path generation.
        """
        best_match_id = None
        best_should_reverse = False
        min_distance = float('inf')

        for entity_id, data in entities_to_search.items():
            if data['type'] == 'CIRCLE': # Circles are not connectable in this context
                continue

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

    def generate_gcode(self, ordered_segments_data_list, isolated_circles_data_list, initial_start_point=(0.0, 0.0)): # <-- Added isolated_circles_data_list
        """
        Generates ISO G-code from an ordered list of segment data and a list of isolated circles.
        Returns the G-code as a string and a map from G-code line index to DXF segment ID.
        """
        gcode_lines = []
        dxf_segment_id_map = {}
        current_x, current_y = initial_start_point
        gcode_line_idx = 0

        gcode_lines.append(f"N{gcode_line_idx*10} G90 G21 G17 G40 G49 G80")
        dxf_segment_id_map[gcode_line_idx] = "INIT_SETUP"
        gcode_line_idx += 1

        gcode_lines.append(f"N{gcode_line_idx*10} G00 X{current_x:.4f} Y{current_y:.4f}")
        dxf_segment_id_map[gcode_line_idx] = "INIT_POSITION"
        gcode_line_idx += 1
        
        gcode_lines.append(f"N{gcode_line_idx*10} ; Start of DXF Path (Lines and Arcs)")
        dxf_segment_id_map[gcode_line_idx] = "PATH_COMMENT_LINES_ARCS"
        gcode_line_idx += 1

        for segment_data in ordered_segments_data_list:
            segment_start_x = segment_data['coords']['start_point'][0]
            segment_start_y = segment_data['coords']['start_point'][1]
            segment_end_x = segment_data['coords']['end_point'][0]
            segment_end_y = segment_data['coords']['end_point'][1]
            dxf_original_id = segment_data['original_id']

            distance_to_start = math.hypot(segment_start_x - current_x, segment_start_y - current_y)
            if distance_to_start > self.connection_tolerance:
                gcode_lines.append(f"N{gcode_line_idx*10} G00 X{segment_start_x:.4f} Y{segment_start_y:.4f} ; Jump to DXF ID: {dxf_original_id}")
                dxf_segment_id_map[gcode_line_idx] = f"JUMP_TO_DXF_{dxf_original_id}"
                gcode_line_idx += 1
                current_x, current_y = segment_start_x, segment_start_y

            if segment_data['type'] == 'LINE':
                gcode_lines.append(f"N{gcode_line_idx*10} G01 X{segment_end_x:.4f} Y{segment_end_y:.4f} ; LINE DXF ID: {dxf_original_id}")
                dxf_segment_id_map[gcode_line_idx] = dxf_original_id
                gcode_line_idx += 1

            elif segment_data['type'] == 'ARC':
                center_x = segment_data['coords']['center'][0]
                center_y = segment_data['coords']['center'][1]
                
                i_offset = center_x - current_x
                j_offset = center_y - current_y

                command = "G02" if segment_data['coords']['is_clockwise'] else "G03"
                
                gcode_lines.append(f"N{gcode_line_idx*10} {command} X{segment_end_x:.4f} Y{segment_end_y:.4f} I{i_offset:.4f} J{j_offset:.4f} ; ARC DXF ID: {dxf_original_id}")
                dxf_segment_id_map[gcode_line_idx] = dxf_original_id
                gcode_line_idx += 1
            
            current_x, current_y = segment_end_x, segment_end_y

        # --- G-code for Isolated Circles --- <-- Added
        if isolated_circles_data_list:
            gcode_lines.append(f"N{gcode_line_idx*10} ; Start of DXF Isolated Circles")
            dxf_segment_id_map[gcode_line_idx] = "PATH_COMMENT_CIRCLES"
            gcode_line_idx += 1

            for circle_data in isolated_circles_data_list:
                center_x = circle_data['coords']['center'][0]
                center_y = circle_data['coords']['center'][1]
                radius = circle_data['coords']['radius']
                dxf_original_id = circle_data['original_id']

                # Pick a start point for the circle (e.g., at 0 degrees, to the right of the center)
                start_x_circle = center_x + radius
                start_y_circle = center_y

                # Move to the start point of the circle (G00)
                gcode_lines.append(f"N{gcode_line_idx*10} G00 X{start_x_circle:.4f} Y{start_y_circle:.4f} ; Jump to CIRCLE DXF ID: {dxf_original_id}")
                dxf_segment_id_map[gcode_line_idx] = f"JUMP_TO_CIRCLE_{dxf_original_id}"
                gcode_line_idx += 1
                current_x, current_y = start_x_circle, start_y_circle

                # Generate G02/G03 for a full circle. For a full circle, the end point is the same as the start point.
                # I and J are relative offsets from the current point to the center.
                i_offset = center_x - current_x
                j_offset = center_y - current_y

                # Assuming CCW for full circles by default, can be made configurable
                gcode_lines.append(f"N{gcode_line_idx*10} G03 X{start_x_circle:.4f} Y{start_y_circle:.4f} I{i_offset:.4f} J{j_offset:.4f} ; Full CIRCLE DXF ID: {dxf_original_id}")
                dxf_segment_id_map[gcode_line_idx] = dxf_original_id
                gcode_line_idx += 1
                current_x, current_y = start_x_circle, start_y_circle # End point is the same as start point

        # End of program
        gcode_lines.append(f"N{gcode_line_idx*10} M02 ; Program End")
        dxf_segment_id_map[gcode_line_idx] = "PROGRAM_END"
        gcode_line_idx += 1

        generated_gcode = "\n".join(gcode_lines)
        return generated_gcode, dxf_segment_id_map
        
    def generate_auto_path(self, current_dxf_entities, start_entity_data=None):
        """
        Generates an ordered path automatically based on connectivity, handling multiple disconnected profiles
        and separate isolated circles.
        Returns the list of ordered segment data (lines and arcs) and a separate list of isolated circle data.
        """
        if not current_dxf_entities:
            return [], [] # <-- Modified to return two lists

        remaining_entities_processing = {}
        isolated_circles = [] # <-- Added for isolated circles

        # Separate circles from lines/arcs and make deep copies
        for original_id, data in current_dxf_entities.items():
            if data['type'] == 'CIRCLE':
                isolated_circles.append(copy.deepcopy(data))
            else:
                remaining_entities_processing[original_id] = copy.deepcopy(data)

        ordered_segments_local = []
        started_with_user_specified_entity = False

        while remaining_entities_processing:
            current_path_segments = []
            first_segment_data_for_island = None
            
            if start_entity_data and not started_with_user_specified_entity:
                target_original_id = start_entity_data['id'] 
                if target_original_id in remaining_entities_processing:
                    first_segment_data_for_island = remaining_entities_processing.pop(target_original_id)
                    if start_entity_data['reversed'] != first_segment_data_for_island['reversed']:
                        self.reverse_segment_direction(first_segment_data_for_island)
                    started_with_user_specified_entity = True 
                else:
                    pass 
            
            if not first_segment_data_for_island:
                # Find the closest LINE/ARC entity to (0,0) among the remaining ones to start a new island
                initial_segment_id, initial_should_reverse, _ = self._get_best_candidate_info((0.0, 0.0), remaining_entities_processing)
                if initial_segment_id is not None:
                    first_segment_data_for_island = remaining_entities_processing.pop(initial_segment_id)
                    if initial_should_reverse:
                        self.reverse_segment_direction(first_segment_data_for_island)
                else:
                    break

            if first_segment_data_for_island:
                current_path_segments.append(first_segment_data_for_island)
                current_active_point = list(first_segment_data_for_island['coords']['end_point'])

                while True:
                    next_match_id, next_should_reverse, connection_dist = self._get_best_candidate_info(current_active_point, remaining_entities_processing)
                    
                    if next_match_id is not None and connection_dist <= self.connection_tolerance:
                        next_segment_data = remaining_entities_processing.pop(next_match_id)
                        if next_should_reverse:
                            self.reverse_segment_direction(next_segment_data)
                        current_path_segments.append(next_segment_data)
                        
                        current_active_point[0] = next_segment_data['coords']['end_point'][0]
                        current_active_point[1] = next_segment_data['coords']['end_point'][1]
                    else:
                        break
                
                ordered_segments_local.extend(current_path_segments)
            else:
                break # Should not be reached if remaining_entities_processing is not empty

        return ordered_segments_local, isolated_circles # <-- Modified to return two lists
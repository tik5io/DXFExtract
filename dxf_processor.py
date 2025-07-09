# dxf_processor.py

import ezdxf
import math
import logging
from typing import List, Dict, Tuple

# Configuration du logging pour ce module
logging.basicConfig(level=logging.INFO, format='[DXF_PROCESSOR] %(message)s')

class DxfProcessor:
    """
    Traite les fichiers DXF pour en extraire des entités géométriques,
    créer des trajectoires d'usinage et générer le G-code correspondant.
    """
    def __init__(self, connection_tolerance: float = 0.01):
        self.connection_tolerance = connection_tolerance 
        self.current_dxf_entities: Dict[str, Dict] = {} 

    def extract_dxf_entities(self, file_path: str) -> Dict[str, Dict]:
        """
        Lit un fichier DXF et extrait les entités LINE, ARC, et CIRCLE.
        Ne conserve que les coordonnées 2D (X, Y).
        """
        self.current_dxf_entities = {}
        logging.info(f"Début de l'extraction des entités du fichier : {file_path}")
        try:
            doc = ezdxf.readfile(file_path)
            msp = doc.modelspace()
            logging.info(f"Modelspace contient {len(msp)} entités.")

            for entity in msp:
                entity_data = {'original_id': str(entity.dxf.handle)} 

                if entity.dxftype() == 'LINE':
                    entity_data.update({
                        'type': 'LINE',
                        'coords': {
                            'start_point': tuple(entity.dxf.start)[:2], 
                            'end_point': tuple(entity.dxf.end)[:2] 
                        },
                        'id_display': f"Line {entity_data['original_id'][-4:]}" 
                    })
                elif entity.dxftype() == 'ARC':
                    # Normaliser les angles pour le traitement
                    start_angle = entity.dxf.start_angle
                    end_angle = entity.dxf.end_angle
                    if end_angle < start_angle:
                        end_angle += 360 
                    
                    center = tuple(entity.dxf.center)[:2]
                    radius = entity.dxf.radius

                    # Calculer les points de départ et de fin en 2D
                    start_point = (center[0] + radius * math.cos(math.radians(start_angle)),
                                   center[1] + radius * math.sin(math.radians(start_angle)))
                    end_point = (center[0] + radius * math.cos(math.radians(end_angle)),
                                 center[1] + radius * math.sin(math.radians(end_angle)))

                    entity_data.update({
                        'type': 'ARC',
                        'coords': {
                            'center': center, 
                            'radius': radius, 
                            'start_angle': start_angle, 
                            'end_angle': end_angle,
                            'start_point': start_point, 
                            'end_point': end_point 
                        },
                        'id_display': f"Arc {entity_data['original_id'][-4:]}" 
                    })
                elif entity.dxftype() == 'CIRCLE':
                    entity_data.update({
                        'type': 'CIRCLE',
                        'coords': {
                            'center': tuple(entity.dxf.center)[:2], 
                            'radius': entity.dxf.radius 
                        },
                        'id_display': f"Circle {entity_data['original_id'][-4:]}" 
                    })
                else:
                    continue # Ignorer les autres types d'entités 

                self.current_dxf_entities[entity_data['original_id']] = entity_data
            
            logging.info(f"{len(self.current_dxf_entities)} entités supportées extraites.") 
            return self.current_dxf_entities
        except (ezdxf.DXFError, IOError, Exception) as e:
            logging.error(f"Erreur lors du traitement du fichier DXF : {e}")
            return None 

    def generate_auto_path(self, dxf_entities: Dict[str, Dict]) -> Tuple[List[List[Dict]], List[Dict]]:
        """
        Organise les entités en trajectoires connectées (boucles) et en cercles isolés.
        """
        logging.info("Génération automatique des trajectoires...")
        
        entities_for_pathing = {k: v for k, v in dxf_entities.items() if v['type'] != 'CIRCLE'} 
        isolated_circles = [v for v in dxf_entities.values() if v['type'] == 'CIRCLE'] 
        ordered_trajectories = []
        
        # 1. Identifier les groupes de segments connectés
        components = self._find_connected_components(entities_for_pathing)
        
        # 2. Transformer chaque groupe en une trajectoire ordonnée
        for component in components:
            if component:
                start_id = next(iter(component))
                path = self._path_single_trajectory(component, component[start_id])
                if path:
                    ordered_trajectories.append(path)
        
        logging.info(f"{len(ordered_trajectories)} trajectoires et {len(isolated_circles)} cercles isolés générés.") 
        return ordered_trajectories, isolated_circles

    def generate_gcode(self, ordered_segments: List[Dict], isolated_circles: List[Dict], initial_start_point: Tuple[float, float]) -> Tuple[str, Dict[int, str]]:
        """
        Génère une chaîne de caractères G-code à partir des segments ordonnés et des cercles.
        Retourne le G-code et une map associant chaque ligne à un ID d'entité DXF.
        """
        logging.info("Génération du G-code...")
        gcode_lines, dxf_id_map = [], {}
        current_x, current_y = initial_start_point

        def add_line(line, dxf_id):
            gcode_lines.append(line)
            dxf_id_map[len(gcode_lines) - 1] = dxf_id

        # En-tête du G-code
        add_line(f"G0 X{current_x:.3f} Y{current_y:.3f} ; Position initiale", "INITIAL_POS") 

        # Traitement des segments ordonnés (lignes et arcs)
        for segment in ordered_segments:
            start_x, start_y = segment['coords']['start_point']
            end_x, end_y = segment['coords']['end_point']

            # Si la position actuelle n'est pas le début du segment, s'y déplacer en rapide (G0)
            if self._calculate_distance((current_x, current_y), (start_x, start_y)) > self.connection_tolerance:
                add_line(f"G0 X{start_x:.3f} Y{start_y:.3f} ; Aller au segment {segment['original_id']}", f"JUMP_TO_DXF_{segment['original_id']}") 
                current_x, current_y = start_x, start_y

            if segment['type'] == 'LINE':
                add_line(f"G1 X{end_x:.3f} Y{end_y:.3f}", f"L{segment['original_id']}") 
            elif segment['type'] == 'ARC':
                center_x, center_y = segment['coords']['center']
                i, j = center_x - current_x, center_y - current_y
                # G2 = sens horaire, G3 = sens anti-horaire
                # Un angle final plus grand signifie un parcours anti-horaire (G3)
                gcode_cmd = "G3" if (segment['coords']['end_angle'] > segment['coords']['start_angle']) ^ segment.get('direction_reversed', False) else "G2" 
                add_line(f"{gcode_cmd} X{end_x:.3f} Y{end_y:.3f} I{i:.3f} J{j:.3f}", f"A{segment['original_id']}") 
            
            current_x, current_y = end_x, end_y

        # Traitement des cercles isolés
        for circle in isolated_circles:
            center_x, center_y = circle['coords']['center']
            radius = circle['coords']['radius']
            start_x, start_y = center_x + radius, center_y # Point de départ du cercle sur l'axe X+

            if self._calculate_distance((current_x, current_y), (start_x, start_y)) > self.connection_tolerance:
                add_line(f"G0 X{start_x:.3f} Y{start_y:.3f} ; Aller au cercle {circle['original_id']}", f"JUMP_TO_CIRCLE_{circle['original_id']}") 
                current_x, current_y = start_x, start_y

            # Un cercle complet est un G2 ou G3 avec I et J relatifs
            gcode_cmd = "G3" if circle.get('direction_reversed', False) else "G2" 
            add_line(f"{gcode_cmd} I{-radius:.3f} J0.000", f"C{circle['original_id']}") 
            current_x, current_y = start_x, start_y # On revient au point de départ du cercle

        # Pied de page du G-code
        add_line("M2 ; Fin du programme", "FOOTER") 
        
        logging.info("Génération du G-code terminée.")
        return "\n".join(gcode_lines), dxf_id_map 

    
    def _calculate_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) 

    def _get_segment_endpoints(self, segment: Dict) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return segment['coords']['start_point'], segment['coords']['end_point'] 

    def _reverse_segment(self, segment: Dict):
        if segment['type'] in ['LINE', 'ARC']:
            segment['coords']['start_point'], segment['coords']['end_point'] = segment['coords']['end_point'], segment['coords']['start_point'] 
            segment['direction_reversed'] = not segment.get('direction_reversed', False)
            logging.debug(f"Segment {segment['original_id']} inversé.")

    def _find_next_segment(self, active_point: Tuple[float, float], remaining_entities: Dict) -> Tuple[str, bool]:
        for entity_id, entity in remaining_entities.items():
            start_p, end_p = self._get_segment_endpoints(entity)
            if self._calculate_distance(active_point, start_p) <= self.connection_tolerance:
                return entity_id, False # Ne pas inverser
            if self._calculate_distance(active_point, end_p) <= self.connection_tolerance:
                return entity_id, True  # Inverser
        return None, False

    def _find_connected_components(self, dxf_entities: Dict) -> List[Dict]:
        components, visited_ids = [], set()
        for entity_id in dxf_entities:
            if entity_id in visited_ids:
                continue
            
            component_ids = set()
            queue = [entity_id]
            
            while queue:
                current_id = queue.pop(0)
                if current_id in component_ids:
                    continue
                
                component_ids.add(current_id)
                visited_ids.add(current_id)
                current_start, current_end = self._get_segment_endpoints(dxf_entities[current_id])
                
                for neighbor_id, neighbor_entity in dxf_entities.items():
                    if neighbor_id in component_ids:
                        continue
                    neighbor_start, neighbor_end = self._get_segment_endpoints(neighbor_entity)
                    
                    if min(self._calculate_distance(current_start, neighbor_start),
                           self._calculate_distance(current_start, neighbor_end),
                           self._calculate_distance(current_end, neighbor_start),
                           self._calculate_distance(current_end, neighbor_end)) <= self.connection_tolerance:
                        queue.append(neighbor_id)
            
            components.append({cid: dxf_entities[cid] for cid in component_ids})
        logging.info(f"{len(components)} composants connectés trouvés.") 
        return components

    def _path_single_trajectory(self, component: Dict, start_segment: Dict) -> List[Dict]:
        path = [start_segment]
        remaining = component.copy()
        del remaining[start_segment['original_id']]
        
        active_point = start_segment['coords']['end_point']
        
        while remaining:
            next_id, should_reverse = self._find_next_segment(active_point, remaining)
            if next_id is None:
                break # Fin de la trajectoire ouverte
                
            next_segment = remaining.pop(next_id)
            if should_reverse:
                self._reverse_segment(next_segment)
            
            path.append(next_segment)
            active_point = next_segment['coords']['end_point']

            # Condition de fermeture de boucle
            if self._calculate_distance(active_point, start_segment['coords']['start_point']) <= self.connection_tolerance:
                break # Boucle fermée

        return path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import os
# Assurez-vous que ces modules sont disponibles et correctement implémentés
from dxf_processor import DxfProcessor
from gcode_visualizer import GcodeVisualizer
from typing import List, Dict, Tuple, Set, Any

# Configuration du logging pour l'application principale
logging.basicConfig(level=logging.debug, format='[GCODE_VIS_APP] %(message)s')

class AppGUI:
    def __init__(self, master):
        self.master = master
        master.title("G-code Visualizer")
        master.geometry("1200x800")

        # --- Modules de traitement ---
        self.dxf_processor = DxfProcessor()

        # --- État de l'application ---
        self.gcode_string = ""
        self.dxf_id_map: Dict[int, str] = {} # Map: line_idx -> original_dxf_id (from G-code generation)
        self.ordered_trajectories: List[List[Dict]] = [] # Liste des listes de segments ordonnés
        self.isolated_circles: List[Dict] = []

        # --- NOUVELLE ARCHITECTURE : État de la sélection centralisé ---
        self.selected_dxf_ids: Set[str] = set() # Utiliser un set pour des recherches rapides et éviter les doublons
        self.dxf_id_to_line_map: Dict[str, List[int]] = {} # Map: original_id -> [line_idx, ...]
        # Map: original_dxf_id_segment -> parent_trajectory_tree_id (e.g., 'traj_0', 'isolated_circles_parent')
        self.dxf_id_to_traj_map: Dict[str, str] = {}

        self._is_programmatic_update = False # Flag pour éviter les boucles de mise à jour

        self.trajectory_colors = [
            "#FF6666", "#66CC66", "#6699FF", "#FFCC00", "#00CCCC", "#CC66FF", "#FF9966", "#66FFCC"
        ]

        self._setup_gui()

    def regenerate_gcode_from_current_trajectories(self):
        """Utilise les trajectoires déjà modifiées sans les régénérer automatiquement."""
        all_ordered_segments = [seg for traj in self.ordered_trajectories for seg in traj]
        self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
            all_ordered_segments,
            self.isolated_circles,
            (0.0, 0.0)
        )

        # Reconstruire la map ligne->id
        self.dxf_id_to_line_map = {}
        for line_idx, dxf_id_str in self.dxf_id_map.items():
            handle = None
            if '_' in dxf_id_str:
                handle = dxf_id_str.split('_')[-1]
            elif dxf_id_str.startswith(('L', 'A', 'C')) and len(dxf_id_str) > 1:
                handle = dxf_id_str[1:]
            if handle and handle not in ["HEADER", "INITIAL_POS", "FOOTER"]:
                self.dxf_id_to_line_map.setdefault(handle, []).append(line_idx)

        self.selected_dxf_ids.clear()
        self.update_gcode_text()
        self.populate_treeview()
        self.update_gcode_visualizer()

    def move_trajectory_up(self):
        selected = self.gcode_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        if item_id.startswith("traj_"):
            idx = int(item_id.split("_")[1])
            if idx > 0:
                self.ordered_trajectories[idx - 1], self.ordered_trajectories[idx] = self.ordered_trajectories[idx], self.ordered_trajectories[idx - 1]
                self.regenerate_gcode_from_current_trajectories()
        elif item_id in [circle['original_id'] for circle in self.isolated_circles]:
            idx = next((i for i, c in enumerate(self.isolated_circles) if c['original_id'] == item_id), None)
            if idx is not None and idx > 0:
                self.isolated_circles[idx - 1], self.isolated_circles[idx] = self.isolated_circles[idx], self.isolated_circles[idx - 1]
                self.regenerate_gcode_from_current_trajectories()
    def move_trajectory_down(self):
        selected = self.gcode_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        if item_id.startswith("traj_"):
            idx = int(item_id.split("_")[1])
            if idx < len(self.ordered_trajectories) - 1:
                self.ordered_trajectories[idx + 1], self.ordered_trajectories[idx] = self.ordered_trajectories[idx], self.ordered_trajectories[idx + 1]
                self.regenerate_gcode_from_current_trajectories()
        elif item_id in [circle['original_id'] for circle in self.isolated_circles]:
            idx = next((i for i, c in enumerate(self.isolated_circles) if c['original_id'] == item_id), None)
            if idx is not None and idx < len(self.isolated_circles) - 1:
                self.isolated_circles[idx + 1], self.isolated_circles[idx] = self.isolated_circles[idx], self.isolated_circles[idx + 1]
                self.regenerate_gcode_from_current_trajectories()
    def delete_selected_trajectory(self):
        selected = self.gcode_tree.selection()
        if not selected:
            return
        item_id = selected[0]

        if item_id.startswith("traj_"):
            idx = int(item_id.split("_")[1])
            del self.ordered_trajectories[idx]
            self.regenerate_gcode_from_current_trajectories()

        elif item_id == "isolated_circles_parent":
            # Supprime tous les cercles
            self.isolated_circles.clear()
            self.regenerate_gcode_from_current_trajectories()

        elif item_id in [circle['original_id'] for circle in self.isolated_circles]:
            # Supprime un cercle isolé en particulier
            self.isolated_circles = [c for c in self.isolated_circles if c['original_id'] != item_id]
            self.regenerate_gcode_from_current_trajectories()

    def reverse_selected_trajectory(self):
        selected = self.gcode_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        if item_id.startswith("traj_"):
            idx = int(item_id.split("_")[1])
            traj = self.ordered_trajectories[idx]
            for segment in traj:
                self.dxf_processor._reverse_segment(segment)
            traj.reverse()
            self.regenerate_gcode_from_current_trajectories()

    def mark_first_in_trajectory(self):
        selected = self.gcode_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        if not self.gcode_tree.tag_has("dxf_entity", item_id):
            return

        for i, traj in enumerate(self.ordered_trajectories):
            for j, seg in enumerate(traj):
                if seg['original_id'] == item_id:
                    new_traj = traj[j:] + traj[:j]
                    start_seg = new_traj[0]
                    reordered = [start_seg]
                    remaining = new_traj[1:]
                    active_pt = start_seg['coords']['end_point']

                    while remaining:
                        found = False
                        for k, seg in enumerate(remaining):
                            d = self.dxf_processor._calculate_distance(active_pt, seg['coords']['start_point'])
                            dr = self.dxf_processor._calculate_distance(active_pt, seg['coords']['end_point'])
                            if d <= self.dxf_processor.connection_tolerance:
                                reordered.append(seg)
                                active_pt = seg['coords']['end_point']
                                remaining.pop(k)
                                found = True
                                break
                            elif dr <= self.dxf_processor.connection_tolerance:
                                self.dxf_processor._reverse_segment(seg)
                                reordered.append(seg)
                                active_pt = seg['coords']['end_point']
                                remaining.pop(k)
                                found = True
                                break
                        if not found:
                            break
                    self.ordered_trajectories[i] = reordered
                    self.regenerate_gcode_from_current_trajectories()
                    return

    def _setup_gui(self):
        """Construit l'interface graphique."""
        self.main_frame = ttk.Frame(self.master, padding="10")
        self.main_frame.pack(fill="both", expand=True)

        # --- Panneau supérieur avec les boutons ---
        top_frame = ttk.Frame(self.main_frame)
        top_frame.pack(fill="x", pady=5)
        ttk.Button(top_frame, text="Load DXF", command=self.load_dxf_file).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Regenerate G-code", command=self.regenerate_gcode_and_update_gui).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Save G-code", command=self.save_gcode_file).pack(side="left", padx=5)

        # --- Barre d'outils de réorganisation ---
        toolbar_frame = ttk.Frame(self.main_frame)
        toolbar_frame.pack(fill="x", pady=2)

        ttk.Button(toolbar_frame, text="Monter", command=self.move_trajectory_up).pack(side="left", padx=2)
        ttk.Button(toolbar_frame, text="Descendre", command=self.move_trajectory_down).pack(side="left", padx=2)
        ttk.Button(toolbar_frame, text="Supprimer", command=self.delete_selected_trajectory).pack(side="left", padx=2)
        ttk.Button(toolbar_frame, text="Inverser", command=self.reverse_selected_trajectory).pack(side="left", padx=2)
        ttk.Button(toolbar_frame, text="Marquer comme 1er élément", command=self.mark_first_in_trajectory).pack(side="left", padx=2)

        # --- Panneau de contenu principal (Visualiseur, Arbre, Texte G-code) ---
        content_frame = ttk.Frame(self.main_frame)
        content_frame.pack(fill="both", expand=True, pady=5)
        content_frame.grid_rowconfigure(0, weight=3)
        content_frame.grid_rowconfigure(1, weight=1)
        content_frame.grid_columnconfigure(0, weight=3)
        content_frame.grid_columnconfigure(1, weight=1)

        # --- G-code Visualizer (colonne 0, ligne 0) ---
        vis_frame = ttk.LabelFrame(content_frame, text="Visualiseur G-code", padding="5")
        vis_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.gcode_visualizer = GcodeVisualizer(vis_frame)
        self.gcode_visualizer.pack(fill="both", expand=True)
        

        # --- DXF Elements Treeview (colonne 1, ligne 0) ---
        tree_frame = ttk.LabelFrame(content_frame, text="Éléments DXF", padding="5")
        tree_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.gcode_tree = ttk.Treeview(tree_frame, show="tree")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.gcode_tree.yview)
        self.gcode_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self.gcode_tree.pack(side="left", fill="both", expand=True)
        # Lié à <<TreeviewSelect>> pour gérer la sélection de l'utilisateur
        self.gcode_tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        # --- G-code Text Output (sur les 2 colonnes, ligne 1) ---
        text_frame = ttk.LabelFrame(content_frame, text="Sortie G-code", padding="5")
        text_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        # Utiliser une couleur de fond blanche pour permettre la sélection
        self.gcode_text = tk.Text(text_frame, wrap="none", bg="white", undo=True, state="normal")
        v_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.gcode_text.yview)
        h_scroll = ttk.Scrollbar(text_frame, orient="horizontal", command=self.gcode_text.xview)
        self.gcode_text.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        v_scroll.pack(side="right", fill="y")
        h_scroll.pack(side="bottom", fill="x")
        self.gcode_text.pack(side="left", fill="both", expand=True)
        # Utiliser ButtonRelease-1 est plus fiable pour détecter un clic utilisateur
        self.gcode_text.bind("<ButtonRelease-1>", self.on_gcode_text_select)

        # --- Barre de statut ---
        self.status_label = ttk.Label(self.main_frame, text="Prêt", relief="sunken", anchor="w")
        self.status_label.pack(side="bottom", fill="x", pady=(5,0))

    def load_dxf_file(self):
        """Ouvre un fichier DXF, le traite et met à jour l'IHM."""
        file_path = filedialog.askopenfilename(filetypes=[("DXF Files", "*.dxf"), ("All Files", "*.*")])
        if not file_path: return

        self.status_label.config(text=f"Chargement de {os.path.basename(file_path)}...")
        dxf_entities = self.dxf_processor.extract_dxf_entities(file_path)
        if dxf_entities:
            self.regenerate_gcode_and_update_gui(dxf_entities)
            self.status_label.config(text=f"Fichier {os.path.basename(file_path)} traité.")
        else:
            messagebox.showerror("Erreur DXF", "Impossible de lire ou traiter le fichier DXF.")
            self.status_label.config(text="Échec du chargement DXF.")

    def regenerate_gcode_and_update_gui(self, dxf_entities=None):
        """Génère le G-code et met à jour tous les composants de l'IHM."""
        if dxf_entities is None:
            dxf_entities = self.dxf_processor.current_dxf_entities
        if not dxf_entities:
            messagebox.showwarning("Avertissement", "Aucune entité DXF à traiter.")
            return

        logging.info("Régénération du G-code et mise à jour de l'IHM...")
        self.ordered_trajectories, self.isolated_circles = self.dxf_processor.generate_auto_path(dxf_entities)

        all_ordered_segments = [seg for traj in self.ordered_trajectories for seg in traj]

        self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(all_ordered_segments, self.isolated_circles, (0.0, 0.0))

        # Créer la map inversée pour la nouvelle architecture
        self.dxf_id_to_line_map = {}
        for line_idx, dxf_id_str in self.dxf_id_map.items():
            handle = None
            # Extract the actual DXF handle (e.g., 'A123' -> '123')
            # This part needs to match how your dxf_processor.py formats the original_id
            if '_' in dxf_id_str: # For "JUMP_TO_DXF_ABC"
                handle = dxf_id_str.split('_')[-1]
            elif dxf_id_str.startswith(('L', 'A', 'C')) and len(dxf_id_str) > 1: # For "LABC", "AXYZ", "C123"
                handle = dxf_id_str[1:]
            
            if handle and handle not in ["HEADER", "INITIAL_POS", "FOOTER"]: # Filter out non-entity IDs
                if handle not in self.dxf_id_to_line_map:
                    self.dxf_id_to_line_map[handle] = []
                self.dxf_id_to_line_map[handle].append(line_idx)
        
        # Réinitialiser la sélection
        self.selected_dxf_ids.clear()

        # Mettre à jour les widgets
        self.update_gcode_text()
        self.populate_treeview() # Appel modifié pour la nouvelle structure
        self.update_gcode_visualizer()
        logging.info("IHM mise à jour.")

    def save_gcode_file(self):
        if not self.gcode_string:
            messagebox.showwarning("Sauvegarde impossible", "Aucun G-code à sauvegarder.")
            return
        file_path = filedialog.asksaveasfilename(defaultextension=".gcode", filetypes=[("G-code Files", "*.gcode")])
        if file_path:
            try:
                with open(file_path, 'w') as f: f.write(self.gcode_string)
                self.status_label.config(text=f"G-code sauvegardé : {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Erreur de sauvegarde", f"Échec de la sauvegarde : {e}")

    def update_gcode_text(self):
        self.gcode_text.delete("1.0", tk.END)
        self.gcode_text.insert("1.0", self.gcode_string)

    def populate_treeview(self):
        """
        Popule le Treeview avec les entités DXF regroupées par trajectoires.
        Cette version est basée sur la structure DXF (trajectoires et cercles isolés)
        et non directement sur les lignes de G-code.
        """
        self.gcode_tree.delete(*self.gcode_tree.get_children())
        self.dxf_id_to_traj_map.clear() # Vider la map avant de la remplir

        # Afficher les trajectoires ordonnées
        for i, trajectory in enumerate(self.ordered_trajectories):
            traj_parent_id = f"traj_{i}"
            # Le texte indique le nombre d'entités dans la trajectoire
            self.gcode_tree.insert("", "end", traj_parent_id, 
                                   text=f"Trajectoire {i+1} ({len(trajectory)} entités)", 
                                   tags=("trajectory_parent",), open=True) 
            
            for seg in trajectory:
                dxf_id = seg['original_id']
                dxf_type = seg['type'] # e.g., 'LINE', 'ARC'
                
                # Utiliser dxf_id directement comme item_id pour la logique de sélection
                self.gcode_tree.insert(traj_parent_id, "end", dxf_id, 
                                       text=f"{dxf_type}: {dxf_id}", 
                                       values=(dxf_id, dxf_type), # Stocker les données pertinentes
                                       tags=("dxf_entity",)) # Nouveau tag pour les entités DXF individuelles
                # Mapper original_id à son élément parent du Treeview
                self.dxf_id_to_traj_map[dxf_id] = traj_parent_id

        # Afficher les cercles isolés
        if self.isolated_circles:
            isolated_parent_id = "isolated_circles_parent" 
            self.gcode_tree.insert("", "end", isolated_parent_id, 
                                   text=f"Cercles isolés ({len(self.isolated_circles)} entités)", 
                                   tags=("isolated_parent",), open=True) 
            
            for circle in self.isolated_circles:
                dxf_id = circle['original_id']
                dxf_type = circle['type'] # Devrait être 'CIRCLE'
                
                self.gcode_tree.insert(isolated_parent_id, "end", dxf_id, 
                                       text=f"{dxf_type}: {dxf_id}", 
                                       values=(dxf_id, dxf_type),
                                       tags=("dxf_entity",))
                self.dxf_id_to_traj_map[dxf_id] = isolated_parent_id

    def update_gcode_visualizer(self):
        # Reconstruction complète avec déplacements G0 visibles
        visualizer_segments = []
        current_x, current_y = 0.0, 0.0  # position initiale
        for i, trajectory in enumerate(self.ordered_trajectories):
            color = self.trajectory_colors[i % len(self.trajectory_colors)]
            for segment in trajectory:
                sx, sy = segment['coords']['start_point']
                if self.dxf_processor._calculate_distance((current_x, current_y), (sx, sy)) > self.dxf_processor.connection_tolerance:
                    # Ajouter segment G0 fictif
                    visualizer_segments.append({
                        'type': 'LINE',
                        'coords': {'start_point': (current_x, current_y), 'end_point': (sx, sy)},
                        'color': 'gray',
                        'original_id': f"JUMP_TO_DXF_{segment['original_id']}"
                    })
                visualizer_segments.append({
                    'type': segment['type'],
                    'coords': segment['coords'],
                    'color': color,
                    'original_id': segment['original_id'],
                    'direction_reversed': segment.get('direction_reversed', False)
                })
                current_x, current_y = segment['coords']['end_point']
        # Cercles isolés (même logique)
        for circle in self.isolated_circles:
            cx, cy = circle['coords']['center']
            r = circle['coords']['radius']
            sx, sy = (cx + r, cy)
            if self.dxf_processor._calculate_distance((current_x, current_y), (sx, sy)) > self.dxf_processor.connection_tolerance:
                visualizer_segments.append({
                    'type': 'LINE',
                    'coords': {'start_point': (current_x, current_y), 'end_point': (sx, sy)},
                    'color': 'gray',
                    'original_id': f"JUMP_TO_CIRCLE_{circle['original_id']}"
                })
            visualizer_segments.append({
                'type': 'CIRCLE',
                'coords': circle['coords'],
                'color': 'red',
                'original_id': circle['original_id']
            })
            current_x, current_y = sx, sy

        # Mettre à jour le visualiseur avec les segments
        self.gcode_visualizer.draw_gcode_path(visualizer_segments)

    def _update_gcode_text_selection(self):
        """Met à jour la sélection de l'éditeur de texte en fonction de self.selected_dxf_ids."""
        logging.info(f"[GCODE_TEXT_SEL] Début _update_gcode_text_selection. selected_dxf_ids: {self.selected_dxf_ids}") # Nouveau log
        self.gcode_text.tag_remove(tk.SEL, "1.0", tk.END)
        self.gcode_text.focus_set()  # <-- Ajoute ceci pour forcer la sélection visible
        gcode_lines_to_select = []
        for dxf_id in self.selected_dxf_ids:
            lines = self.dxf_id_to_line_map.get(dxf_id, [])
            if not lines:
                logging.warning(f"[GCODE_TEXT_SEL] Aucun G-code line_idx trouvé pour dxf_id: {dxf_id}. dxf_id_to_line_map: {self.dxf_id_to_line_map.keys()}")
            gcode_lines_to_select.extend(lines)

        logging.info(f"[GCODE_TEXT_SEL] Lignes G-code à sélectionner (avant tri/dedupl.): {gcode_lines_to_select}") # Nouveau log

        if gcode_lines_to_select:
            gcode_lines_to_select = sorted(list(set(gcode_lines_to_select)))
            logging.info(f"[GCODE_TEXT_SEL] Lignes G-code à sélectionner (après tri/dedupl.): {gcode_lines_to_select}") # Nouveau log
            for line_idx in gcode_lines_to_select:
                self.gcode_text.tag_add(tk.SEL, f"{line_idx + 1}.0", f"{line_idx + 1}.end")
                logging.info(f"[GCODE_TEXT_SEL] Sélection ajoutée pour la ligne: {line_idx + 1}") # Nouveau log
            if gcode_lines_to_select:
                self.gcode_text.see(f"{gcode_lines_to_select[0] + 1}.0")
                logging.info(f"[GCODE_TEXT_SEL] Fait défiler jusqu'à la ligne: {gcode_lines_to_select[0] + 1}") # Nouveau log
        else:
            logging.info("[GCODE_TEXT_SEL] Aucune ligne G-code à sélectionner.")

    def _refresh_widgets_from_selection(self):
        """Met à jour tous les widgets (visualiseur, texte, treeview) à partir de la source de vérité : self.selected_dxf_ids."""
        self._is_programmatic_update = True # Débute une mise à jour programmatique
        try:
            # 1. Rafraîchir le visualiseur
            self.gcode_visualizer.highlight_dxf_entities_by_ids(list(self.selected_dxf_ids))

            # 2. Rafraîchir l'éditeur de texte
            self._update_gcode_text_selection()

            # 3. Rafraîchir le Treeview
            current_tree_selection = set(self.gcode_tree.selection())
            desired_tree_selection = set()

            # Ajouter les éléments DXF individuels à la sélection désirée
            for dxf_id in self.selected_dxf_ids:
                if self.gcode_tree.exists(dxf_id): # Vérifier si l'ID DXF existe comme élément de l'arbre
                    desired_tree_selection.add(dxf_id)
            
            # Ajouter les éléments parent de trajectoire/cercles isolés si tous leurs enfants sont sélectionnés
            # Pour les trajectoires ordonnées:
            for i, trajectory in enumerate(self.ordered_trajectories):
                traj_tree_id = f"traj_{i}"
                if not self.gcode_tree.exists(traj_tree_id):
                    continue

                all_children_selected = True
                if not trajectory: # Gérer les trajectoires vides
                    all_children_selected = False 
                else:
                    for seg in trajectory:
                        if seg['original_id'] not in self.selected_dxf_ids:
                            all_children_selected = False
                            break
                if all_children_selected and trajectory: # S'assurer qu'il y a des enfants et qu'ils sont tous sélectionnés
                    desired_tree_selection.add(traj_tree_id)

            # Pour les cercles isolés:
            if self.isolated_circles:
                circ_tree_id = "isolated_circles_parent"
                if self.gcode_tree.exists(circ_tree_id):
                    all_children_selected = True
                    for circle in self.isolated_circles:
                        if circle['original_id'] not in self.selected_dxf_ids:
                            all_children_selected = False
                            break
                    if all_children_selected and self.isolated_circles: # S'assurer qu'il y a des enfants et qu'ils sont tous sélectionnés
                        desired_tree_selection.add(circ_tree_id)

            if desired_tree_selection != current_tree_selection:
                self.gcode_tree.selection_set(list(desired_tree_selection))
                if desired_tree_selection:
                    self.gcode_tree.see(list(desired_tree_selection)[0])
                
        finally:
            self._is_programmatic_update = False


    def on_tree_select(self, event):
        """Met à jour l'état de la sélection depuis le Treeview et rafraîchit tous les autres widgets."""
        if self._is_programmatic_update:
            logging.info("[TREE_SELECT] Ignoré: mise à jour programmatique.") # Nouveau log
            return # Ignore les sélections déclenchées par le programme

        selected_items_in_tree = self.gcode_tree.selection() # Ce sont les items *explicitement* sélectionnés par l'utilisateur
        logging.info(f"[TREE_SELECT] Éléments Treeview sélectionnés par l'utilisateur: {selected_items_in_tree}") # Nouveau log

        new_selected_dxf_ids = set()

        for item_id in selected_items_in_tree:
            if self.gcode_tree.tag_has("trajectory_parent", item_id) or self.gcode_tree.tag_has("isolated_parent", item_id):
                children_items = self.gcode_tree.get_children(item_id)
                logging.info(f"[TREE_SELECT] Parent sélectionné ({item_id}), ajout des enfants: {children_items}") # Nouveau log
                for child_id in children_items:
                    new_selected_dxf_ids.add(child_id)
            elif self.gcode_tree.tag_has("dxf_entity", item_id):
                new_selected_dxf_ids.add(item_id)
                logging.info(f"[TREE_SELECT] Entité DXF sélectionnée: {item_id}") # Nouveau log
        
        logging.info(f"[TREE_SELECT] new_selected_dxf_ids avant mise à jour: {new_selected_dxf_ids}. Précédent selected_dxf_ids: {self.selected_dxf_ids}") # Nouveau log
        # Mettre à jour l'état centralisé de la sélection
        self.selected_dxf_ids = new_selected_dxf_ids
        logging.info(f"[TREE_SELECT] selected_dxf_ids après mise à jour: {self.selected_dxf_ids}") # Nouveau log
        
        # IMPORTANT: Rafraîchir TOUS les widgets basés sur la nouvelle sélection, y compris le Treeview.
        self._refresh_widgets_from_selection()
        logging.info("[TREE_SELECT] Appel de _refresh_widgets_from_selection.") # Nouveau log

    def on_gcode_text_select(self, event):
        """Met à jour l'état de la sélection depuis l'éditeur de texte et rafraîchit tout."""
        if self._is_programmatic_update:
            return

        new_selected_dxf_ids = set()
        
        # Obtenir les indices des lignes sélectionnées par l'utilisateur
        try:
            start_index = self.gcode_text.index(tk.SEL_FIRST)
            end_index = self.gcode_text.index(tk.SEL_LAST)
            
            start_line_idx = int(start_index.split('.')[0]) - 1
            end_line_idx = int(end_index.split('.')[0]) - 1
            
            for line_idx in range(start_line_idx, end_line_idx + 1):
                if 0 <= line_idx < len(self.dxf_id_map):
                    dxf_id_str_with_prefix = self.dxf_id_map.get(line_idx)
                    handle = None
                    # Extraire le handle DXF réel
                    if dxf_id_str_with_prefix:
                        if '_' in dxf_id_str_with_prefix: # e.g. JUMP_TO_DXF_ABC
                            handle = dxf_id_str_with_prefix.split('_')[-1]
                        elif dxf_id_str_with_prefix.startswith(('L', 'A', 'C')) and len(dxf_id_str_with_prefix) > 1: # e.g. LABCD
                            handle = dxf_id_str_with_prefix[1:]
                    if handle and handle not in ["HEADER", "INITIAL_POS", "FOOTER"]:
                        new_selected_dxf_ids.add(handle)
        except tk.TclError:
            # Aucune sélection textuelle active
            pass

        # Mettre à jour l'état centralisé de la sélection
        self.selected_dxf_ids = new_selected_dxf_ids
        
        # Rafraîchir tous les autres widgets (y compris le Treeview)
        self._refresh_widgets_from_selection()


if __name__ == "__main__":
    root = tk.Tk()
    app = AppGUI(root)
    root.mainloop()
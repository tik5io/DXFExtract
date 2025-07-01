import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import os

# Import your DxfProcessor and GcodeVisualizer classes
from dxf_processor import DxfProcessor
from gcode_visualizer import GcodeVisualizer

# Configure logging for the application
logging.basicConfig(level=logging.INFO, format='[GCODE_VIS_APP] %(message)s')

class AppGUI:
    def __init__(self, master):
        self.master = master
        master.title("G-code Visualizer")
        master.geometry("1000x800")

        self.dxf_processor = DxfProcessor()
        self.current_dxf_entities = {}
        self.gcode_string = ""
        self.dxf_id_map = {}

        self.ordered_trajectories = []   # PATCH: liste de listes de segments (une par boucle/chemin)
        self.isolated_circles = []

        self.block_colors = {
            "ORDERED_TRAJECTORY": "blue",
            "ISOLATED_CIRCLES": "red",
            "HIGHLIGHT": "orange"
        }

        self.trajectory_colors = [
            "#FF6666", "#66CC66", "#6699FF", "#FFCC00", "#00CCCC", "#CC66FF", "#FF9966", "#66FFCC"
        ]

        self.create_widgets()
        self.gcode_text.tag_configure("highlight_gcode", background="#E0E0E0", foreground="blue")

    def create_widgets(self):
        # Top frame for controls
        top_frame = ttk.Frame(self.master, padding="10")
        top_frame.pack(side=tk.TOP, fill=tk.X)

        self.load_button = ttk.Button(top_frame, text="Load DXF", command=self.load_dxf_file)
        self.load_button.pack(side=tk.LEFT, padx=5)

        self.reverse_button = ttk.Button(top_frame, text="Inverser l'élément", command=self.reverse_selected_element)
        self.reverse_button.pack(side=tk.LEFT, padx=5)
        # Main content area - horizontally divided
        main_pane = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        main_pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left frame for G-code display
        left_frame = ttk.Frame(main_pane, relief=tk.SUNKEN, borderwidth=2)
        main_pane.add(left_frame, weight=1) # Give it weight so it expands

        self.gcode_text_label = ttk.Label(left_frame, text="Generated G-code:")
        self.gcode_text_label.pack(side=tk.TOP, padx=5, pady=5, anchor=tk.W)

        self.gcode_text = tk.Text(left_frame, wrap=tk.NONE, height=20, width=50) # Use tk.Text for multi-line
        self.gcode_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Add scrollbars to G-code text
        gcode_yscroll = ttk.Scrollbar(self.gcode_text, orient=tk.VERTICAL, command=self.gcode_text.yview)
        gcode_yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.gcode_text['yscrollcommand'] = gcode_yscroll.set

        gcode_xscroll = ttk.Scrollbar(self.gcode_text, orient=tk.HORIZONTAL, command=self.gcode_text.xview)
        gcode_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.gcode_text['xscrollcommand'] = gcode_xscroll.set
        
        # Bind an event for G-code text selection
        # Using <ButtonRelease-1> is more stable for "selection complete" than <<Selection>>
        self.gcode_text.bind("<ButtonRelease-1>", self.on_gcode_text_select)
        self.gcode_text.bind("<KeyRelease>", self.on_gcode_text_select) # For keyboard navigation


        # Right frame for Treeview and Matplotlib visualizer
        right_frame = ttk.Frame(main_pane, relief=tk.SUNKEN, borderwidth=2)
        main_pane.add(right_frame, weight=1) # Give it weight

        # Nested PanedWindow for Treeview (top-right) and Visualizer (bottom-right)
        right_pane_vertical = ttk.PanedWindow(right_frame, orient=tk.VERTICAL)
        right_pane_vertical.pack(fill=tk.BOTH, expand=True)

        # Treeview frame
        tree_frame = ttk.Frame(right_pane_vertical, relief=tk.FLAT)
        right_pane_vertical.add(tree_frame, weight=1)

        self.tree_label = ttk.Label(tree_frame, text="DXF Entities:")
        self.tree_label.pack(side=tk.TOP, padx=5, pady=5, anchor=tk.W)

        # Create Treeview
        self.tree = ttk.Treeview(tree_frame, columns=("DXF ID", "Action"), show="tree headings")
        self.tree.heading("#0", text="G-code Line #", anchor=tk.W)
        self.tree.heading("DXF ID", text="DXF ID", anchor=tk.W)
        self.tree.heading("Action", text="↔️", anchor=tk.CENTER)
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        tree_yscroll = ttk.Scrollbar(self.tree, orient=tk.VERTICAL, command=self.tree.yview)
        tree_yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree['yscrollcommand'] = tree_yscroll.set

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # Visualizer frame
        visualizer_frame = ttk.Frame(right_pane_vertical, relief=tk.FLAT)
        right_pane_vertical.add(visualizer_frame, weight=2) # Give more weight to visualizer

        self.gcode_visualizer = GcodeVisualizer(visualizer_frame) # Pass the frame to the visualizer

        # Drag-and-drop bindings
        self.tree.bind("<ButtonPress-1>", self.on_tree_drag_start)
        self.tree.bind("<B1-Motion>", self.on_tree_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_drag_drop)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_action_click)
        self._dragged_item = None

    def load_dxf_file(self):
        file_path = filedialog.askopenfilename(
            title="Select DXF File",
            filetypes=[("DXF Files", "*.dxf")]
        )
        if not file_path:
            return

        logging.info(f"[GCODE_VIS_APP] Loading DXF file: {file_path}")

        try:
            self.current_dxf_entities = self.dxf_processor.extract_dxf_entities(file_path)
            if self.current_dxf_entities is None:
                logging.error("[GCODE_VIS_APP] DXF extraction failed.")
                return

            # PATCH: multi-trajectoires
            self.ordered_trajectories, self.isolated_circles = self.dxf_processor.generate_auto_path(self.current_dxf_entities)

            # Concatène tous les segments pour le G-code
            all_segments = [seg for traj in self.ordered_trajectories for seg in traj]
            self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
                all_segments, self.isolated_circles, initial_start_point=(0.0, 0.0)
            )

            self.gcode_text.delete(1.0, tk.END)
            self.gcode_text.insert(tk.END, self.gcode_string)

            self.clear_treeview()
            self.populate_treeview()

            self.master.update_idletasks()

            self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)

            self.tree.selection_remove(self.tree.selection())
            self.gcode_text.tag_remove("highlight_gcode", "1.0", tk.END)
            self.gcode_visualizer.highlight_gcode_line(None)

            logging.info("[GCODE_VIS_APP] DXF file successfully loaded and processed.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load or process DXF: {e}")
            logging.exception("[GCODE_VIS_APP] Error loading or processing DXF.")

    def clear_treeview(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        logging.info("[GCODE_VIS_APP] Treeview cleared.")

    def populate_treeview(self):
        logging.info("[GCODE_VIS_APP] Populating Treeview...")

        reverse_dxf_map = {}
        for line_num, dxf_id in self.dxf_id_map.items():
            if isinstance(dxf_id, str) and (dxf_id.startswith(('L', 'A', 'C'))):
                if dxf_id not in reverse_dxf_map:
                    reverse_dxf_map[dxf_id] = []
                reverse_dxf_map[dxf_id].append(line_num)

        # PATCH: Un parent par boucle/chemin
        parent_ids = []
        for i, ordered_segments in enumerate(self.ordered_trajectories):
            parent_iid = f"ORDERED_TRAJECTORY_BLOCK_{i+1}"
            color = self.trajectory_colors[i % len(self.trajectory_colors)]
            tag = f"traj_color_{i}"
            self.tree.insert(
                "", "end", iid=parent_iid,
                text=f"● Ordered Trajectory {i+1}",
                values=(f"ORDERED_TRAJECTORY_{i+1}",),
                tags=(tag,)
            )
            self.tree.tag_configure(tag, foreground=color)
            for seg in ordered_segments:
                if seg['type'] == 'LINE':
                    dxf_id_str = f"L{seg['original_id']}"
                elif seg['type'] == 'ARC':
                    dxf_id_str = f"A{seg['original_id']}"
                else:
                    continue
                original_int_id = int(dxf_id_str[1:])
                display_text = self.current_dxf_entities.get(original_int_id, {}).get('id_display', f"DXF ID: {dxf_id_str}")
                entity_item_iid = dxf_id_str
                self.tree.insert(
                    parent_iid, "end", iid=entity_item_iid,
                    text=display_text,
                    values=(dxf_id_str, "↔️")
                )
                for line_num_0_based in sorted(reverse_dxf_map.get(dxf_id_str, [])):
                    line_num_1_based = line_num_0_based + 1
                    self.tree.insert(entity_item_iid, "end", text=f"G-code Line {line_num_1_based}", values=(f"LINE_GCODE_{line_num_1_based}",))

        # Isolated circles (inchangé)
        isolated_circles_parent = self.tree.insert("", "end", iid="ISOLATED_CIRCLES_BLOCK",
                                                   text="Isolated Circles", values=("ISOLATED_CIRCLES",))
        for seg in self.isolated_circles:
            if seg['type'] == 'CIRCLE':
                dxf_id_str = f"C{seg['original_id']}"
                original_int_id = int(dxf_id_str[1:])
                display_text = self.current_dxf_entities.get(original_int_id, {}).get('id_display', f"DXF ID: {dxf_id_str}")
                entity_item_iid = dxf_id_str
                self.tree.insert(isolated_circles_parent, "end", iid=entity_item_iid, text=display_text, values=(dxf_id_str,))
                for line_num_0_based in sorted(reverse_dxf_map.get(dxf_id_str, [])):
                    line_num_1_based = line_num_0_based + 1
                    self.tree.insert(entity_item_iid, "end", text=f"G-code Line {line_num_1_based}", values=(f"LINE_GCODE_{line_num_1_based}",))

        logging.info("[GCODE_VIS_APP] Treeview populated successfully.")

    def on_tree_select(self, event):
        selected_item_ids = self.tree.selection() # Get all selected items

        # Clear previous selections/highlights in other widgets
        self.gcode_text.tag_remove("highlight_gcode", "1.0", tk.END)
        self.gcode_visualizer.highlight_gcode_line(None) # Clear visualizer highlight

        if not selected_item_ids:
            logging.info("[GCODE_VIS_APP] Treeview selection cleared. Clearing all highlights.")
            return

        selected_item_id = selected_item_ids[0]

        # PATCH: surlignage par boucle
        if selected_item_id.startswith("ORDERED_TRAJECTORY_BLOCK_"):
            # Numéro de la boucle
            idx = int(selected_item_id.replace("ORDERED_TRAJECTORY_BLOCK_", "")) - 1
            if 0 <= idx < len(self.ordered_trajectories):
                # Récupère tous les dxf_id de la boucle
                dxf_ids = []
                for seg in self.ordered_trajectories[idx]:
                    if seg['type'] == 'LINE':
                        dxf_ids.append(f"L{seg['original_id']}")
                    elif seg['type'] == 'ARC':
                        dxf_ids.append(f"A{seg['original_id']}")
                # Surligne dans matplotlib et dans le gcode
                self.gcode_visualizer.highlight_gcode_line(dxf_ids)
                self._highlight_gcode_text_by_dxf_ids(dxf_ids)
                logging.info(f"[GCODE_VIS_APP] Treeview select event: Selected Block ID: ORDERED_TRAJECTORY_{idx+1}")
            return
        elif selected_item_id == "ISOLATED_CIRCLES_BLOCK":
            self.gcode_visualizer.highlight_gcode_line("ISOLATED_CIRCLES")
            self._highlight_gcode_text_by_block("ISOLATED_CIRCLES")
            logging.info(f"[GCODE_VIS_APP] Treeview select event: Selected Block ID: ISOLATED_CIRCLES")
            return
        else:
            # It's an individual DXF entity (L1, A2, C3) or a G-code line (LINE_GCODE_X)
            item_values = self.tree.item(selected_item_id, 'values')
            if item_values:
                selected_dxf_or_gcode_id = item_values[0]
                if selected_dxf_or_gcode_id.startswith("LINE_GCODE_"):
                    # If an individual G-code line is selected, we need its parent's DXF ID for visualizer highlight
                    parent_iid = self.tree.parent(selected_item_id)
                    if parent_iid:
                        parent_values = self.tree.item(parent_iid, 'values')
                        if parent_values:
                            selected_dxf_entity_id_for_highlight = parent_values[0]
                            logging.info(f"[GCODE_VIS_APP] Treeview select event: Selected G-code line {selected_dxf_or_gcode_id}, highlighting parent DXF ID: {selected_dxf_entity_id_for_highlight}")
                            self.gcode_visualizer.highlight_gcode_line(selected_dxf_entity_id_for_highlight)
                            # Highlight this specific G-code line in the text widget
                            line_num_1_based = int(selected_dxf_or_gcode_id.replace("LINE_GCODE_", ""))
                            self._apply_gcode_text_highlight([line_num_1_based - 1])
                            # Optionally, select the parent entity in the treeview as well:
                            # self.tree.selection_set(parent_iid)
                            return
                else:
                    # It's a direct DXF entity ID (L1, A2, C3)
                    logging.info(f"[GCODE_VIS_APP] Treeview select event: Selected DXF entity ID: {selected_dxf_or_gcode_id}")
                    self.gcode_visualizer.highlight_gcode_line(selected_dxf_or_gcode_id)
                    self._highlight_gcode_text_by_dxf_id(selected_dxf_or_gcode_id)
                    return
            else:
                # If no values, try to get parent (for robustness)
                parent_iid = self.tree.parent(selected_item_id)
                if parent_iid:
                    parent_values = self.tree.item(parent_iid, 'values')
                    if parent_values:
                        selected_dxf_entity_id_for_highlight = parent_values[0]
                        self.gcode_visualizer.highlight_gcode_line(selected_dxf_entity_id_for_highlight)
                        # Optionally, highlight all G-code lines for this entity
                        self._highlight_gcode_text_by_dxf_id(selected_dxf_entity_id_for_highlight)

    def on_tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        item_values = self.tree.item(item_id, 'values')
        if not item_values:
            return
        dxf_id = item_values[0]
        if dxf_id.startswith("L") or dxf_id.startswith("A"):
            # Trouver l'entité correspondante dans current_dxf_entities
            original_int_id = int(dxf_id[1:])
            start_entity_data = self.current_dxf_entities.get(original_int_id)
            if start_entity_data:
                # Recalcule la trajectoire à partir de cet élément
                self.ordered_trajectories, self.isolated_circles = self.dxf_processor.generate_auto_path(self.current_dxf_entities, start_entity_data)
                all_segments = [seg for traj in self.ordered_trajectories for seg in traj]
                self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(all_segments, self.isolated_circles, initial_start_point=(0.0, 0.0))
                self.gcode_text.delete(1.0, tk.END)
                self.gcode_text.insert(tk.END, self.gcode_string)
                self.clear_treeview()
                self.populate_treeview()
                self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)

    def reverse_selected_element(self):
        """Inverse le sens de l'élément sélectionné (ligne ou arc). Si bloc, inverse la trajectoire.
        Pour les éléments de 'ordered trajectory', force le rerouting pour garder la cohérence.
        Pour les éléments isolés, inverse juste le sens sans rerouting.
        """
        selected_item_ids = self.tree.selection()
        if not selected_item_ids:
            messagebox.showinfo("Aucune sélection", "Sélectionnez un élément à inverser dans l'arbre.")
            return

        selected_item_id = selected_item_ids[0]
        item_values = self.tree.item(selected_item_id, 'values')
        if not item_values:
            # Peut-être un bloc parent (ex: ORDERED_TRAJECTORY_BLOCK_1)
            if selected_item_id.startswith("ORDERED_TRAJECTORY_BLOCK_"):
                idx = int(selected_item_id.replace("ORDERED_TRAJECTORY_BLOCK_", "")) - 1
                if 0 <= idx < len(self.ordered_trajectories):
                    traj = self.ordered_trajectories[idx]
                    if traj:
                        # Inverser le premier segment
                        self.dxf_processor.reverse_segment_direction(traj[0])
                        # Inverser l'ordre de la trajectoire
                        traj = list(reversed(traj))
                        # Re-routing complet pour cohérence
                        self.ordered_trajectories, self.isolated_circles = self.dxf_processor.generate_auto_path(self.current_dxf_entities, traj[0])                        # Reconcatène tous les segments pour le G-code
                        all_segments = [seg for t in self.ordered_trajectories for seg in t]
                        self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
                            all_segments, self.isolated_circles, initial_start_point=(0.0, 0.0)
                        )
                        self.gcode_text.delete(1.0, tk.END)
                        self.gcode_text.insert(tk.END, self.gcode_string)
                        self.clear_treeview()
                        self.populate_treeview()
                        self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)
                return
            else:
                return

        dxf_id = item_values[0]
        # Si c'est une entité DXF (Lx ou Ax)
        if dxf_id.startswith("L") or dxf_id.startswith("A"):
            original_int_id = int(dxf_id[1:])
            found = False
            for traj_idx, traj in enumerate(self.ordered_trajectories):
                for seg in traj:
                    if seg['original_id'] == original_int_id and seg['type'][0] == dxf_id[0]:
                        self.dxf_processor.reverse_segment_direction(seg)
                        # Après inversion, on force le rerouting pour cohérence
                        self.ordered_trajectories, self.isolated_circles = self.dxf_processor.generate_auto_path(self.current_dxf_entities, seg)
                        found = True
                        break
                if found:
                    break
            all_segments = [seg for t in self.ordered_trajectories for seg in t]
            self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
                all_segments, self.isolated_circles, initial_start_point=(0.0, 0.0)
            )
            self.gcode_text.delete(1.0, tk.END)
            self.gcode_text.insert(tk.END, self.gcode_string)
            self.clear_treeview()
            self.populate_treeview()
            self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)
        # Si c'est un cercle isolé (C)
        elif dxf_id.startswith("C"):
            original_int_id = int(dxf_id[1:])
            for seg in self.isolated_circles:
                if seg['original_id'] == original_int_id and seg['type'][0] == dxf_id[0]:
                    self.dxf_processor.reverse_segment_direction(seg)
                    break
            all_segments = [seg for t in self.ordered_trajectories for seg in t]
            self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
                all_segments, self.isolated_circles, initial_start_point=(0.0, 0.0)
            )
            self.gcode_text.delete(1.0, tk.END)
            self.gcode_text.insert(tk.END, self.gcode_string)
            self.clear_treeview()
            self.populate_treeview()
            self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)
        # Si c'est un bloc complet
        elif dxf_id == "ORDERED_TRAJECTORY":
            if self.ordered_segments:
                self.dxf_processor.reverse_segment_direction(self.ordered_segments[0])
                self.ordered_segments = list(reversed(self.ordered_segments))
                # Re-routing complet pour cohérence
                self.ordered_segments, self.isolated_circles = self.dxf_processor.generate_auto_path(self.current_dxf_entities, self.ordered_segments[0])
                self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
                    self.ordered_segments, self.isolated_circles, initial_start_point=(0.0, 0.0)
                )
                self.gcode_text.delete(1.0, tk.END)
                self.gcode_text.insert(tk.END, self.gcode_string)
                self.clear_treeview()
                self.populate_treeview()
                self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)

    def on_tree_drag_start(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        values = self.tree.item(item, 'values')
        # Autoriser le drag sur les entités DXF OU sur les parents de boucle
        if (values and (values[0].startswith("L") or values[0].startswith("A") or values[0].startswith("C"))) \
            or (item.startswith("ORDERED_TRAJECTORY_BLOCK_")):
            self._dragged_item = item
        else:
            self._dragged_item = None

    def on_tree_drag_motion(self, event):
        # Optionnel : feedback visuel (curseur, etc.)
        pass

    def on_tree_drag_drop(self, event):
        if not self._dragged_item:
            return
        target_item = self.tree.identify_row(event.y)
        if not target_item or target_item == self._dragged_item:
            self._dragged_item = None
            return

        # --- PATCH: Drag & drop de boucles entières ---
        if self._dragged_item.startswith("ORDERED_TRAJECTORY_BLOCK_") and target_item.startswith("ORDERED_TRAJECTORY_BLOCK_"):
            src_idx = int(self._dragged_item.replace("ORDERED_TRAJECTORY_BLOCK_", "")) - 1
            dst_idx = int(target_item.replace("ORDERED_TRAJECTORY_BLOCK_", "")) - 1
            if src_idx == dst_idx or not (0 <= src_idx < len(self.ordered_trajectories)) or not (0 <= dst_idx < len(self.ordered_trajectories)):
                self._dragged_item = None
                return
            # Réordonne la liste des trajectoires
            traj = self.ordered_trajectories.pop(src_idx)
            self.ordered_trajectories.insert(dst_idx, traj)
            # Met à jour le G-code et l'affichage
            all_segments = [seg for t in self.ordered_trajectories for seg in t]
            self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
                all_segments, self.isolated_circles, initial_start_point=(0.0, 0.0)
            )
            self.gcode_text.delete(1.0, tk.END)
            self.gcode_text.insert(tk.END, self.gcode_string)
            self.clear_treeview()
            self.populate_treeview()
            self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)
            self._dragged_item = None
            return
        # --- Fin PATCH ---

        # Vérifie qu'on reste dans le même parent (même boucle)
        parent_src = self.tree.parent(self._dragged_item)
        parent_dst = self.tree.parent(target_item)
        if parent_src != parent_dst or not parent_src:
            self._dragged_item = None
            return

        # Récupère la liste de segments de la boucle concernée
        idx = int(parent_src.replace("ORDERED_TRAJECTORY_BLOCK_", "")) - 1
        if not (0 <= idx < len(self.ordered_trajectories)):
            self._dragged_item = None
            return

        # Récupère l'ordre actuel des entités dans la boucle
        segs = self.ordered_trajectories[idx]
        dragged_dxf_id = self.tree.item(self._dragged_item, 'values')[0]
        target_dxf_id = self.tree.item(target_item, 'values')[0]

        # Trouve les indices dans la liste
        dragged_idx = next((i for i, seg in enumerate(segs) if f"{seg['type'][0]}{seg['original_id']}" == dragged_dxf_id), None)
        target_idx = next((i for i, seg in enumerate(segs) if f"{seg['type'][0]}{seg['original_id']}" == target_dxf_id), None)
        if dragged_idx is None or target_idx is None:
            self._dragged_item = None
            return

        # Réordonne la liste
        seg = segs.pop(dragged_idx)
        segs.insert(target_idx, seg)

        # Met à jour la trajectoire et le G-code (pas de rerouting, juste l'ordre)
        all_segments = [seg for t in self.ordered_trajectories for seg in t]
        self.gcode_string, self.dxf_id_map = self.dxf_processor.generate_gcode(
            all_segments, self.isolated_circles, initial_start_point=(0.0, 0.0)
        )
        self.gcode_text.delete(1.0, tk.END)
        self.gcode_text.insert(tk.END, self.gcode_string)
        self.clear_treeview()
        self.populate_treeview()
        self.gcode_visualizer.update_gcode(self.gcode_string, self.dxf_id_map, self.block_colors)

        self._dragged_item = None

    def _apply_gcode_text_highlight(self, line_indices):
        """Surligne les lignes G-code (0-based) passées en paramètre."""
        self.gcode_text.tag_remove("highlight_gcode", "1.0", tk.END)
        for idx in line_indices:
            start = f"{idx+1}.0"
            end = f"{idx+1}.end"
            self.gcode_text.tag_add("highlight_gcode", start, end)

    def _highlight_gcode_text_by_dxf_id(self, dxf_id):
        """Surligne toutes les lignes G-code associées à un DXF ID."""
        indices = [i for i, v in self.dxf_id_map.items() if v == dxf_id]
        self._apply_gcode_text_highlight(indices)

    def _highlight_gcode_text_by_dxf_ids(self, dxf_ids):
        """Surligne toutes les lignes G-code associées à une liste de DXF IDs."""
        indices = [i for i, v in self.dxf_id_map.items() if v in dxf_ids]
        self._apply_gcode_text_highlight(indices)

    def _highlight_gcode_text_by_block(self, block_type):
        """Surligne toutes les lignes G-code d'un bloc (ORDERED_TRAJECTORY ou ISOLATED_CIRCLES)."""
        if block_type == "ORDERED_TRAJECTORY":
            indices = [i for i, v in self.dxf_id_map.items() if isinstance(v, str) and (v.startswith("L") or v.startswith("A"))]
        elif block_type == "ISOLATED_CIRCLES":
            indices = [i for i, v in self.dxf_id_map.items() if isinstance(v, str) and v.startswith("C")]
        else:
            indices = []
        self._apply_gcode_text_highlight(indices)

    def _select_treeview_item_by_dxf_id(self, dxf_id):
        """Sélectionne l'item Treeview correspondant à un DXF ID."""
        self.tree.selection_remove(self.tree.selection())
        if self.tree.exists(dxf_id):
            self.tree.selection_set(dxf_id)
            self.tree.see(dxf_id)

    def _select_treeview_item_by_gcode_line(self, line_idx):
        """Sélectionne l'item Treeview correspondant à une ligne G-code (0-based)."""
        dxf_id = self.dxf_id_map.get(line_idx)
        if not dxf_id:
            return
        # Cherche l'item enfant (ligne G-code) dans le Treeview
        for parent in self.tree.get_children():
            for entity in self.tree.get_children(parent):
                for child in self.tree.get_children(entity):
                    values = self.tree.item(child, 'values')
                    if values and values[0] == f"LINE_GCODE_{line_idx+1}":
                        self.tree.selection_remove(self.tree.selection())
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        return
        # Sinon, sélectionne l'entité DXF
        self._select_treeview_item_by_dxf_id(dxf_id)

    def on_gcode_text_select(self, event):
        """Callback lors de la sélection dans le widget G-code."""
        try:
            index = self.gcode_text.index(tk.INSERT)
            line_idx = int(index.split('.')[0]) - 1  # 0-based
            dxf_id = self.dxf_id_map.get(line_idx)
            if dxf_id and isinstance(dxf_id, str) and (dxf_id.startswith("L") or dxf_id.startswith("A") or dxf_id.startswith("C")):
                self.gcode_visualizer.highlight_gcode_line(dxf_id)
                self._apply_gcode_text_highlight([line_idx])
                self._select_treeview_item_by_dxf_id(dxf_id)
        except Exception:
            pass

    def on_tree_action_click(self, event):
        # Ignore si on vient de faire un drag and drop
        if getattr(self, "_dragged_item", None) is not None:
            return
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#3":  # "Action" est la 3e colonne (indexée à partir de 1)
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        values = self.tree.item(row_id, 'values')
        if not values or not (values[0].startswith("L") or values[0].startswith("A") or values[0].startswith("C")):
            return
        # Inverse l'élément sélectionné
        self.tree.selection_set(row_id)
        self.reverse_selected_element()

if __name__ == "__main__":
    root = tk.Tk()
    app = AppGUI(root)
    root.mainloop()

    logging.info("[GCODE_VIS_APP] Application started.")

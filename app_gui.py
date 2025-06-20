import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, ttk
import tkinter.font as tkfont
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import os
import copy

# Import our custom modules
from dxf_processor import DxfProcessor
from gcode_visualizer import GcodeVisualizer

class GcodeViewerApp:
    def __init__(self, root):
        self.root = root
        root.title("DXF to ISO G-code Viewer")

        self.dxf_processor = DxfProcessor(connection_tolerance=0.1)
        self.current_dxf_entities = {}
        self.ordered_segments_for_gui = [] # For LINE/ARC segments that form a path
        self.isolated_circles_for_gui = [] # New: For isolated CIRCLE entities
        self.current_dxf_segment_id_map = {}

        # --- Load Icons ---
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

        # Treeview for segments (replaces Listbox)
        self.treeview_frame = ttk.Frame(self.top_section_frame)
        self.treeview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Define columns for Treeview, adjusted for CIRCLE data
        self.treeview_columns = ("ID", "Type", "Début X / Centre X", "Début Y / Centre Y", "Fin X / Rayon", "Fin Y", "Inversé")
        self.segment_treeview = ttk.Treeview(self.treeview_frame, columns=self.treeview_columns, show="headings", height=15)

        # Configure column headings
        for col in self.treeview_columns:
            self.segment_treeview.heading(col, text=col, anchor=tk.W)
            self.segment_treeview.column(col, width=tkfont.Font().measure(col) + 10, anchor=tk.W)

        # Set specific column widths for better readability
        self.segment_treeview.column("ID", width=50, minwidth=50)
        self.segment_treeview.column("Type", width=90, minwidth=70) # Increased width for "LINE", "ARC", "CIRCLE"
        self.segment_treeview.column("Début X / Centre X", width=120, minwidth=90)
        self.segment_treeview.column("Début Y / Centre Y", width=120, minwidth=90)
        self.segment_treeview.column("Fin X / Rayon", width=100, minwidth=80)
        self.segment_treeview.column("Fin Y", width=80, minwidth=70)
        self.segment_treeview.column("Inversé", width=70, minwidth=60, anchor=tk.CENTER) # Increased width for "Oui" / "Non"

        self.segment_treeview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Bind events
        self.segment_treeview.bind("<Double-Button-1>", self.on_treeview_double_click)
        self.segment_treeview.bind("<<TreeviewSelect>>", self.on_treeview_select)

        self.treeview_scrollbar_y = ttk.Scrollbar(self.treeview_frame, orient=tk.VERTICAL, command=self.segment_treeview.yview)
        self.treeview_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.segment_treeview.config(yscrollcommand=self.treeview_scrollbar_y.set)

        self.treeview_scrollbar_x = ttk.Scrollbar(self.treeview_frame, orient=tk.HORIZONTAL, command=self.segment_treeview.xview)
        self.treeview_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.segment_treeview.config(xscrollcommand=self.treeview_scrollbar_x.set)

        # Buttons for list manipulation (right of treeview)
        self.list_controls_frame = ttk.Frame(self.top_section_frame, padding="2")
        self.list_controls_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))

        button_width = 12
        button_pady = 1

        self.move_up_button = ttk.Button(self.list_controls_frame, text="Monter", command=self.move_segment_up,
                                         image=self.icons["arrow_up"],
                                         compound=tk.LEFT if self.icons["arrow_up"] else tk.NONE,
                                         width=button_width)
        self.move_up_button.pack(fill=tk.X, pady=button_pady)

        self.move_down_button = ttk.Button(self.list_controls_frame, text="Descendre", command=self.move_segment_down,
                                           image=self.icons["arrow_down"],
                                           compound=tk.LEFT if self.icons["arrow_down"] else tk.NONE,
                                           width=button_width)
        self.move_down_button.pack(fill=tk.X, pady=button_pady)

        self.reverse_button = ttk.Button(self.list_controls_frame, text="Inverser Sens", command=self.reverse_selected_segment,
                                         image=self.icons["reverse"],
                                         compound=tk.LEFT if self.icons["reverse"] else tk.NONE,
                                         width=button_width)
        self.reverse_button.pack(fill=tk.X, pady=button_pady)

        self.delete_button = ttk.Button(self.list_controls_frame, text="Supprimer", command=self.delete_selected_segment,
                                        image=self.icons["delete"],
                                        compound=tk.LEFT if self.icons["delete"] else tk.NONE,
                                        width=button_width)
        self.delete_button.pack(fill=tk.X, pady=button_pady)

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

        self.visualizer = GcodeVisualizer(self.ax)

        # --- Initialisation au démarrage ---
        self.root.after(100, self.load_dxf_file_on_startup)


    def _update_segment_treeview(self):
        """Clears and repopulates the segment treeview from self.ordered_segments_for_gui and self.isolated_circles_for_gui."""
        # Clear existing items
        for item in self.segment_treeview.get_children():
            self.segment_treeview.delete(item)

        # Add ordered segments (LINE and ARC)
        if self.ordered_segments_for_gui:
            for segment_data in self.ordered_segments_for_gui:
                dxf_id = segment_data['original_id']
                seg_type = segment_data['type']
                reversed_display = "Oui" if segment_data.get('reversed', False) else "Non"

                # LINE and ARC will have start_point and end_point
                start_x = f"{segment_data['coords']['start_point'][0]:.4f}"
                start_y = f"{segment_data['coords']['start_point'][1]:.4f}"
                end_x = f"{segment_data['coords']['end_point'][0]:.4f}"
                end_y = f"{segment_data['coords']['end_point'][1]:.4f}"

                self.segment_treeview.insert("", tk.END,
                                             values=(dxf_id, seg_type,
                                                     start_x, start_y,
                                                     end_x, end_y,
                                                     reversed_display))

        # Add a separator if there are circles AND segments
        if self.ordered_segments_for_gui and self.isolated_circles_for_gui:
            self.segment_treeview.insert("", tk.END, "separator_circles", text="",
                                         values=("---", "Cercles", "Isolés", "---", "---", "---", "---"),
                                         tags=("separator",))
            self.segment_treeview.tag_configure("separator", foreground="blue", font=('TkDefaultFont', 9, 'bold'))


        # Add isolated circles
        if self.isolated_circles_for_gui:
            for circle_data in self.isolated_circles_for_gui:
                dxf_id = circle_data['original_id']
                seg_type = circle_data['type']
                center_x = f"{circle_data['coords']['center'][0]:.4f}"
                center_y = f"{circle_data['coords']['center'][1]:.4f}"
                radius = f"{circle_data['coords']['radius']:.4f}"

                # For circles, 'Fin X' column is used for Radius, and 'Fin Y' is empty
                self.segment_treeview.insert("", tk.END,
                                             values=(dxf_id, seg_type,
                                                     center_x, center_y,
                                                     radius, "", # Fin Y is empty for circles
                                                     "N/A")) # Reversed is not applicable for circles

    def load_dxf_file_on_startup(self):
        """Called once at startup to prompt for DXF file."""
        self.load_dxf_file()

    def load_dxf_file(self):
        """Opens file dialog, loads DXF, and triggers auto-generation."""
        filepath = filedialog.askopenfilename(
            title="Sélectionner un fichier DXF",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")]
        )
        if filepath:
            self.current_dxf_file = filepath
            self.current_dxf_entities = self.dxf_processor.extract_dxf_entities(filepath)

            if self.current_dxf_entities is None or not self.current_dxf_entities:
                messagebox.showerror("Erreur de Fichier DXF", "Aucune entité valide trouvée dans le fichier DXF ou le fichier est vide.")
                self.current_dxf_file = None
                self.current_dxf_entities = {}
                self.gcode_text.delete(1.0, tk.END)
                self.visualizer.reset_plot()
                self.ordered_segments_for_gui = []
                self.isolated_circles_for_gui = [] # Reset circles too
                self._update_segment_treeview()
            else:
                self.ordered_segments_for_gui = [] # Clear previous order
                self.isolated_circles_for_gui = [] # Clear previous circles
                self._regenerate_auto_path_and_gcode(start_entity_data=None)
        else:
            if not hasattr(self, 'current_dxf_file') or not self.current_dxf_file:
                messagebox.showinfo("Annulé", "Aucun fichier DXF sélectionné. L'application va se fermer.")
                self.root.destroy()
            else:
                pass

    def _regenerate_auto_path_and_gcode(self, start_entity_data=None):
        """
        Helper method to regenerate the path automatically and then the G-code.
        Encapsulates the two-step process.
        """
        # Call generate_auto_path which now returns two lists
        ordered_segments, isolated_circles = self.dxf_processor.generate_auto_path(
            self.current_dxf_entities, start_entity_data
        )

        self.ordered_segments_for_gui = ordered_segments
        self.isolated_circles_for_gui = isolated_circles

        self._update_segment_treeview()
        self._generate_gcode_from_current_order()

    def _generate_gcode_from_current_order(self):
        """
        Generates G-code based on the current order in self.ordered_segments_for_gui
        and updates the text area and visualization.
        """
        if not self.ordered_segments_for_gui and not self.isolated_circles_for_gui:
            self.gcode_text.delete(1.0, tk.END)
            self.visualizer.reset_plot()
            self.current_dxf_segment_id_map = {}
            return

        # Pass both lists to generate_gcode
        generated_gcode, dxf_id_map = self.dxf_processor.generate_gcode(
            self.ordered_segments_for_gui, self.isolated_circles_for_gui, (0.0, 0.0)
        )

        if generated_gcode:
            self.gcode_text.delete(1.0, tk.END)
            self.gcode_text.insert(tk.END, generated_gcode)

            self.current_dxf_segment_id_map = dxf_id_map

            self.visualizer.visualize(generated_gcode, dxf_segment_id_map=self.current_dxf_segment_id_map)

    def on_gcode_text_click(self, event):
        """Handles click events in the G-code text area for highlighting and Treeview synchronization."""
        index = self.gcode_text.index(tk.CURRENT)
        line_num = int(float(index))
        gcode_line_index = line_num - 1 # Convert to 0-based index for map

        # Highlight G-code text
        self.gcode_text.tag_remove("highlight", 1.0, tk.END)
        self.gcode_text.tag_add("highlight", f"{line_num}.0", f"{line_num}.end")

        # Highlight in Matplotlib
        self.visualizer.highlight_elements(gcode_line_index)

        # Find corresponding DXF segment ID and select in Treeview
        dxf_segment_id_to_select = None
        if gcode_line_index in self.current_dxf_segment_id_map:
            dxf_segment_id_to_select = self.current_dxf_segment_id_map[gcode_line_index]

            # Find and select corresponding item in Treeview
            self.segment_treeview.selection_remove(self.segment_treeview.selection()) # Deselect any current
            found_item_id = None
            for item_id in self.segment_treeview.get_children():
                # Skip separator
                if self.segment_treeview.tag_has("separator", item_id):
                    continue

                item_values = self.segment_treeview.item(item_id, 'values')
                # The first value in the Treeview is the 'original_id'
                if item_values and str(item_values[0]) == str(dxf_segment_id_to_select): # Compare as strings for safety
                    found_item_id = item_id
                    break

            if found_item_id:
                self.segment_treeview.selection_set(found_item_id)
                self.segment_treeview.focus(found_item_id) # Set focus to the item
                self.segment_treeview.see(found_item_id) # Scroll to make it visible

    def on_treeview_select(self, event):
        """Handles selection in the Treeview to highlight corresponding G-code and visualization."""
        selected_item_ids = self.segment_treeview.selection()
        if not selected_item_ids:
            # No item selected (e.g., click outside an item), clear highlights
            self.gcode_text.tag_remove("highlight", 1.0, tk.END)
            self.visualizer.clear_highlights()
            return

        selected_item_id = selected_item_ids[0]
        # Skip if it's the separator item
        if self.segment_treeview.tag_has("separator", selected_item_id):
            self.gcode_text.tag_remove("highlight", 1.0, tk.END)
            self.visualizer.clear_highlights()
            return

        item_values = self.segment_treeview.item(selected_item_id, 'values')

        if item_values:
            selected_original_id = item_values[0] # Get the 'original_id' from Treeview

            # Find the corresponding G-code line index
            gcode_line_to_highlight = -1
            # Iterate through the map to find the G-code line associated with this original ID
            for gcode_idx, original_id_in_map in self.current_dxf_segment_id_map.items():
                if str(original_id_in_map) == str(selected_original_id): # Compare as strings
                    gcode_line_to_highlight = gcode_idx
                    break

            if gcode_line_to_highlight != -1:
                # Highlight G-code text (Tkinter line numbers are 1-based)
                self.gcode_text.tag_remove("highlight", 1.0, tk.END)
                self.gcode_text.tag_add("highlight", f"{gcode_line_to_highlight + 1}.0", f"{gcode_line_to_highlight + 1}.end")
                self.gcode_text.see(f"{gcode_line_to_highlight + 1}.0") # Scroll to make visible

                # Highlight in Matplotlib
                self.visualizer.highlight_elements(gcode_line_to_highlight)
            else:
                self.gcode_text.tag_remove("highlight", 1.0, tk.END)
                self.visualizer.clear_highlights() # Clear if no mapping

    def on_treeview_double_click(self, event):
        """Handles double-click on treeview items to trigger auto-regeneration."""
        selected_item_ids = self.segment_treeview.selection()
        if not selected_item_ids:
            return

        selected_item_id = selected_item_ids[0]
        # Skip if it's the separator item or a circle (double-click to restart path only applies to segments)
        if self.segment_treeview.tag_has("separator", selected_item_id) or \
           self.segment_treeview.item(selected_item_id, 'values')[1] == 'CIRCLE':
            messagebox.showinfo("Action non applicable", "Vous ne pouvez pas démarrer un chemin automatique avec un élément non-ligne/arc ou un séparateur.")
            return

        selected_index = self.segment_treeview.index(selected_item_id)
        selected_segment_data = self.ordered_segments_for_gui[selected_index]

        if messagebox.askyesno("Recommencer Auto", f"Voulez-vous régénérer le chemin automatiquement en commençant par l'ID '{selected_segment_data['original_id']}' ?\n(Toutes les modifications manuelles de l'ordre seront perdues.)"):
            self._regenerate_auto_path_and_gcode(start_entity_data=copy.deepcopy(selected_segment_data))

    def move_segment_up(self):
        """Moves the selected segment up in the list."""
        selected_item_ids = self.segment_treeview.selection()
        if not selected_item_ids:
            messagebox.showwarning("Déplacement", "Veuillez sélectionner un segment à déplacer.")
            return

        selected_item_id = selected_item_ids[0]
        # Prevent moving separator or circles using these controls
        if self.segment_treeview.tag_has("separator", selected_item_id) or \
           self.segment_treeview.item(selected_item_id, 'values')[1] == 'CIRCLE':
            messagebox.showinfo("Action non applicable", "Cette action n'est pas applicable aux cercles ou séparateurs.")
            return

        idx = self.segment_treeview.index(selected_item_id)

        if idx > 0:
            segment = self.ordered_segments_for_gui.pop(idx)
            self.ordered_segments_for_gui.insert(idx - 1, segment)
            self._update_segment_treeview()

            # Re-select the moved item
            # We need to find the new item_id because indices might shift due to separator
            new_item_id_found = False
            for new_id in self.segment_treeview.get_children():
                if self.segment_treeview.item(new_id, 'values')[0] == segment['original_id'] and \
                   self.segment_treeview.item(new_id, 'values')[1] == segment['type']:
                    self.segment_treeview.selection_set(new_id)
                    self.segment_treeview.focus(new_id)
                    new_item_id_found = True
                    break
            if new_item_id_found:
                self._generate_gcode_from_current_order()
            else:
                # Fallback if item not found (shouldn't happen with unique original_id)
                self.segment_treeview.selection_set(self.segment_treeview.get_children()[idx-1]) # Try by original index
                self.segment_treeview.focus(self.segment_treeview.get_children()[idx-1])
                self._generate_gcode_from_current_order()


    def move_segment_down(self):
        """Moves the selected segment down in the list."""
        selected_item_ids = self.segment_treeview.selection()
        if not selected_item_ids:
            messagebox.showwarning("Déplacement", "Veuillez sélectionner un segment à déplacer.")
            return

        selected_item_id = selected_item_ids[0]
        # Prevent moving separator or circles using these controls
        if self.segment_treeview.tag_has("separator", selected_item_id) or \
           self.segment_treeview.item(selected_item_id, 'values')[1] == 'CIRCLE':
            messagebox.showinfo("Action non applicable", "Cette action n'est pas applicable aux cercles ou séparateurs.")
            return

        idx = self.segment_treeview.index(selected_item_id)

        if idx < len(self.ordered_segments_for_gui) - 1: # Only allow moving within the ordered segments list
            segment = self.ordered_segments_for_gui.pop(idx)
            self.ordered_segments_for_gui.insert(idx + 1, segment)
            self._update_segment_treeview()

            # Re-select the moved item
            new_item_id_found = False
            for new_id in self.segment_treeview.get_children():
                if self.segment_treeview.item(new_id, 'values')[0] == segment['original_id'] and \
                   self.segment_treeview.item(new_id, 'values')[1] == segment['type']:
                    self.segment_treeview.selection_set(new_id)
                    self.segment_treeview.focus(new_id)
                    new_item_id_found = True
                    break
            if new_item_id_found:
                self._generate_gcode_from_current_order()
            else:
                # Fallback
                self.segment_treeview.selection_set(self.segment_treeview.get_children()[idx+1])
                self.segment_treeview.focus(self.segment_treeview.get_children()[idx+1])
                self._generate_gcode_from_current_order()

    def reverse_selected_segment(self):
        """Reverses the direction of the selected segment."""
        selected_item_ids = self.segment_treeview.selection()
        if not selected_item_ids:
            messagebox.showwarning("Inverser", "Veuillez sélectionner un segment à inverser.")
            return

        selected_item_id = selected_item_ids[0]
        # Prevent reversing separator or circles
        if self.segment_treeview.tag_has("separator", selected_item_id) or \
           self.segment_treeview.item(selected_item_id, 'values')[1] == 'CIRCLE':
            messagebox.showinfo("Action non applicable", "Cette action n'est applicable qu'aux lignes et aux arcs.")
            return

        idx = self.segment_treeview.index(selected_item_id)
        segment_data = self.ordered_segments_for_gui[idx]

        self.dxf_processor.reverse_segment_direction(segment_data)

        self._update_segment_treeview() # Update treeview to reflect the change

        # Re-select the item
        new_item_id_found = False
        for new_id in self.segment_treeview.get_children():
            if self.segment_treeview.item(new_id, 'values')[0] == segment_data['original_id'] and \
               self.segment_treeview.item(new_id, 'values')[1] == segment_data['type']:
                self.segment_treeview.selection_set(new_id)
                self.segment_treeview.focus(new_id)
                new_item_id_found = True
                break
        if new_item_id_found:
            self._generate_gcode_from_current_order()

    def delete_selected_segment(self):
        """Deletes the selected segment from the list."""
        selected_item_ids = self.segment_treeview.selection()
        if not selected_item_ids:
            messagebox.showwarning("Supprimer", "Veuillez sélectionner un segment à supprimer.")
            return

        selected_item_id = selected_item_ids[0]
        # Prevent deleting separator
        if self.segment_treeview.tag_has("separator", selected_item_id):
            messagebox.showinfo("Action non applicable", "Vous ne pouvez pas supprimer le séparateur.")
            return

        item_values = self.segment_treeview.item(selected_item_id, 'values')
        original_id_to_delete = item_values[0] # This is a string
        type_to_delete = item_values[1]

        if messagebox.askyesno("Supprimer Élément", f"Êtes-vous sûr de vouloir supprimer l'élément avec l'ID '{original_id_to_delete}' de type '{type_to_delete}' de la liste ?"):
            if type_to_delete in ['LINE', 'ARC']:
                # Find and remove from ordered_segments_for_gui
                self.ordered_segments_for_gui = [
                    seg for seg in self.ordered_segments_for_gui
                    # Cast original_id from internal data to string for comparison
                    if not (str(seg['original_id']) == original_id_to_delete and seg['type'] == type_to_delete)
                ]
            elif type_to_delete == 'CIRCLE':
                # Find and remove from isolated_circles_for_gui
                self.isolated_circles_for_gui = [
                    circ for circ in self.isolated_circles_for_gui
                    # Cast original_id from internal data to string for comparison
                    if not (str(circ['original_id']) == original_id_to_delete and circ['type'] == type_to_delete)
                ]
            else:
                messagebox.showerror("Erreur de suppression", "Type d'entité inconnu pour la suppression.")
                return

            # After modifying the internal lists, update the Treeview and regenerate G-code
            self._update_segment_treeview()
            self._generate_gcode_from_current_order()

# Main execution block
if __name__ == "__main__":
    root = tk.Tk()
    app = GcodeViewerApp(root)
    root.mainloop()
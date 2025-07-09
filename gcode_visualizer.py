import tkinter as tk
from tkinter import Canvas
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.lines import Line2D
import logging
import math # Import math module for fmod
from typing import List, Dict, Tuple, Any
from matplotlib.colors import to_rgba 

logging.basicConfig(level=logging.INFO, format='[GCODE_VIS] %(message)s')

class GcodeVisualizer(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.figure, self.ax = plt.subplots(figsize=(8, 6))
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._configure_plot()

        self.path_artists: Dict[str, List[Any]] = {} # Map: original_id -> list of matplotlib artists (Line2D or patches)
        # Store original colors for highlighting
        self.original_artist_colors: Dict[Any, Dict[str, Any]] = {} # artist -> {'facecolor': ..., 'edgecolor': ..., 'linecolor': ...}

        # Connect event for mouse scroll (zoom)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        # Connect events for pan
        self.canvas.mpl_connect('button_press_event', self._on_button_press)
        self.canvas.mpl_connect('button_release_event', self._on_button_release)
        self.canvas.mpl_connect('motion_notify_event', self._on_motion)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        
        self._pan_start = None
        self._xlim_at_press = None
        self._ylim_at_press = None

    def _configure_plot(self):
        """Configure l'aspect du graphique pour un affichage épuré avec axes XY minimalistes."""
        self.ax.set_aspect('equal', adjustable='datalim')
        self.ax.axis('off')  # Supprime axes, ticks, cadre, etc.
        self.ax.grid(False)
        self.ax.set_title("")
        self.ax.legend_ = None

        # Supprime tout ce qui reste
        self.ax.xaxis.set_visible(False)
        self.ax.yaxis.set_visible(False)
        self.ax.set_xticks([])
        self.ax.set_yticks([])

        # Ajoute deux flèches pour X et Y depuis l'origine
        arrow_len = 10  # Ajuste la longueur selon ton échelle
        self.ax.annotate('', xy=(arrow_len, 0), xytext=(0, 0),
                         arrowprops=dict(facecolor='black', width=1.5, headwidth=8))
        self.ax.annotate('', xy=(0, arrow_len), xytext=(0, 0),
                         arrowprops=dict(facecolor='black', width=1.5, headwidth=8))
        # Labels X et Y
        self.ax.text(arrow_len + 1, 0, "X", fontsize=10, va='center', ha='left')
        self.ax.text(0, arrow_len + 1, "Y", fontsize=10, va='bottom', ha='center')

   
    def _on_scroll(self, event):
        if event.xdata is None or event.ydata is None:
            return  # souris en dehors du graphe

        base_scale = 1.2  # facteur de zoom (zoom in/out)
        scale = base_scale if event.step < 0 else 1 / base_scale

        xdata, ydata = event.xdata, event.ydata
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        # Calcul des nouvelles limites avec effet de zoom centré sur la souris
        new_xlim = [
            xdata - (xdata - xlim[0]) * scale,
            xdata + (xlim[1] - xdata) * scale
        ]
        new_ylim = [
            ydata - (ydata - ylim[0]) * scale,
            ydata + (ylim[1] - ydata) * scale
        ]

        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)
        self.canvas.draw_idle()

    def _on_button_press(self, event):
        if event.button == 1 and event.xdata is not None and event.ydata is not None:
            self._pan_start = (event.xdata, event.ydata)
            self._xlim_at_press = self.ax.get_xlim()
            self._ylim_at_press = self.ax.get_ylim()

    def _on_button_release(self, event):
        if event.button == 1:
            self._pan_start = None

    def _on_motion(self, event):
        if self._pan_start is None or event.xdata is None or event.ydata is None:
            return

        dx = event.xdata - self._pan_start[0]
        dy = event.ydata - self._pan_start[1]

        new_xlim = (self._xlim_at_press[0] - dx, self._xlim_at_press[1] - dx)
        new_ylim = (self._ylim_at_press[0] - dy, self._ylim_at_press[1] - dy)

        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)
        self.canvas.draw_idle()

    def draw_gcode_path(self, segments: List[Dict]):
        """
        Dessine le chemin G-code sur le graphique Matplotlib.
        segments: Liste de dictionnaires, chacun décrivant un segment (ligne, arc, cercle).
                Chaque dict doit contenir 'type', 'coords', 'color', 'original_id'.
                'coords' varie selon le type.
                Pour les arcs, 'direction_reversed' peut être présent.
        """
        print(f"[INFO] Appel de draw_gcode_path avec {len(segments)} segments.")
        self.ax.clear()
        self._configure_plot()

        self.path_artists.clear()
        self.original_artist_colors.clear()

        all_x = []
        all_y = []

        for segment in segments:
            seg_type = segment.get('type')
            coords = segment.get('coords', {})
            color = segment.get('color', 'blue')
            original_id = segment.get('original_id', 'unknown')
            artist = None

            is_jump = str(original_id).startswith("JUMP_TO_")  # G0?

            try:
                if seg_type == 'LINE':
                    x1, y1 = coords['start_point']
                    x2, y2 = coords['end_point']
                    linestyle = '--' if is_jump else '-'
                    linewidth = 1 if is_jump else 2
                    line_color = 'gray' if is_jump else color

                    print(f"[DEBUG] LINE {x1, y1} → {x2, y2} | jump={is_jump}")
                    artist = Line2D([x1, x2], [y1, y2], color=line_color, linestyle=linestyle, linewidth=linewidth)
                    self.ax.add_line(artist)
                    all_x.extend([x1, x2])
                    all_y.extend([y1, y2])

                elif seg_type == 'ARC':
                    center_x, center_y = coords['center']
                    radius = coords['radius']
                    start_angle = coords['start_angle'] % 360
                    end_angle = coords['end_angle'] % 360
                    direction_reversed = segment.get('direction_reversed', False)

                    if direction_reversed:  # G3
                        theta1, theta2 = start_angle, end_angle
                        if theta2 <= theta1:
                            theta2 += 360
                    else:  # G2
                        theta1, theta2 = start_angle, end_angle
                        if theta2 >= theta1:
                            theta2 -= 360

                    print(f"[DEBUG] ARC center=({center_x}, {center_y}), r={radius}, θ=({theta1}→{theta2}), reversed={direction_reversed}")
                    artist = patches.Arc((center_x, center_y), 2 * radius, 2 * radius,
                                        angle=0, theta1=theta1, theta2=theta2, color=color,
                                        linewidth=2, fill=False)
                    self.ax.add_patch(artist)
                    x1, y1 = coords['start_point']
                    x2, y2 = coords['end_point']
                    all_x.extend([x1, x2])
                    all_y.extend([y1, y2])

                elif seg_type == 'CIRCLE':
                    center_x, center_y = coords['center']
                    radius = coords['radius']
                    print(f"[DEBUG] CIRCLE center=({center_x}, {center_y}), r={radius}")
                    artist = patches.Circle((center_x, center_y), radius, color=color, fill=False, linewidth=2)
                    self.ax.add_patch(artist)
                    all_x.extend([center_x - radius, center_x + radius])
                    all_y.extend([center_y - radius, center_y + radius])

                else:
                    print(f"[WARNING] Type de segment inconnu: {seg_type}")
                    continue

                if artist:
                    if original_id not in self.path_artists:
                        self.path_artists[original_id] = []
                    self.path_artists[original_id].append(artist)

                    if isinstance(artist, Line2D):
                        self.original_artist_colors[artist] = {'linecolor': artist.get_color()}
                    elif isinstance(artist, patches.Patch):
                        self.original_artist_colors[artist] = {
                            'facecolor': artist.get_facecolor(),
                            'edgecolor': artist.get_edgecolor()
                        }

            except Exception as e:
                print(f"[ERROR] Exception pour {seg_type}: {e} | segment={segment}")

        if all_x and all_y:
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
            padding = max((max_x - min_x) * 0.1, (max_y - min_y) * 0.1, 10)
            self.ax.set_xlim(min_x - padding, max_x + padding)
            self.ax.set_ylim(min_y - padding, max_y + padding)
            self.ax.set_aspect('equal')
        else:
            self.ax.set_xlim(-100, 100)
            self.ax.set_ylim(-100, 100)

        self.canvas.draw_idle()
        logging.info(f"Dessin de {len(segments)} segments sur le visualiseur.")


    def highlight_dxf_entities_by_ids(self, selected_dxf_ids: List[str]):
        """
        Met en surbrillance les entités DXF spécifiées par leurs IDs.
        selected_dxf_ids: Liste des original_id des entités à mettre en surbrillance.
        """
        highlight_color = 'magenta' # Couleur de surbrillance
        default_linewidth = 2
        highlight_linewidth = 4 # Rendre la ligne plus épaisse pour la surbrillance

        logging.info(f"Mise en surbrillance des IDs DXF: {selected_dxf_ids}")

        # D'abord, restaurer la couleur de tous les artistes
        for artist, colors_dict in self.original_artist_colors.items():
            if isinstance(artist, Line2D):
                artist.set_color(colors_dict['linecolor'])
                artist.set_linewidth(default_linewidth)
            elif isinstance(artist, patches.Patch): # Covers Circle and Arc
                artist.set_facecolor(colors_dict['facecolor'])
                artist.set_edgecolor(colors_dict['edgecolor'])
                artist.set_linewidth(default_linewidth)

        # Ensuite, appliquer la surbrillance aux artistes sélectionnés
        for dxf_id in selected_dxf_ids:
            artists_for_id = self.path_artists.get(dxf_id, [])
            for artist in artists_for_id:
                if isinstance(artist, Line2D):
                    artist.set_color(highlight_color)
                    artist.set_linewidth(highlight_linewidth)
                elif isinstance(artist, patches.Patch): # Covers Circle and Arc
                    # Convertir la couleur de surbrillance en RGBA et ajuster l'alpha
                    rgba_color = to_rgba(highlight_color)
                    transparent_highlight_color = (rgba_color[0], rgba_color[1], rgba_color[2], 0.5)
                    artist.set_facecolor(transparent_highlight_color) # Utiliser la couleur transparente pour le remplissage
                    artist.set_edgecolor(highlight_color) # Garder la couleur opaque pour les bords
                    artist.set_linewidth(highlight_linewidth)
        self.canvas.draw_idle()

    def _fit_plot_to_content(self):
        """Ajuste les limites du graphique pour occuper ~90% de la surface du widget."""
        all_x = []
        all_y = []
        # Récupère tous les points extrêmes des segments
        for seg in self.gcode_lines:
            if seg['type'] == 'LINE':
                all_x.extend([seg['start_x'], seg['end_x']])
                all_y.extend([seg['start_y'], seg['end_y']])
            elif seg['type'] == 'ARC':
                # Ajoute le centre et le rayon pour estimer le bounding box de l'arc
                cx, cy = seg['center_x'], seg['center_y']
                r = seg['radius']
                all_x.extend([cx - r, cx + r])
                all_y.extend([cy - r, cy + r])
            elif seg['type'] == 'CIRCLE':
                cx, cy = seg['center_x'], seg['center_y']
                r = seg['radius']
                all_x.extend([cx - r, cx + r])
                all_y.extend([cy - r, cy + r])
        if not all_x or not all_y:
            self.ax.set_xlim(-10, 10)
            self.ax.set_ylim(-10, 10)
            return

        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        dx = max_x - min_x
        dy = max_y - min_y
        # Padding de 5% de chaque côté
        pad_x = dx * 0.05 if dx > 0 else 1.0
        pad_y = dy * 0.05 if dy > 0 else 1.0
        self.ax.set_xlim(min_x - pad_x, max_x + pad_x)
        self.ax.set_ylim(min_y - pad_y, max_y + pad_y)
        self.canvas.draw_idle()
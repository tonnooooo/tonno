"""Kit di costruzione dei blockout (richiede ``bpy``: gira solo dentro Blender).

Prende una spec gia' validata e normalizzata da ``spec.py`` e costruisce la
scena: render Cycles, mondo e luci, prefab parametrici (manichino, auto,
citta', interni...), primitive, animazioni cotte fotogramma per fotogramma
(matematica in ``moto.py``), camera e compositor (glow + vignettatura).

Stile: blockout pulito senza texture, manichini avorio lucidi, accenti neri,
pannelli emissivi pastello, pavimenti riflettenti. Il fronte dei prefab guarda
verso -Y; unita' in metri, Z in alto.
"""
from __future__ import annotations

import json
import math
import random
from typing import Any, Sequence

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from . import moto
from . import spec as S

# ---------------------------------------------------------------------------
# Utilita' di base
# ---------------------------------------------------------------------------


def srgb_a_lineare(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def colore(v, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Colore della spec (sRGB) -> RGBA lineare per i nodi di Blender."""
    r, g, b = S.hex_a_rgb(v)
    return (srgb_a_lineare(r), srgb_a_lineare(g), srgb_a_lineare(b), alpha)


def rad(v: Sequence[float]) -> tuple[float, float, float]:
    return tuple(math.radians(x) for x in v)  # type: ignore[return-value]


def vec3(v) -> tuple[float, float, float]:
    if isinstance(v, (int, float)):
        return (float(v), float(v), float(v))
    return (float(v[0]), float(v[1]), float(v[2]))


def svuota_scena() -> None:
    """Rimuove tutto dalla scena di avvio (cubo, luce, camera di default)."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.curves):
        for item in list(coll):
            if item.users == 0:
                coll.remove(item)


def _nodi(idblock):
    """Restituisce l'albero di nodi di un materiale/mondo (5.x li crea sempre)."""
    if getattr(idblock, "node_tree", None) is None:
        try:
            idblock.use_nodes = True
        except AttributeError:  # pragma: no cover
            pass
    return idblock.node_tree


# ---------------------------------------------------------------------------
# Costruzione di mesh multi-materiale
# ---------------------------------------------------------------------------


class Mesh:
    """Accumula parti (box, torniti, estrusi, aste) in un'unica mesh.

    Ogni parte ha il suo materiale e la sua ombreggiatura: un prefab intero
    diventa cosi' uno o pochi oggetti, con meno overhead in Cycles.
    """

    def __init__(self) -> None:
        self.v: list[tuple[float, float, float]] = []
        self.f: list[tuple[int, ...]] = []
        self.mi: list[int] = []
        self.sm: list[bool] = []
        self.mats: list[Any] = []

    def _mat(self, m) -> int:
        chiave = json.dumps(m, sort_keys=True, default=str)
        for i, k in enumerate(self.mats):
            if json.dumps(k, sort_keys=True, default=str) == chiave:
                return i
        self.mats.append(m)
        return len(self.mats) - 1

    def parte(self, verts, facce, mat, liscio: bool = False, matrice: Matrix | None = None) -> None:
        base = len(self.v)
        for p in verts:
            if matrice is not None:
                p = matrice @ Vector(p)
            self.v.append((p[0], p[1], p[2]))
        i = self._mat(mat)
        for fc in facce:
            self.f.append(tuple(base + x for x in fc))
            self.mi.append(i)
            self.sm.append(liscio)

    def box(self, centro, dim, mat, rot=(0.0, 0.0, 0.0), matrice: Matrix | None = None) -> None:
        """Parallelepipedo di dimensioni ``dim`` centrato in ``centro`` (rot in gradi)."""
        hx, hy, hz = dim[0] / 2, dim[1] / 2, dim[2] / 2
        vs = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
              (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
        m = Matrix.Translation(centro) @ Euler(rad(rot)).to_matrix().to_4x4()
        if matrice is not None:
            m = matrice @ m
        facce = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        self.parte(vs, facce, mat, False, m)

    def tornio(self, profilo, mat, segmenti: int = 32, centro=(0.0, 0.0, 0.0), scala=(1.0, 1.0),
               liscio: bool = True, matrice: Matrix | None = None, chiudi: bool = True) -> None:
        """Superficie di rotazione attorno a Z da un profilo [(raggio, z), ...]."""
        vs: list[tuple[float, float, float]] = []
        anelli: list[list[int]] = []
        for r, z in profilo:
            if r <= 1e-6:
                anelli.append([len(vs)])
                vs.append((0.0, 0.0, z))
            else:
                anello = []
                for k in range(segmenti):
                    a = 2 * math.pi * k / segmenti
                    anello.append(len(vs))
                    vs.append((r * math.cos(a) * scala[0], r * math.sin(a) * scala[1], z))
                anelli.append(anello)
        facce: list[tuple[int, ...]] = []
        for a, b in zip(anelli, anelli[1:]):
            if len(a) == 1 and len(b) == 1:
                continue
            if len(a) == 1:
                facce += [(a[0], b[k], b[(k + 1) % segmenti]) for k in range(segmenti)]
            elif len(b) == 1:
                facce += [(a[k], b[0], a[(k + 1) % segmenti]) for k in range(segmenti)]
            else:
                facce += [(a[k], a[(k + 1) % segmenti], b[(k + 1) % segmenti], b[k]) for k in range(segmenti)]
        if chiudi:
            if len(anelli[0]) > 1:
                facce.append(tuple(reversed(anelli[0])))
            if len(anelli[-1]) > 1:
                facce.append(tuple(anelli[-1]))
        m = Matrix.Translation(centro)
        if matrice is not None:
            m = matrice @ m
        self.parte(vs, facce, mat, liscio, m)

    def estruso(self, profilo, larghezza: float, mat, x0: float = 0.0, liscio: bool = False,
                matrice: Matrix | None = None) -> None:
        """Poligono laterale [(y, z), ...] estruso lungo X per ``larghezza``."""
        n = len(profilo)
        hw = larghezza / 2
        vs = [(x0 - hw, y, z) for y, z in profilo] + [(x0 + hw, y, z) for y, z in profilo]
        facce = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
        facce += [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)]
        self.parte(vs, facce, mat, liscio, matrice)

    def asta(self, p, q, spessore: float, mat) -> None:
        """Asta a sezione quadrata tra i punti ``p`` e ``q`` (traliccio, cornici)."""
        p, q = Vector(p), Vector(q)
        d = q - p
        if d.length < 1e-9:
            return
        d.normalize()
        u = d.cross(Vector((0, 0, 1)))
        if u.length < 1e-6:
            u = d.cross(Vector((1, 0, 0)))
        u.normalize()
        w = d.cross(u)
        h = spessore / 2
        vs = []
        for c in (p, q):
            for su, sw in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                vs.append(tuple(c + u * su * h + w * sw * h))
        facce = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        self.parte(vs, facce, mat)

    def sfera(self, centro, raggio, mat, segmenti: int = 24, scala=(1.0, 1.0, 1.0), matrice=None,
              anelli: int | None = None) -> None:
        anelli = max(4, anelli or segmenti // 2)
        prof = [(raggio * math.sin(math.pi * i / anelli), -raggio * math.cos(math.pi * i / anelli) * scala[2])
                for i in range(anelli + 1)]
        self.tornio(prof, mat, segmenti, centro, (scala[0], scala[1]), True, matrice)

    def cilindro(self, centro, raggio, altezza, mat, segmenti: int = 24, raggio2=None, liscio=True,
                 matrice=None) -> None:
        r2 = raggio if raggio2 is None else raggio2
        prof = [(0.0, -altezza / 2), (raggio, -altezza / 2), (r2, altezza / 2), (0.0, altezza / 2)]
        self.tornio(prof, mat, segmenti, centro, (1.0, 1.0), liscio, matrice, chiudi=False)

    def oggetto(self, kit: "Kit", nome: str, genitore=None):
        me = bpy.data.meshes.new(nome)
        me.from_pydata(self.v, [], self.f)
        me.validate(clean_customdata=False)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(me)
        bm.free()
        me.polygons.foreach_set("material_index", self.mi)
        me.polygons.foreach_set("use_smooth", self.sm)
        for m in self.mats:
            me.materials.append(kit.materiale(m))
        me.update()
        ob = bpy.data.objects.new(nome, me)
        kit.collega(ob, genitore)
        return ob


def profilo_capsula(raggio: float, lunghezza: float, passi: int = 6, dal_basso: bool = True):
    """Profilo (r, z) di una capsula lunga ``lunghezza`` (estremi inclusi)."""
    r = min(raggio, lunghezza / 2)
    corpo = lunghezza - 2 * r
    out = []
    for i in range(passi + 1):
        a = -math.pi / 2 + (math.pi / 2) * i / passi
        out.append((r * math.cos(a), r + r * math.sin(a)))
    for i in range(passi + 1):
        a = (math.pi / 2) * i / passi
        out.append((r * math.cos(a), r + corpo + r * math.sin(a)))
    if not dal_basso:
        out = [(x, z - lunghezza / 2) for x, z in out]
    return out


# ---------------------------------------------------------------------------
# Kit
# ---------------------------------------------------------------------------


STILI_AUTO: dict[str, dict[str, Any]] = {
    # y in frazioni di meta' lunghezza (-1 = muso), z in metri
    "coupe_80s": {"L": 4.2, "W": 1.63, "wr": 0.30, "wb": 2.40,
                  "body": [(-1, 0.30), (-1, 0.56), (-0.93, 0.70), (-0.33, 0.80), (0.82, 0.86), (1, 0.83), (1, 0.32)],
                  "cabin": [(-0.36, 0.78), (0.0, 1.26), (0.42, 1.29), (0.95, 0.88), (0.95, 0.80), (-0.36, 0.76)],
                  "head": (-0.98, 0.60), "tail": 0.70},
    "hatchback": {"L": 3.9, "W": 1.68, "wr": 0.30, "wb": 2.45,
                  "body": [(-1, 0.32), (-1, 0.66), (-0.9, 0.78), (-0.45, 0.86), (1, 0.92), (1, 0.34)],
                  "cabin": [(-0.47, 0.84), (-0.05, 1.42), (0.93, 1.42), (1.0, 0.92), (-0.47, 0.82)],
                  "head": (-1.0, 0.68), "tail": 0.84},
    "sedan": {"L": 4.7, "W": 1.8, "wr": 0.32, "wb": 2.75,
              "body": [(-1, 0.34), (-1, 0.66), (-0.92, 0.76), (-0.40, 0.86), (0.62, 0.90), (0.70, 0.98), (1, 0.98), (1, 0.36)],
              "cabin": [(-0.42, 0.84), (-0.08, 1.42), (0.40, 1.42), (0.68, 0.96), (-0.42, 0.82)],
              "head": (-1.0, 0.66), "tail": 0.86},
    "sports": {"L": 4.4, "W": 1.9, "wr": 0.33, "wb": 2.6,
               "body": [(-1, 0.28), (-1, 0.50), (-0.88, 0.60), (-0.15, 0.76), (0.75, 0.84), (1, 0.82), (1, 0.30)],
               "cabin": [(-0.18, 0.74), (0.12, 1.13), (0.42, 1.15), (0.95, 0.84), (-0.18, 0.72)],
               "head": (-0.96, 0.54), "tail": 0.70},
    "suv": {"L": 4.7, "W": 1.92, "wr": 0.38, "wb": 2.8,
            "body": [(-1, 0.42), (-1, 0.90), (-0.88, 1.02), (-0.5, 1.08), (1, 1.12), (1, 0.42)],
            "cabin": [(-0.52, 1.06), (-0.25, 1.72), (0.95, 1.74), (1, 1.10), (-0.52, 1.04)],
            "head": (-1.0, 0.88), "tail": 1.0},
    "van": {"L": 4.9, "W": 1.95, "wr": 0.33, "wb": 3.0,
            "body": [(-1, 0.38), (-1, 0.95), (-0.85, 1.05), (1, 1.05), (1, 0.38)],
            "cabin": [(-0.86, 1.03), (-0.62, 1.92), (1, 1.95), (1, 1.03)],
            "head": (-1.0, 0.82), "tail": 0.95},
}


class Kit:
    """Costruisce una scena Blender a partire da una spec normalizzata."""

    def __init__(self, spec: dict):
        self.spec = spec
        self.meta = spec["meta"]
        self.frames = int(self.meta["frames"])
        self.fps = S.FPS
        self.scene = bpy.context.scene
        self.radici: dict[str, Any] = {}       # nome spec -> oggetto radice
        self.giunti: dict[str, dict] = {}      # nome manichino -> {giunto: empty}
        self.ruote: dict[str, list] = {}       # nome auto -> [(oggetto ruota, raggio)]
        self.campioni: dict[str, list] = {}    # nome -> trasformazioni per frame
        self._materiali: dict[str, Any] = {}
        self._posizioni: dict[str, list] = {}
        self.camera = None
        self._oggetti: list[dict] = []
        self._luci_mirate: list[tuple] = []          # luci con look_at su un oggetto
        self._scala_manichini: dict[str, float] = {}

    # -- infrastruttura -----------------------------------------------------

    def collega(self, ob, genitore=None):
        self.scene.collection.objects.link(ob)
        if genitore is not None:
            ob.parent = genitore
        return ob

    def vuoto(self, nome: str, genitore=None, loc=(0.0, 0.0, 0.0), dim: float = 0.2):
        ob = bpy.data.objects.new(nome, None)
        ob.empty_display_type = "PLAIN_AXES"
        ob.empty_display_size = dim
        ob.location = loc
        return self.collega(ob, genitore)

    def materiale(self, desc) -> Any:
        """Materiale Blender (con cache) da una descrizione della spec."""
        m = S.risolvi_materiale(desc)  # idempotente sui materiali gia' risolti
        chiave = json.dumps(m, sort_keys=True, default=str)
        if chiave in self._materiali:
            return self._materiali[chiave]
        nome = m.get("preset") or ("emissivo" if m.get("emissive_only") else "mat")
        mat = bpy.data.materials.new(f"{nome}_{len(self._materiali):02d}")
        nt = _nodi(mat)
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        if m.get("emissive_only"):
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs["Color"].default_value = colore(m["emission"])
            em.inputs["Strength"].default_value = float(m["emission_strength"])
            nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
        else:
            p = nt.nodes.new("ShaderNodeBsdfPrincipled")
            p.inputs["Base Color"].default_value = colore(m["color"])
            p.inputs["Roughness"].default_value = float(m["roughness"])
            p.inputs["Metallic"].default_value = float(m["metallic"])
            p.inputs["Specular IOR Level"].default_value = float(m["specular"])
            p.inputs["IOR"].default_value = float(m.get("ior", 1.5))
            p.inputs["Coat Weight"].default_value = float(m["coat"])
            p.inputs["Transmission Weight"].default_value = float(m["transmission"])
            if m.get("alpha", 1.0) < 1.0:
                p.inputs["Alpha"].default_value = float(m["alpha"])
            if m.get("emission"):
                p.inputs["Emission Color"].default_value = colore(m["emission"])
                p.inputs["Emission Strength"].default_value = float(m.get("emission_strength", 1.0))
            if m.get("wet"):
                # pozzanghere: rugosita' variabile da un rumore a grande scala
                tc = nt.nodes.new("ShaderNodeTexCoord")
                no = nt.nodes.new("ShaderNodeTexNoise")
                no.inputs["Scale"].default_value = 0.35
                no.inputs["Detail"].default_value = 3.0
                mr = nt.nodes.new("ShaderNodeMapRange")
                mr.inputs["From Min"].default_value = 0.42
                mr.inputs["From Max"].default_value = 0.62
                mr.inputs["To Min"].default_value = float(m["roughness"])
                mr.inputs["To Max"].default_value = float(m.get("rough_max", 0.32))
                nt.links.new(tc.outputs["Object"], no.inputs["Vector"])
                nt.links.new(no.outputs["Fac"], mr.inputs["Value"])
                nt.links.new(mr.outputs["Result"], p.inputs["Roughness"])
            nt.links.new(p.outputs["BSDF"], out.inputs["Surface"])
        self._materiali[chiave] = mat
        return mat

    @staticmethod
    def mat_colore(materiale, col) -> dict:
        """Materiale della spec con il colore sostituito (se non emissivo)."""
        m = S.risolvi_materiale(materiale)
        if col is not None and not m.get("emissive_only"):
            m["color"] = col
        return m

    @staticmethod
    def emissivo(col, forza: float) -> dict:
        return S.risolvi_materiale(f"emissive:{col if isinstance(col, str) else '#FFFFFF'}:{forza}")

    def discendenti(self, ob) -> list:
        out = [ob]
        for c in ob.children:
            out += self.discendenti(c)
        return out

    # -- render, mondo, compositor --------------------------------------------

    def imposta_render(self) -> None:
        sc, r, cfg = self.scene, self.scene.render, self.spec["render"]
        r.engine = "CYCLES"
        c = sc.cycles
        c.device = "CPU"
        c.samples = int(cfg["samples"])
        c.use_adaptive_sampling = True
        c.adaptive_threshold = float(cfg["adaptive_threshold"])
        c.adaptive_min_samples = 0
        c.use_denoising = bool(cfg["denoise"])
        if cfg["denoise"]:
            # OIDN con prefiltro veloce: su superfici lisce da blockout la differenza non si vede
            c.denoiser = "OPENIMAGEDENOISE"
            c.denoising_input_passes = "RGB_ALBEDO_NORMAL"
            c.denoising_prefilter = "FAST"
            c.denoising_quality = "BALANCED"
        b = cfg["bounces"]
        c.max_bounces = int(b["max"])
        c.diffuse_bounces = int(b["diffuse"])
        c.glossy_bounces = int(b["glossy"])
        c.transmission_bounces = int(b["transmission"])
        c.transparent_max_bounces = int(b["transparent"])
        c.volume_bounces = int(b["volume"])
        c.caustics_reflective = False
        c.caustics_refractive = False
        c.blur_glossy = 1.0
        c.sample_clamp_direct = 0.0
        c.sample_clamp_indirect = float(cfg["clamp_indirect"])
        c.use_light_tree = bool(cfg.get("light_tree", False))  # spento: ~30% piu' veloce con poche luci
        c.seed = int(self.meta.get("seed", 0))
        r.use_persistent_data = bool(cfg["persistent_data"])
        r.resolution_x, r.resolution_y = (int(x) for x in self.meta["resolution"])
        r.resolution_percentage = 100
        r.fps, r.fps_base = self.fps, 1.0
        r.use_motion_blur = bool(cfg["motion_blur"])
        r.motion_blur_shutter = float(cfg["shutter"])
        r.film_transparent = bool(cfg["film_transparent"])
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA" if cfg["film_transparent"] else "RGB"
        r.image_settings.color_depth = "8"
        r.use_compositing = True
        sc.frame_start, sc.frame_end = 0, self.frames - 1
        vs = sc.view_settings
        vs.view_transform = cfg["view_transform"]
        look = cfg["look"]
        for cand in (f"{cfg['view_transform']} - {look}", look, "None"):
            try:
                vs.look = cand
                break
            except TypeError:
                continue
        vs.exposure = float(cfg["exposure"])
        vs.gamma = float(cfg["gamma"])

    def imposta_mondo(self) -> None:
        w = self.spec["world"]
        mondo = bpy.data.worlds.new("Mondo")
        self.scene.world = mondo
        nt = _nodi(mondo)
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputWorld")
        luce = nt.nodes.new("ShaderNodeBackground")
        luce.inputs["Color"].default_value = colore(w["color"])
        luce.inputs["Strength"].default_value = float(w["strength"])
        if w.get("background"):
            # sfondo visto dalla camera diverso dalla luce ambiente
            vis = nt.nodes.new("ShaderNodeBackground")
            vis.inputs["Color"].default_value = colore(w["background"])
            vis.inputs["Strength"].default_value = float(w.get("background_strength", 1.0))
            lp = nt.nodes.new("ShaderNodeLightPath")
            mix = nt.nodes.new("ShaderNodeMixShader")
            nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
            nt.links.new(luce.outputs["Background"], mix.inputs[1])
            nt.links.new(vis.outputs["Background"], mix.inputs[2])
            nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
        else:
            nt.links.new(luce.outputs["Background"], out.inputs["Surface"])
        vol = w.get("volumetric")
        if vol:
            sv = nt.nodes.new("ShaderNodeVolumePrincipled")
            sv.inputs["Color"].default_value = colore(vol.get("color", "#FFFFFF"))
            sv.inputs["Density"].default_value = float(vol.get("density", 0.02))
            sv.inputs["Anisotropy"].default_value = float(vol.get("anisotropy", 0.3))
            nt.links.new(sv.outputs["Volume"], out.inputs["Volume"])
            if self.spec["render"]["bounces"]["volume"] == 0:
                self.scene.cycles.volume_bounces = 1
        if w.get("fog"):
            fog = w["fog"]
            ms = mondo.mist_settings
            ms.start = float(fog.get("start", 5.0))
            ms.depth = float(fog.get("depth", 40.0))
            ms.falloff = "QUADRATIC"
            self.scene.view_layers[0].use_pass_mist = True
        for i, l in enumerate(w["lights"]):
            self.luce(dict(l, name=l.get("name", f"luce_{i:02d}")), None)

    def imposta_compositor(self) -> None:
        cfg = self.spec["render"]
        fog = self.spec["world"].get("fog")
        ng = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = ng
        ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = ng.nodes.new("CompositorNodeRLayers")
        uscita = rl.outputs["Image"]
        if fog:
            mix = ng.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MIX"
            mul = ng.nodes.new("ShaderNodeMath")
            mul.operation = "MULTIPLY"
            mul.inputs[1].default_value = float(fog.get("amount", 0.6))
            ng.links.new(rl.outputs["Mist"], mul.inputs[0])
            ng.links.new(mul.outputs[0], mix.inputs["Factor"])
            ng.links.new(uscita, mix.inputs[6])
            mix.inputs[7].default_value = colore(fog.get("color", "#1A1F2A"))
            uscita = mix.outputs[2]
        g = cfg.get("glare")
        if g:
            gl = ng.nodes.new("CompositorNodeGlare")
            gl.inputs["Type"].default_value = g.get("type", "Bloom")
            gl.inputs["Quality"].default_value = "Medium"
            gl.inputs["Threshold"].default_value = float(g.get("threshold", 0.9))
            gl.inputs["Strength"].default_value = float(g.get("strength", 0.4))
            gl.inputs["Size"].default_value = float(g.get("size", 0.6))
            ng.links.new(uscita, gl.inputs["Image"])
            uscita = gl.outputs["Image"]
        vig = float(cfg.get("vignette", 0.0))
        if vig > 0:
            r = self.scene.render
            el = ng.nodes.new("CompositorNodeEllipseMask")
            el.inputs["Size"].default_value = (1.05, 1.05)
            bl = ng.nodes.new("CompositorNodeBlur")
            raggio = 0.28 * max(r.resolution_x, r.resolution_y)
            bl.inputs["Size"].default_value = (raggio, raggio)
            try:
                bl.inputs["Type"].default_value = "Fast Gaussian"
            except TypeError:  # pragma: no cover
                pass
            ng.links.new(el.outputs["Mask"], bl.inputs["Image"])
            # fattore = 1 - vig * (1 - maschera)
            inv = ng.nodes.new("ShaderNodeMapRange")
            inv.inputs["To Min"].default_value = 1.0 - vig
            inv.inputs["To Max"].default_value = 1.0
            ng.links.new(bl.outputs["Image"], inv.inputs["Value"])
            mix = ng.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            ng.links.new(uscita, mix.inputs[6])
            ng.links.new(inv.outputs["Result"], mix.inputs[7])  # float -> grigio
            uscita = mix.outputs[2]
        go = ng.nodes.new("NodeGroupOutput")
        ng.links.new(uscita, go.inputs[0])

    # -- oggetti --------------------------------------------------------------

    def espandi_ripetizioni(self, oggetti: list[dict]) -> list[dict]:
        out = []
        for o in oggetti:
            out.append(o)
            rep = o.get("repeat")
            if not rep:
                continue
            off = vec3(rep.get("offset", (0, 0, 0)))
            drot = vec3(rep.get("rotation", (0, 0, 0)))
            for k in range(1, int(rep["count"])):
                c = json.loads(json.dumps(o))
                c["repeat"] = None
                c["name"] = f"{o['name']}_{k}"
                c["location"] = [o["location"][i] + off[i] * k for i in range(3)]
                c["rotation"] = [o["rotation"][i] + drot[i] * k for i in range(3)]
                for key in c.get("keys", []):
                    if "location" in key:
                        key["location"] = [key["location"][i] + off[i] * k for i in range(3)]
                if c.get("path"):
                    c["path"]["points"] = [[p[i] + off[i] * k for i in range(3)] for p in c["path"]["points"]]
                out.append(c)
        return out

    def costruisci_oggetti(self) -> None:
        oggetti = self.espandi_ripetizioni(self.spec["objects"])
        self._oggetti = oggetti
        for o in oggetti:
            costruttore = getattr(self, "p_" + o["type"])
            root = self.radice(o) if o["type"] != "light" else None
            res = costruttore(o, root)
            if root is None:
                root = res
            self.radici[o["name"]] = root
            if o["type"] != "light":  # le luci hanno gia' posizione e mira (look_at)
                root.location = vec3(o["location"])
                root.rotation_euler = rad(o["rotation"])
                root.scale = vec3(o["scale"])
            if not o.get("shadow", True):
                for ob in self.discendenti(root):
                    ob.visible_shadow = False
        for o in oggetti:
            if o.get("parent"):
                self.radici[o["name"]].parent = self.radici[o["parent"]]

    def radice(self, o: dict):
        return self.vuoto(o["name"], None, dim=0.5)

    # primitive -----------------------------------------------------------

    def _mat_primitiva(self, o):
        return self.mat_colore(o.get("material", "clay"), o.get("color"))

    def _semplice(self, o, root, mesh: Mesh, bevel: float = 0.0):
        ob = mesh.oggetto(self, o["name"] + ".mesh", root)
        if bevel > 0:
            md = ob.modifiers.new("Bevel", "BEVEL")
            md.width = bevel
            md.segments = 2
            md.limit_method = "ANGLE"
        return ob

    def p_box(self, o, root):
        m = Mesh()
        sx, sy, sz = o["size"]
        z = sz / 2 if o["origin"] == "bottom" else 0.0
        m.box((0, 0, z), (sx, sy, sz), self._mat_primitiva(o))
        return self._semplice(o, root, m, o.get("bevel", 0.0))

    def p_cylinder(self, o, root):
        m = Mesh()
        z = o["depth"] / 2 if o["origin"] == "bottom" else 0.0
        m.cilindro((0, 0, z), o["radius"], o["depth"], self._mat_primitiva(o), o["vertices"], liscio=o["smooth"])
        return self._semplice(o, root, m)

    def p_cone(self, o, root):
        m = Mesh()
        z = o["depth"] / 2 if o["origin"] == "bottom" else 0.0
        m.cilindro((0, 0, z), o["radius1"], o["depth"], self._mat_primitiva(o), o["vertices"],
                   raggio2=o["radius2"], liscio=o["smooth"])
        return self._semplice(o, root, m)

    def p_sphere(self, o, root):
        m = Mesh()
        m.sfera((0, 0, 0), o["radius"], self._mat_primitiva(o), o["segments"], anelli=o["rings"])
        return self._semplice(o, root, m)

    def p_plane(self, o, root):
        m = Mesh()
        hx, hy = o["size"][0] / 2, o["size"][1] / 2
        m.parte([(-hx, -hy, 0), (hx, -hy, 0), (hx, hy, 0), (-hx, hy, 0)], [(0, 1, 2, 3)], self._mat_primitiva(o))
        return self._semplice(o, root, m)

    def p_torus(self, o, root):
        m = Mesh()
        R, r, n = o["major"], o["minor"], o["segments"]
        k = max(8, n // 3)
        vs, fs = [], []
        for i in range(n):
            a = 2 * math.pi * i / n
            for j in range(k):
                b = 2 * math.pi * j / k
                vs.append(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
        for i in range(n):
            for j in range(k):
                a0, a1 = i * k, ((i + 1) % n) * k
                fs.append((a0 + j, a1 + j, a1 + (j + 1) % k, a0 + (j + 1) % k))
        m.parte(vs, fs, self._mat_primitiva(o), True)
        return self._semplice(o, root, m)

    def p_capsule(self, o, root):
        m = Mesh()
        m.tornio(profilo_capsula(o["radius"], o["length"], dal_basso=o["origin"] == "bottom"),
                 self._mat_primitiva(o), 24)
        return self._semplice(o, root, m)

    def p_lathe(self, o, root):
        m = Mesh()
        m.tornio([tuple(p) for p in o["profile"]], self._mat_primitiva(o), o["segments"], liscio=o["smooth"])
        return self._semplice(o, root, m)

    def p_extrude(self, o, root):
        m = Mesh()
        m.estruso([tuple(p) for p in o["profile"]], o["width"], self._mat_primitiva(o), liscio=o["smooth"])
        return self._semplice(o, root, m, o.get("bevel", 0.0))

    def p_empty(self, o, root):
        return root

    def luce(self, l: dict, genitore):
        tipo = l.get("light_type", "area").upper()
        dati = bpy.data.lights.new(l["name"], tipo)
        dati.color = colore(l.get("color", "#FFFFFF"))[:3]
        dati.energy = float(l.get("energy", 300.0))
        dati.use_shadow = bool(l.get("cast_shadow", True))
        size = float(l.get("size", 1.0))
        if tipo == "AREA":
            if l.get("size_y"):
                dati.shape = "RECTANGLE"
                dati.size, dati.size_y = size, float(l["size_y"])
            else:
                dati.shape = "SQUARE"
                dati.size = size
        elif tipo in ("POINT", "SPOT"):
            dati.shadow_soft_size = size if "size" in l else 0.1
            if tipo == "SPOT":
                dati.spot_size = math.radians(float(l.get("spot_size", 45.0)))
                dati.spot_blend = float(l.get("spot_blend", 0.3))
        elif tipo == "SUN":
            dati.angle = math.radians(float(l.get("angle", 1.0)))
        ob = bpy.data.objects.new(l["name"], dati)
        self.collega(ob, genitore)
        ob.location = vec3(l.get("location", (0, 0, 3)))
        if l.get("look_at") is not None and not isinstance(l["look_at"], (str, dict)):
            ob.rotation_euler = moto.look_at_euler(ob.location, l["look_at"])
        else:
            ob.rotation_euler = rad(l.get("rotation", (0, 0, 0)))
        ob.visible_camera = bool(l.get("camera_visible", False))
        if isinstance(l.get("look_at"), (str, dict)):
            self._luci_mirate.append((ob, l["look_at"]))
        return ob

    def p_light(self, o, root):
        return self.luce(o, None)

    # prefab: manichino -------------------------------------------------------

    def p_mannequin(self, o, root):
        s = o["height"] / 1.65
        corpo = self.mat_colore(o.get("material", "mannequin"), o["color"])
        acc = self.mat_colore("accent_dark", o["accent"])
        nero = self.mat_colore("glossy_black", o["accent"])
        acc_set = set(o["accessories"])
        nome = o["name"]
        posa0 = moto.posa(o["pose"], o.get("joints"))
        seduto = posa0["pelvis_drop"] > 0.2
        lungo = o["dress"] == "long"

        def S_(v):  # scala le misure del manichino di riferimento (1.65 m)
            return tuple(x * s for x in v)

        G: dict[str, Any] = {}
        G["root"] = root
        G["pelvis"] = self.vuoto(f"{nome}.pelvis", root, S_((0, 0, 0.92)))
        G["spine"] = self.vuoto(f"{nome}.spine", G["pelvis"], S_((0, 0, 0.06)))
        G["neck"] = self.vuoto(f"{nome}.neck", G["spine"], S_((0, 0, 0.385)))
        G["head"] = self.vuoto(f"{nome}.head", G["neck"], S_((0, 0, 0.075)))
        for lato, sx in (("l", 1), ("r", -1)):
            G[f"shoulder_{lato}"] = self.vuoto(f"{nome}.shoulder_{lato}", G["spine"], S_((0.19 * sx, 0, 0.355)))
            G[f"elbow_{lato}"] = self.vuoto(f"{nome}.elbow_{lato}", G[f"shoulder_{lato}"], S_((0, 0, -0.29)))
            G[f"wrist_{lato}"] = self.vuoto(f"{nome}.wrist_{lato}", G[f"elbow_{lato}"], S_((0, 0, -0.26)))
            G[f"hip_{lato}"] = self.vuoto(f"{nome}.hip_{lato}", G["pelvis"], S_((0.09 * sx, 0, 0)))
            G[f"knee_{lato}"] = self.vuoto(f"{nome}.knee_{lato}", G[f"hip_{lato}"], S_((0, 0, -0.44)))
            G[f"ankle_{lato}"] = self.vuoto(f"{nome}.ankle_{lato}", G[f"knee_{lato}"], S_((0, 0, -0.42)))
        self.giunti[nome] = G

        def pezzo(giunto: str, costruisci, mat=corpo):
            m = Mesh()
            costruisci(m, mat)
            ob = m.oggetto(self, f"{nome}.{giunto}.geo{len(G[giunto].children)}", G[giunto])
            return ob

        sc = Matrix.Diagonal((s, s, s, 1.0))
        # testa a uovo (mento piu' stretto)
        testa = [(0, 0), (0.033, 0.007), (0.062, 0.033), (0.082, 0.077), (0.092, 0.124), (0.092, 0.166),
                 (0.082, 0.203), (0.06, 0.226), (0.031, 0.237), (0, 0.24)]
        pezzo("head", lambda m, mt: m.tornio(testa, mt, 28, (0, 0, -0.012), (1.0, 1.08), matrice=sc))
        pezzo("neck", lambda m, mt: m.cilindro((0, 0, 0.02), 0.034, 0.12, mt, 20, matrice=sc))
        # busto: spalle ampie e arrotondate, sezione ellittica
        busto = [(0.0, -0.07), (0.128, -0.07), (0.127, 0.0), (0.136, 0.12), (0.163, 0.25), (0.188, 0.32),
                 (0.193, 0.36), (0.18, 0.395), (0.14, 0.418), (0.07, 0.43), (0.0, 0.433)]
        pezzo("spine", lambda m, mt: m.tornio(busto, mt, 32, scala=(1.12, 0.6), matrice=sc))
        if lungo and not seduto:
            # kimono / abito lungo: colonna fino a terra con base arrotondata
            abito = [(0.0, 0.08), (0.135, 0.08), (0.163, -0.06), (0.158, -0.35), (0.152, -0.62),
                     (0.158, -0.80), (0.162, -0.87), (0.14, -0.905), (0.09, -0.918), (0.0, -0.92)]
            pezzo("pelvis", lambda m, mt: m.tornio(abito, mt, 32, scala=(1.0, 0.8), matrice=sc))
        else:
            bacino = [(0.0, -0.1), (0.1, -0.1), (0.15, -0.04), (0.155, 0.04), (0.13, 0.09), (0.0, 0.1)]
            pezzo("pelvis", lambda m, mt: m.tornio(bacino, mt, 28, scala=(1.0, 0.72), matrice=sc))
        for lato in ("l", "r"):
            pezzo(f"shoulder_{lato}", lambda m, mt: m.tornio(
                [(x, z - 0.29 - 0.02) for x, z in profilo_capsula(0.043, 0.33)], mt, 18, matrice=sc))
            pezzo(f"elbow_{lato}", lambda m, mt: m.tornio(
                [(x, z - 0.27) for x, z in profilo_capsula(0.037, 0.29)], mt, 18, matrice=sc))
            pezzo(f"wrist_{lato}", lambda m, mt: m.tornio(
                [(x, z - 0.13) for x, z in profilo_capsula(0.03, 0.14)], mt, 14, scala=(0.75, 1.0), matrice=sc))
            if lungo and seduto:
                rg = (0.095, 0.085)  # gambe "nell'abito": piu' piene
            elif lungo:
                rg = None
            else:
                rg = (0.068, 0.052)
            if rg:
                pezzo(f"hip_{lato}", lambda m, mt, r=rg[0]: m.tornio(
                    [(x, z - 0.44 - r * 0.6) for x, z in profilo_capsula(r, 0.44 + r * 1.2)], mt, 20, matrice=sc))
                pezzo(f"knee_{lato}", lambda m, mt, r=rg[1]: m.tornio(
                    [(x, z - 0.42 - r * 0.5) for x, z in profilo_capsula(r, 0.42 + r)], mt, 18, matrice=sc))
                pezzo(f"ankle_{lato}", lambda m, mt: m.box((0, -0.06, -0.03), (0.085, 0.22, 0.06), mt, matrice=sc))

        if "obi" in acc_set:
            obi = [(0.0, -0.03), (0.142, -0.03), (0.146, 0.0), (0.147, 0.15), (0.143, 0.175), (0.0, 0.175)]
            pezzo("spine", lambda m, mt: m.tornio(obi, mt, 32, scala=(1.0, 0.68), matrice=sc), acc)
        if "hair_bun" in acc_set:
            def chignon(m, mt):
                m.sfera((0, 0.015, 0.235), 0.062, mt, 20, matrice=sc)
                m.sfera((0.055, 0.02, 0.205), 0.042, mt, 16, matrice=sc)
                m.sfera((-0.055, 0.02, 0.205), 0.042, mt, 16, matrice=sc)
                m.sfera((0, 0.07, 0.17), 0.05, mt, 16, matrice=sc)
                # calotta di capelli: copre sommita' e nuca, lascia libero il viso
                m.sfera((0, 0.014, 0.142), 0.097, mt, 24, scala=(1.0, 1.0, 0.86), matrice=sc)
            pezzo("head", chignon, nero)
        if "kanzashi" in acc_set:
            def bastoncini(m, mt):
                for sx in (1, -1):
                    m.asta(S_((0.0, 0.02, 0.22)), S_((0.16 * sx, 0.03, 0.31)), 0.008 * s, mt)
            pezzo("head", bastoncini, self.mat_colore("clay", "#F4F1EA"))
        if "flower" in acc_set:
            pezzo("head", lambda m, mt: m.sfera((0.075, 0.03, 0.2), 0.034, mt, 14, matrice=sc),
                  self.mat_colore("clay", "#F7F5F0"))
        if "sunglasses" in acc_set:
            pezzo("head", lambda m, mt: m.box((0, -0.082, 0.118), (0.17, 0.035, 0.048), mt, matrice=sc), nero)
        if "hat" in acc_set:
            def cappello(m, mt):
                m.cilindro((0, 0, 0.2), 0.17, 0.012, mt, 32, liscio=False, matrice=sc)
                m.cilindro((0, 0, 0.25), 0.095, 0.1, mt, 28, liscio=False, matrice=sc)
            pezzo("head", cappello, acc)
        if "umbrella" in acc_set:
            ombrello = self.mat_colore("glossy_black", o["umbrella_color"])

            def ombr(m, mt):
                m.cilindro((0, -0.16, 0.45), 0.008, 1.25, mt, 8, matrice=sc)
                m.tornio([(0, 1.30), (0.58, 1.02), (0.54, 1.015), (0, 1.25)], mt, 36, (0, -0.16, 0), liscio=False,
                         matrice=sc)
                m.cilindro((0, -0.16, 1.33), 0.012, 0.08, mt, 8, matrice=sc)
            pezzo("spine", ombr, ombrello)
        if "bag" in acc_set:
            pezzo("wrist_r", lambda m, mt: m.box((0, 0, -0.2), (0.24, 0.08, 0.18), mt, matrice=sc), acc)
        self.applica_posa(nome, {"joints": posa0["joints"], "pelvis_drop": posa0["pelvis_drop"], "bob": 0.0}, s)
        self._scala_manichini[nome] = s
        return root

    def applica_posa(self, nome: str, p: dict, s: float, frame: int | None = None) -> None:
        G = self.giunti[nome]
        for g in moto.GIUNTI:
            if g == "root":
                continue
            ang = p["joints"].get(g, (0.0, 0.0, 0.0))
            G[g].rotation_euler = rad(ang)
            if frame is not None:
                G[g].keyframe_insert("rotation_euler", frame=frame)
        G["pelvis"].location = (0.0, 0.0, (0.92 - p["pelvis_drop"] + p.get("bob", 0.0)) * s)
        if frame is not None:
            G["pelvis"].keyframe_insert("location", frame=frame)

    # prefab: auto ---------------------------------------------------------------

    def p_car(self, o, root):
        st = STILI_AUTO[o["style"]]
        L, W, wr, wb = st["L"], st["W"], st["wr"], st["wb"]
        h = L / 2
        corpo = self.mat_colore("car_paint", o["color"])
        basso = self.mat_colore("glossy_black", o["lower_color"])
        vetro = S.risolvi_materiale("glass")
        gomma = S.risolvi_materiale("rubber")
        acceso = o["lights_on"]
        fari = self.emissivo("#FFFFFF", o["headlight_strength"] if acceso else 0.0) if acceso else \
            self.mat_colore("clay", "#DADADA")
        fendi = self.emissivo("#FFF0D2", 6.0) if acceso else self.mat_colore("clay", "#E6DCC8")
        posteriori = self.emissivo(o["taillight_color"], 5.0) if o["taillights_on"] else \
            self.mat_colore("glossy_black", "#5A1C24")
        m = Mesh()
        body = [(y * h, z) for y, z in st["body"]]
        m.estruso(body, W, corpo)
        cab = [(y * h, z) for y, z in st["cabin"]]
        m.estruso(cab, W - 0.16, vetro)
        # tetto e montanti: sottile lastra del colore carrozzeria sopra l'abitacolo
        tetto = sorted(cab, key=lambda p: -p[1])[:2]
        y0, y1 = sorted(p[0] for p in tetto)
        ztop = max(p[1] for p in tetto)
        m.box(((0, (y0 + y1) / 2, ztop + 0.015)), (W - 0.2, (y1 - y0) + 0.06, 0.04), corpo)
        # sottoporta nero tra le ruote e paraurti: le ruote restano visibili sotto la carrozzeria
        zb = min(z for _, z in st["body"])
        sotto = wb - 2 * wr - 0.12
        m.box((0, 0, (zb + 0.2) / 2), (W - 0.06, sotto, zb + 0.02 - 0.2), basso)
        m.box((0, -h - 0.03, zb + 0.06), (W + 0.02, 0.16, 0.2), basso)
        m.box((0, h + 0.03, zb + 0.06), (W + 0.02, 0.16, 0.2), basso)
        if o["stripe"]:
            zs = zb + 0.3
            m.box((W / 2 + 0.005, 0.05, zs), (0.01, L * 0.8, 0.03), basso)
            m.box((-W / 2 - 0.005, 0.05, zs), (0.01, L * 0.8, 0.03), basso)
        hy, hz = st["head"][0] * h, st["head"][1]
        if o["popup_headlights"]:
            # fari a scomparsa sollevati: blocchetti inclinati con la faccia emissiva
            for sx in (1, -1):
                cx = sx * (W / 2 - 0.34)
                mt = Matrix.Translation((cx, hy + 0.32, hz + 0.16)) @ Euler((math.radians(-14), 0, 0)).to_matrix().to_4x4()
                m.box((0, 0, 0), (0.42, 0.14, 0.22), corpo, matrice=mt)
                m.box((0, -0.075, 0.0), (0.36, 0.02, 0.17), fari, matrice=mt)
        else:
            for sx in (1, -1):
                m.box((sx * (W / 2 - 0.3), hy - 0.012, hz), (0.38, 0.03, 0.12), fari)
        # frontale nero tra paraurti e fari, con fendinebbia e targa
        top_fascia = hz - (0.04 if o["popup_headlights"] else 0.08)
        m.box((0, -h - 0.012, (zb + top_fascia) / 2), (W - 0.02, 0.03, top_fascia - zb), basso)
        for sx in (1, -1):
            m.box((sx * (W / 2 - 0.3), -h - 0.03, zb + 0.13), (0.26, 0.02, 0.07), fendi)
            m.box((sx * (W / 2 - 0.27), -h - 0.115, zb + 0.02), (0.22, 0.02, 0.05), fendi)
            m.box((sx * (W / 2 - 0.32), h + 0.012, st["tail"]), (0.5, 0.03, 0.11), posteriori)
        m.box((0, -h - 0.115, zb + 0.05), (0.32, 0.015, 0.14), self.mat_colore("clay", "#E9E7E2"))
        corpo_ob = m.oggetto(self, f"{o['name']}.body", root)
        # portiere aperte
        porte = {"left": [1], "right": [-1], "both": [1, -1]}.get(o["doors_open"], [])
        for sx in porte:
            pm = Mesh()
            yb = -0.62
            pm.box((0, 0.5, 0), (0.06, 1.0, 0.5), corpo)
            pm.box((0, 0.55, 0.42), (0.04, 0.8, 0.34), vetro)
            porta = pm.oggetto(self, f"{o['name']}.door_{'l' if sx > 0 else 'r'}", root)
            porta.location = (sx * (W / 2 + 0.02), yb, zb + 0.4)
            porta.rotation_euler = (0, 0, math.radians(-62 * sx))
        # ruote: oggetti separati per farle girare attorno a X
        self.ruote[o["name"]] = []
        rot = Matrix.Rotation(math.radians(90), 4, "Y")
        for sx in (1, -1):
            for sy in (1, -1):
                rm = Mesh()
                rm.cilindro((0, 0, 0), wr, 0.21, gomma, 24, matrice=rot)
                rm.cilindro((0.004 * sx, 0, 0), wr * 0.55, 0.214, self.mat_colore("metal", "#3C3E42"), 12,
                            liscio=False, matrice=rot)
                ruota = rm.oggetto(self, f"{o['name']}.wheel_{'f' if sy < 0 else 'b'}{'l' if sx > 0 else 'r'}", root)
                ruota.location = (sx * (W / 2 - 0.13), sy * wb / 2, wr)
                self.ruote[o["name"]].append((ruota, wr))
        if acceso and o["headlight_beams"]:
            for sx in (1, -1):
                self.luce({"name": f"{o['name']}.beam_{sx}", "light_type": "spot", "color": "#FFF3DE",
                           "energy": 260.0, "size": 0.08, "spot_size": 55.0, "spot_blend": 0.6,
                           "location": (sx * (W / 2 - 0.34), hy - 0.1, hz + 0.05),
                           "rotation": (82.0, 0.0, 180.0)}, root)
        return corpo_ob

    # prefab: citta' ------------------------------------------------------------

    def _pannelli_casuali(self, cfg: dict, w: float, d: float, hgt: float, rng: random.Random) -> list[dict]:
        out = []
        pal = cfg.get("palette") or list(S.PASTELLI.values())
        facce = cfg.get("faces") or ["front"]
        wr, hr = cfg.get("w", (1.2, 3.5)), cfg.get("h", (0.8, 2.2))
        zr = cfg.get("z", (2.0, max(2.5, hgt - 1.0)))
        occupati: list[tuple] = []
        for _ in range(int(cfg.get("count", 3))):
            for _tent in range(20):
                f = rng.choice(facce)
                larg = w if f in ("front", "back") else d
                pw = rng.uniform(*wr)
                ph = rng.uniform(*hr)
                if pw > larg - 0.4:
                    pw = larg - 0.4
                x = rng.uniform(-larg / 2 + pw / 2 + 0.2, larg / 2 - pw / 2 - 0.2)
                z = rng.uniform(min(zr[0], hgt - ph / 2), min(zr[1], hgt - ph / 2 - 0.1))
                box = (f, x - pw / 2 - 0.15, x + pw / 2 + 0.15, z - ph / 2 - 0.15, z + ph / 2 + 0.15)
                if any(b[0] == f and not (box[2] < b[1] or box[1] > b[2] or box[4] < b[3] or box[3] > b[4])
                       for b in occupati):
                    continue
                occupati.append(box)
                out.append({"face": f, "x": x, "z": z, "w": pw, "h": ph, "color": rng.choice(pal),
                            "strength": cfg.get("strength", 1.1)})
                break
        return out

    @staticmethod
    def _su_faccia(f: str, w: float, d: float, x: float, z: float, prof: float):
        """Centro e rotazione di un elemento appoggiato su una faccia del blocco."""
        if f == "front":
            return (x, -d / 2 - prof / 2, z), (0, 0, 0)
        if f == "back":
            return (-x, d / 2 + prof / 2, z), (0, 0, 180)
        if f == "left":
            return (-w / 2 - prof / 2, -x, z), (0, 0, -90)
        return (w / 2 + prof / 2, x, z), (0, 0, 90)

    def p_building_block(self, o, root, rng: random.Random | None = None):
        w, d, hgt = o["size"]
        rng = rng or random.Random(hash(o["name"]) % 10000 + self.meta.get("seed", 0))
        m = Mesh()
        m.box((0, 0, hgt / 2), (w, d, hgt), self.mat_colore(o.get("material", "building"), o["color"]))
        pannelli = o["panels"]
        if isinstance(pannelli, dict):
            pannelli = self._pannelli_casuali(pannelli, w, d, hgt, rng)
        for p in pannelli:
            prof = p.get("depth", 0.06)
            c, r = self._su_faccia(p.get("face", "front"), w, d, p.get("x", 0.0), p.get("z", hgt / 2), prof)
            m.box(c, (p.get("w", 2.0), prof, p.get("h", 1.2)), self.emissivo(p.get("color", S.PASTELLI["menta"]),
                                                                        p.get("strength", 1.1)), rot=r)
        fin = o.get("windows")
        if fin:
            colw = fin.get("color", S.PASTELLI["crema"])
            fw, fh = fin.get("size", (0.8, 1.1))
            righe, colonne = int(fin.get("rows", 6)), int(fin.get("cols", 4))
            marg = fin.get("margin", 1.0)
            acceso = fin.get("fill", 0.6)
            for f in fin.get("faces", ["front"]):
                larg = w if f in ("front", "back") else d
                for i in range(righe):
                    for j in range(colonne):
                        if rng.random() > acceso:
                            continue
                        x = -larg / 2 + marg + (larg - 2 * marg) * (j + 0.5) / colonne
                        z = marg + (hgt - 2 * marg) * (i + 0.5) / righe
                        c, r = self._su_faccia(f, w, d, x, z, 0.04)
                        m.box(c, (fw, 0.04, fh), self.emissivo(colw, fin.get("strength", 1.6)), rot=r)
        ob = m.oggetto(self, f"{o['name']}.mesh", root)
        if o.get("bevel", 0) > 0:
            md = ob.modifiers.new("Bevel", "BEVEL")
            md.width = o["bevel"]
            md.segments = 1
        return ob

    def p_skyline(self, o, root):
        rng = random.Random(int(o["seed"]))
        pos = 0.0
        asse = 0 if o["axis"] == "x" else 1
        for i in range(int(o["count"])):
            w = rng.uniform(*o["width"])
            d = rng.uniform(*o["depth"])
            hgt = rng.uniform(*o["height"])
            sub = self.vuoto(f"{o['name']}.b{i}", root)
            loc = [0.0, 0.0, 0.0]
            loc[asse] = pos + (w if asse == 0 else d) / 2
            sub.location = loc
            pannelli = o["panels"] if isinstance(o["panels"], (dict, list)) else {"count": 3}
            self.p_building_block({"name": f"{o['name']}.b{i}", "size": [w, d, hgt], "color": o["color"],
                                   "material": o.get("material", "building"), "panels": pannelli,
                                   "windows": None, "bevel": 0.0}, sub, rng)
            pos += (w if asse == 0 else d) + o["spacing"]
        return root

    def p_billboard(self, o, root):
        m = Mesh()
        bw, bh = o["size"]
        m.box((0, 0, 0), (bw, 0.04, bh), self.emissivo(o["color"], o["strength"]))
        if o.get("frame"):
            m.box((0, 0.04, 0), (bw + 0.2, 0.06, bh + 0.2), self.mat_colore("black_matte", o["frame"]))
        return m.oggetto(self, f"{o['name']}.mesh", root)

    def p_street(self, o, root):
        m = Mesh()
        sw, sl = o["size"]
        bagnato = float(o["wet"])
        asfalto = self.mat_colore("wet_ground", o["color"])
        asfalto["roughness"] = 0.015 + (1 - bagnato) * 0.45
        asfalto["rough_max"] = 0.09 + (1 - bagnato) * 0.5
        asfalto["specular"] = 0.75
        m.parte([(-sw / 2, -sl / 2, 0), (sw / 2, -sl / 2, 0), (sw / 2, sl / 2, 0), (-sw / 2, sl / 2, 0)],
                [(0, 1, 2, 3)], asfalto)
        strisce = self.mat_colore("plastic", "#A7AAB0")
        strisce["roughness"] = 0.3
        cw = o.get("crosswalk")
        if cw:
            cx, cy = cw.get("center", (0.0, 0.0))
            n = int(cw.get("count", 8))
            larg, lung = cw.get("stripe", (0.5, 4.0))
            gap = cw.get("gap", 0.55)
            lungo_x = cw.get("axis", "x") == "x"
            tot = n * larg + (n - 1) * gap
            for i in range(n):
                off = -tot / 2 + larg / 2 + i * (larg + gap)
                if lungo_x:
                    m.box((cx + off, cy, 0.004), (larg, lung, 0.008), strisce)
                else:
                    m.box((cx, cy + off, 0.004), (lung, larg, 0.008), strisce)
        if o.get("lane_lines"):
            y = -sl / 2
            while y < sl / 2:
                m.box((0, y + 1.5, 0.004), (0.14, 3.0, 0.008), strisce)
                y += 6.0
        sp = o.get("sidewalks")
        if sp:
            hh, ww = sp.get("height", 0.15), sp.get("width", 3.0)
            mc = self.mat_colore("concrete", sp.get("color", "#2A2B2F"))
            gap = sp.get("gap", 7.0)
            for sx in (1, -1):
                m.box((sx * (gap + ww / 2), 0, hh / 2), (ww, sl, hh), mc)
        return m.oggetto(self, f"{o['name']}.mesh", root)

    # prefab: interni -----------------------------------------------------------

    def _linee_pavimento(self, m: Mesh, tipo: str, w: float, d: float, y0: float = -1e9, mat=None):
        """Righe del pavimento: tatami, assi di legno o piastrelle (come piccoli listelli)."""
        if tipo == "tatami":
            lm = mat or self.mat_colore("tatami", "#A99367")
            y, riga = -d / 2, 0
            while y < d / 2 - 0.01:
                m.box((0, y, 0.003), (w, 0.022, 0.006), lm)
                x = -w / 2 + (0.9 if riga % 2 else 0.0)
                while x < w / 2:
                    if x > -w / 2 + 0.01:
                        m.box((x, min(y + 0.45, d / 2 - 0.45), 0.003), (0.022, min(0.9, d / 2 - y), 0.006), lm)
                    x += 1.8
                y += 0.9
                riga += 1
        elif tipo == "wood":
            lm = mat or self.mat_colore("wood_dark", "#2E1D11")
            x = -w / 2
            while x < w / 2:
                m.box((x, 0, 0.002), (0.012, d, 0.004), lm)
                x += 0.18
        elif tipo == "tiles":
            lm = mat or self.mat_colore("black_matte", "#16110D")
            passo = 1.2
            x = -w / 2 + passo / 2
            while x < w / 2:
                m.box((x, 0, 0.002), (0.02, d, 0.004), lm)
                x += passo
            y = -d / 2
            while y <= d / 2:
                m.box((0, y, 0.002), (w, 0.02, 0.004), lm)
                y += passo

    def _parete(self, m: Mesh, stile: str, lato: str, w: float, d: float, h: float, o: dict, mat_muro, telaio,
                trave):
        """Una parete della stanza (lato: back/left/right/front) con il suo decoro."""
        sp = 0.08
        if lato in ("back", "front"):
            lung = w
            base = Matrix.Translation((0, (d / 2 + sp / 2) * (1 if lato == "back" else -1), 0))
            if lato == "front":
                base = base @ Matrix.Rotation(math.pi, 4, "Z")
        else:
            lung = d
            # il lato decorato e' il -Y locale: va rivolto verso l'interno della stanza
            base = Matrix.Translation(((w / 2 + sp / 2) * (1 if lato == "right" else -1), 0, 0)) @ \
                Matrix.Rotation(math.radians(-90 if lato == "right" else 90), 4, "Z")
        m.box((0, 0, h / 2), (lung, sp, h), mat_muro, matrice=base)
        # fascia superiore in legno sopra l'architrave (kamoi): pannelli fino a "lintel"
        architrave = min(float(o.get("lintel", h - 0.36)), h)
        fascia = h - architrave if o.get("beam", True) else 0.0
        if fascia > 0.01:
            m.box((0, -0.02, h - fascia / 2), (lung, sp + 0.04, fascia), trave, matrice=base)
        if stile == "shoji":
            n = max(1, round(lung / o.get("panel_width", 1.5)))
            for k in range(1, n):
                x = -lung / 2 + lung * k / n
                m.box((x, -sp / 2 - 0.006, (h - fascia) / 2), (0.028, 0.02, h - fascia), telaio, matrice=base)
            m.box((0, -sp / 2 - 0.006, 0.03), (lung, 0.02, 0.06), telaio, matrice=base)
            m.box((0, -sp / 2 - 0.008, h - fascia - 0.012), (lung, 0.024, 0.024), telaio, matrice=base)
        elif stile in ("wood", "wood_slats"):
            listelli = self.mat_colore("wood", o.get("wall_color", "#8A5A34"))
            x = -lung / 2 + 0.06
            hh = h - fascia
            while x < lung / 2:
                m.box((x, -sp / 2 - 0.015, hh / 2), (0.05, 0.03, hh), listelli, matrice=base)
                x += 0.11

    def p_room(self, o, root):
        w, d, h = o["size"]
        m = Mesh()
        muro_col = o["wall_color"]
        mat_muro = self.mat_colore("shoji" if o["wall_style"] == "shoji" else "beige", muro_col)
        if o["wall_style"] == "wood":
            mat_muro = self.mat_colore("wood_dark", "#3A2414")
        telaio = self.mat_colore("navy", o["frame_color"])
        trave = self.mat_colore("wood", o["beam_color"])
        pav = {"tatami": "tatami", "wood": "wood_light", "concrete": "concrete", "tiles": "tile"}[o["floor"]]
        m.box((0, 0, -0.03), (w + 0.2, d + 0.2, 0.06), S.risolvi_materiale(pav))
        self._linee_pavimento(m, o["floor"], w, d)
        for lato in o["walls"]:
            self._parete(m, o["wall_style"], lato, w, d, h, o, mat_muro, telaio, trave)
        if o["ceiling"]:
            m.box((0, 0, h + 0.03), (w + 0.2, d + 0.2, 0.06), self.mat_colore("wood", o["beam_color"]))
        ob = m.oggetto(self, f"{o['name']}.mesh", root)
        if o["light"]:
            self.luce({"name": f"{o['name']}.ceiling_light", "light_type": "area", "color": "#FFF0DE",
                       "energy": 3.0 * w * d, "size": w * 0.6, "size_y": d * 0.6,
                       "location": (0, 0, h - 0.05), "rotation": (0, 0, 0)}, root)
        return ob

    def p_corridor(self, o, root):
        """Corridoio lungo +Y a partire da y=0 (la mesh e' generata centrata e poi traslata)."""
        L, w, h = o["length"], o["width"], o["height"]
        m = Mesh()
        pav = {"tiles": self.mat_colore("tile", "#3B3029"), "wood": S.risolvi_materiale("wood"),
               "stone": self.mat_colore("tile", "#2C2C2E")}[o["floor"]]
        m.box((0, 0, -0.03), (w, L, 0.06), pav)
        self._linee_pavimento(m, "wood" if o["floor"] == "wood" else "tiles", w, L)
        muro = self.mat_colore("wood_dark", "#2E1C10")
        trave = self.mat_colore("wood_dark", "#4A2E1A")
        stile = {"name": o["name"], "beam": True, "wall_color": o["wall_color"], "lintel": h - 0.6}
        for lato in ("left", "right"):
            self._parete(m, o["wall_style"], lato, w, L, h, stile, muro, self.mat_colore("navy", "#1D2535"), trave)
        if o["ceiling"]:
            m.box((0, 0, h + 0.03), (w + 0.2, L, 0.06), self.mat_colore("black_matte", "#120C08"))
        if o["end"] == "wall":
            m.box((0, L / 2 + 0.04, h / 2), (w, 0.08, h), muro)
        if o["signs"]:
            insegna = self.mat_colore("navy", "#2A3244")
            y, k = -L / 2 + 1.4, 0
            while y < L / 2 - 0.5:
                sx = 1 if k % 2 else -1
                m.box((sx * (w / 2 - 0.02), y, h - 0.75), (0.04, 0.9, 0.7), insegna)
                y += 3.1
                k += 1
        ob = m.oggetto(self, f"{o['name']}.mesh", root)
        ob.data.transform(Matrix.Translation((0, L / 2, 0)))
        lamp = o["lamps"]
        n = int(lamp.get("count", 6))
        lati = {"both": (1, -1), "right": (1,), "left": (-1,)}[lamp.get("side", "both")]
        for i in range(n):
            y = L / n * (i + 0.5)
            for sx in lati:
                nome = f"{o['name']}.lamp{i}{'r' if sx > 0 else 'l'}"
                sost = self.vuoto(nome, root, (sx * (w / 2 - 0.38), y, lamp.get("height", 2.35)), 0.1)
                self.p_lantern({"name": nome, "radius": lamp.get("radius", 0.22), "color": lamp.get("color", "#FFF1DC"),
                                "strength": lamp.get("strength", 6.0), "light_energy": lamp.get("light_energy", 35.0),
                                "cord": 0.0, "stretch": 1.0}, sost)
        return ob

    def p_lantern(self, o, root):
        m = Mesh()
        r = o["radius"]
        m.sfera((0, 0, 0), r, self.emissivo(o["color"], o["strength"]), 24, scala=(1, 1, o.get("stretch", 1.1)))
        if o.get("cord", 0) > 0:
            m.cilindro((0, 0, r + o["cord"] / 2), 0.006, o["cord"], self.mat_colore("black_matte", "#111111"), 6)
        ob = m.oggetto(self, f"{o['name']}.mesh", root)
        ob.visible_shadow = False
        if o.get("light_energy", 0) > 0:
            self.luce({"name": f"{o['name']}.light", "light_type": "point", "color": o["color"],
                       "energy": o["light_energy"], "size": r * 0.9, "location": (0, 0, 0)}, root)
        return ob

    def p_tower_lattice(self, o, root):
        H, B, T = o["height"], o["base"], o["top"]
        n, t = int(o["levels"]), o["strut"]
        mat = self.emissivo(o["color"], o["emission"]) if o["emission"] > 0 else self.mat_colore("clay", o["color"])
        m = Mesh()

        def semi(z):
            return T / 2 + (B / 2 - T / 2) * (1 - z / H) ** 2.3

        livelli = [H * (i / n) ** 0.9 for i in range(n + 1)]
        angoli = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
        for a, b in zip(livelli, livelli[1:]):
            sa, sb = semi(a), semi(b)
            pa = [(sx * sa, sy * sa, a) for sx, sy in angoli]
            pb = [(sx * sb, sy * sb, b) for sx, sy in angoli]
            for k in range(4):
                m.asta(pa[k], pb[k], t * 1.6, mat)               # gambe
                m.asta(pb[k], pb[(k + 1) % 4], t, mat)           # anello
                m.asta(pa[k], pb[(k + 1) % 4], t * 0.7, mat)     # croci
                m.asta(pb[k], pa[(k + 1) % 4], t * 0.7, mat)
        for frac in (0.42, 0.72):
            z = H * frac
            s = semi(z) + 0.4
            m.box((0, 0, z), (2 * s, 2 * s, H * 0.025), mat)
        m.asta((0, 0, H), (0, 0, H + o["antenna"]), t * 1.4, mat)
        return m.oggetto(self, f"{o['name']}.mesh", root)

    def p_tree(self, o, root):
        m = Mesh()
        H, R = o["height"], o["radius"]
        tronco = self.mat_colore("clay", o["trunk_color"])
        chioma = self.mat_colore("clay", o["color"])
        m.cilindro((0, 0, H * 0.25), R * 0.09, H * 0.5, tronco, 12)
        if o["style"] == "cone":
            m.cilindro((0, 0, H * 0.62), R, H * 0.76, chioma, 24, raggio2=0.0, liscio=False)
        else:
            m.sfera((0, 0, H - R), R, chioma, 20)
            m.sfera((R * 0.55, 0.1, H - R * 1.35), R * 0.7, chioma, 16)
            m.sfera((-R * 0.5, -0.1, H - R * 1.3), R * 0.72, chioma, 16)
        return m.oggetto(self, f"{o['name']}.mesh", root)

    def p_table(self, o, root):
        m = Mesh()
        sx, sy, sz = o["size"]
        mat = self._mat_primitiva(o)
        m.box((0, 0, sz - 0.025), (sx, sy, 0.05), mat)
        for a in (1, -1):
            for b in (1, -1):
                m.box((a * (sx / 2 - 0.05), b * (sy / 2 - 0.05), (sz - 0.05) / 2), (0.05, 0.05, sz - 0.05), mat)
        return m.oggetto(self, f"{o['name']}.mesh", root)

    def p_chair(self, o, root):
        m = Mesh()
        hs = o["seat_height"]
        mat = self._mat_primitiva(o)
        m.box((0, 0, hs - 0.025), (0.45, 0.45, 0.05), mat)
        m.box((0, 0.205, hs + 0.25), (0.45, 0.04, 0.5), mat)
        for a in (1, -1):
            for b in (1, -1):
                m.box((a * 0.19, b * 0.19, (hs - 0.05) / 2), (0.04, 0.04, hs - 0.05), mat)
        return m.oggetto(self, f"{o['name']}.mesh", root)

    def p_car_interior(self, o, root):
        """Abitacolo attorno al guidatore: origine = punto a terra sotto il bacino."""
        sx = 1 if o["drive"] == "right" else -1   # lato della portiera rispetto al guidatore
        m = Mesh()
        cru = self.mat_colore("glossy_black", o["dash_color"])
        cru["roughness"] = 0.35
        sedile = self.mat_colore("black_matte", o["seat_color"])
        volante = self.mat_colore("glossy_black", o["wheel_color"])
        # pavimento, sedile e schienale
        m.box((0, -0.2, 0.08), (1.6, 1.8, 0.04), sedile)
        m.box((0, 0.02, 0.3), (0.52, 0.5, 0.14), sedile)
        mt = Matrix.Translation((0, 0.3, 0.68)) @ Matrix.Rotation(math.radians(-14), 4, "X")
        m.box((0, 0, 0), (0.5, 0.12, 0.72), sedile, matrice=mt)
        # cruscotto e palpebra degli strumenti
        m.box((-sx * 0.35, -0.95, 0.72), (1.9, 0.5, 0.3), cru)
        m.box((0, -0.82, 0.92), (0.46, 0.22, 0.12), cru)
        gauge = self.emissivo(o["gauges_color"], 2.2)
        for gx in (-0.09, 0.09):
            m.tornio([(0, 0), (0.055, 0), (0.055, 0.004), (0, 0.004)], gauge, 20, (gx, -0.705, 0.88),
                     matrice=Matrix.Rotation(math.radians(-80), 4, "X") @ Matrix.Translation((0, 0, 0)), liscio=False)
        # volante: corona, razze e piantone
        vol = Matrix.Translation((0, -0.5, 0.86)) @ Matrix.Rotation(math.radians(-62), 4, "X")
        R = 0.19
        n, k = 40, 10
        vs, fs = [], []
        for i in range(n):
            a = 2 * math.pi * i / n
            for j in range(k):
                b = 2 * math.pi * j / k
                vs.append(((R + 0.018 * math.cos(b)) * math.cos(a), (R + 0.018 * math.cos(b)) * math.sin(a),
                           0.018 * math.sin(b)))
        for i in range(n):
            for j in range(k):
                a0, a1 = i * k, ((i + 1) % n) * k
                fs.append((a0 + j, a1 + j, a1 + (j + 1) % k, a0 + (j + 1) % k))
        m.parte(vs, fs, volante, True, vol)
        for ang in (0, 120, 240):
            a = math.radians(ang + 90)
            m.asta(vol @ Vector((0, 0, 0)), vol @ Vector((R * math.cos(a), R * math.sin(a), 0)), 0.022, volante)
        m.cilindro((0, 0, -0.03), 0.06, 0.06, volante, 16, matrice=vol)
        m.asta(vol @ Vector((0, 0, -0.03)), Vector((0, -0.85, 0.68)), 0.05, volante)
        if o["frame"]:
            tel = cru
            # portiera, montanti, tetto
            m.box((sx * 0.62, -0.1, 0.55), (0.08, 1.4, 0.6), tel)
            m.asta((sx * 0.6, -1.15, 0.86), (sx * 0.55, -0.55, 1.28), 0.07, tel)
            m.asta((-sx * 1.2, -1.15, 0.86), (-sx * 1.15, -0.55, 1.28), 0.07, tel)
            m.box((-sx * 0.3, 0.0, 1.31), (1.9, 1.2, 0.05), tel)
            m.box((-sx * 0.3, -0.57, 1.27), (1.9, 0.08, 0.06), tel)
        return m.oggetto(self, f"{o['name']}.mesh", root)

    def p_text(self, o, root):
        cu = bpy.data.curves.new(o["name"] + ".text", "FONT")
        cu.body = o["text"]
        cu.size = float(o["size"])
        cu.extrude = float(o["extrude"])
        cu.align_x = {"center": "CENTER", "left": "LEFT", "right": "RIGHT"}.get(o["align"], "CENTER")
        cu.align_y = "BOTTOM"
        cu.materials.append(self.materiale(self.mat_colore(o["material"], o.get("color"))))
        ob = bpy.data.objects.new(o["name"] + ".text", cu)
        self.collega(ob, root)
        ob.rotation_euler = (math.radians(90), 0, 0)
        return ob

    p_sign = p_text

    # -- animazione -------------------------------------------------------------

    def anima_oggetti(self) -> None:
        for o in self._oggetti:
            root = self.radici[o["name"]]
            camp = moto.campiona_oggetto(o, self.frames, self.fps)
            distanze = None
            if camp is not None:
                self.campioni[o["name"]] = camp
                for f, c in enumerate(camp):
                    root.location = c["location"]
                    root.rotation_euler = rad(c["rotation"])
                    root.scale = c["scale"]
                    root.keyframe_insert("location", frame=f)
                    root.keyframe_insert("rotation_euler", frame=f)
                    root.keyframe_insert("scale", frame=f)
                distanze = [c["distance"] for c in camp]
            if o["type"] == "car" and distanze is not None:
                for ruota, r in self.ruote[o["name"]]:
                    for f, dist in enumerate(distanze):
                        ruota.rotation_euler = (dist / r, 0.0, 0.0)
                        ruota.keyframe_insert("rotation_euler", frame=f)
            if o["type"] == "mannequin" and (o.get("walk") or o.get("pose_keys")):
                pose = moto.campiona_pose(o, self.frames, distanze, self.fps)
                s = self._scala_manichini[o["name"]]
                for f, p in enumerate(pose):
                    self.applica_posa(o["name"], p, s, frame=f)
            vis = o.get("visible")
            if vis:
                da, a = vis.get("from", 0), vis.get("to", self.frames - 1)
                for ob in self.discendenti(root):
                    for f in range(self.frames):
                        nascosto = not (da <= f <= a)
                        if f == 0 or nascosto != (not (da <= f - 1 <= a)):
                            ob.hide_render = nascosto
                            ob.keyframe_insert("hide_render", frame=f)

    def posizione(self, nome: str, f: float):
        """Posizione mondo di un oggetto al frame ``f`` (scena valutata, con cache)."""
        if nome not in self._posizioni:
            ob = self.radici[nome]
            serie = []
            for k in range(self.frames):
                self.scene.frame_set(k)
                serie.append(tuple(ob.matrix_world.translation))
            self._posizioni[nome] = serie
            self.scene.frame_set(0)
        serie = self._posizioni[nome]
        i = max(0, min(len(serie) - 1, int(round(f))))
        return serie[i]

    def mira_luci(self) -> None:
        for ob, bersaglio in self._luci_mirate:
            p = moto.risolvi_punto(bersaglio, 0, self.posizione)
            ob.rotation_euler = moto.look_at_euler(ob.matrix_world.translation, p)

    # -- camera -----------------------------------------------------------------

    def imposta_camera(self) -> None:
        c = self.spec["camera"]
        dati = bpy.data.cameras.new("Camera")
        dati.lens = float(c["lens"])
        dati.sensor_fit = "HORIZONTAL"
        dati.sensor_width = float(c["sensor"])
        dati.clip_start = float(c["clip_start"])
        dati.clip_end = float(c["clip_end"])
        dati.shift_x, dati.shift_y = (float(x) for x in c["shift"])
        cam = bpy.data.objects.new("Camera", dati)
        self.collega(cam)
        self.scene.camera = cam
        self.camera = cam
        pose = moto.campiona_camera(c, self.frames, self.posizione, self.fps)
        statica = all(p["location"] == pose[0]["location"] and p["rotation"] == pose[0]["rotation"]
                      and p["lens"] == pose[0]["lens"] for p in pose)
        dof = c.get("dof")
        fuoco_auto = None
        if dof:
            dati.dof.use_dof = True
            dati.dof.aperture_fstop = float(dof["fstop"])
            fuoco = dof.get("focus")
            if isinstance(fuoco, (int, float)):
                dati.dof.focus_distance = float(fuoco)
            elif isinstance(fuoco, str):
                dati.dof.focus_object = self.radici[fuoco]
            elif isinstance(fuoco, dict):
                vu = self.vuoto("Camera.focus", self.radici[fuoco["object"]], vec3(fuoco.get("offset", (0, 0, 0))))
                dati.dof.focus_object = vu
            elif isinstance(fuoco, (list, tuple)):
                dati.dof.focus_object = self.vuoto("Camera.focus", None, vec3(fuoco))
            else:
                fuoco_auto = True  # distanza dal bersaglio dello sguardo, frame per frame
        for f, p in enumerate(pose):
            cam.location = p["location"]
            cam.rotation_euler = p["rotation"]
            dati.lens = p["lens"]
            fd = p.get("focus_distance")
            if fd is None and fuoco_auto and p.get("target") is not None:
                fd = moto.lunghezza(moto.sub(p["target"], p["location"]))
            if fd is not None and dof:
                dati.dof.focus_distance = float(fd)
            if statica and f > 0 and fd is None:
                break
            if not statica or fd is not None:
                cam.keyframe_insert("location", frame=f)
                cam.keyframe_insert("rotation_euler", frame=f)
                dati.keyframe_insert("lens", frame=f)
                if fd is not None and dof:
                    dati.dof.keyframe_insert("focus_distance", frame=f)

    # -- tutto ------------------------------------------------------------------

    def costruisci(self) -> None:
        svuota_scena()
        self.imposta_render()
        self.imposta_mondo()
        self.costruisci_oggetti()
        self.anima_oggetti()
        self.mira_luci()
        self.imposta_camera()
        self.imposta_compositor()
        self.scene.frame_set(0)


def costruisci_scena(spec: dict) -> Kit:
    """Punto d'ingresso: costruisce la scena descritta dalla spec normalizzata."""
    kit = Kit(spec)
    kit.costruisci()
    return kit


def renderizza_frame(percorso: str, frame: int) -> None:
    sc = bpy.context.scene
    sc.frame_set(frame)
    sc.render.filepath = percorso
    bpy.ops.render.render(write_still=True)

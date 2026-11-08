import sys, json

def sortie(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)

try:
    import trimesh
except ImportError:
    sortie({"ok": False, "erreur": "trimesh non installe : pip install trimesh"})

if len(sys.argv) < 2:
    sortie({"ok": False, "erreur": "chemin STL manquant"})

chemin = sys.argv[1]
try:
    m = trimesh.load(chemin, force="mesh")
except Exception as e:
    sortie({"ok": False, "erreur": "lecture impossible : " + str(e)})

if m.is_empty or len(m.faces) == 0:
    sortie({"ok": False, "erreur": "STL vide (le code OpenSCAD n a rien produit)"})

pieces = m.split(only_watertight=False)
nb_pieces = len(pieces)
etanche = bool(m.is_watertight)
zmin = float(m.bounds[0][2])
dims = [round(float(x), 2) for x in m.extents]
volume_cm3 = round(float(m.volume) / 1000, 2) if etanche else None

VOLUME_MAX = [300, 300, 300]   # a adapter si K2 Pro : [300, 300, 300]
problemes = []
if nb_pieces != 1:
    problemes.append(str(nb_pieces) + " pieces separees au lieu d une seule : les volumes doivent se chevaucher")
if not etanche:
    problemes.append("maillage non etanche")
if abs(zmin) > 0.05:
    problemes.append("la piece ne repose pas sur z=0 (zmin = " + str(round(zmin, 2)) + ")")
for i, axe in enumerate("XYZ"):
    if dims[i] > VOLUME_MAX[i]:
        problemes.append("trop grand en " + axe + " : " + str(dims[i]) + " mm > " + str(VOLUME_MAX[i]))

sortie({
    "ok": len(problemes) == 0,
    "pieces": nb_pieces,
    "etanche": etanche,
    "zmin": round(zmin, 2),
    "dimensions_mm": {"x": dims[0], "y": dims[1], "z": dims[2]},
    "volume_cm3": volume_cm3,
    "problemes": problemes
})
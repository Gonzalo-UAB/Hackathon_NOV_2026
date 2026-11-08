
import pandas as pd
import numpy as np
import json

def convert_types(obj):
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    return str(obj)

print("1. Llegint dades...")
df_aules = pd.read_csv("paquet/aules.csv")
df_proposta = pd.read_csv("proposta-aules.csv")
df_sessions = pd.read_csv("paquet/sessions.csv")

# Combinem proposta amb sessions per obtenir alumnes, durada, etc.
df_merged = pd.merge(
    df_proposta, 
    df_sessions[["id_sessio", "alumnes", "durada_min", "setmana"]], 
    on="id_sessio", 
    how="left"
)

# --- 1. GENERACIO DEL LAYOUT ---
col_aula_id = next((c for c in df_aules.columns if "aula" in c.lower() or "codi" in c.lower()), df_aules.columns[0])
col_cap = next((c for c in df_aules.columns if "capacitat" in c.lower() or "aforament" in c.lower()), df_aules.columns[-1])
col_desc = next((c for c in df_aules.columns if "descripcio" in c.lower() or "nom" in c.lower()), None)

building_z = {"Q4": -60, "Q3": -20, "Q6": -20, "Q2": 20, "Q5": 20, "Q1": 60, "QC": 100, "J": 140, "B3": 140}
building_x_base = {"Q1": -120, "Q2": -120, "Q3": -120, "Q4": -120, "Q5": 20, "Q6": 20, "QC": -100, "J": -120, "B3": 20}

rows_parsed = []
for _, row in df_aules.iterrows():
    aula_id = str(row[col_aula_id]).strip()
    if aula_id == "nan" or not aula_id: continue
        
    cap = float(row[col_cap]) if pd.notna(row[col_cap]) else 999.0
    parts = aula_id.split("/")
    if len(parts) >= 2:
        edifici = parts[0]
        codi = parts[1]
        
        piso = 0
        if len(codi) >= 4 and codi[0].isdigit(): piso = int(codi[0])
        elif len(codi) >= 3 and codi[0].isdigit(): piso = int(codi[0])
        elif "." in codi: piso = int(codi[0])
            
        num = int("".join(filter(str.isdigit, codi))) if any(str.isdigit(ch) for ch in codi) else 0
        desc = str(row[col_desc]) if col_desc and pd.notna(row[col_desc]) else ""
        
        rows_parsed.append({
            "id": aula_id, "edifici": edifici, "codi": codi, "piso": piso, 
            "num": num, "desc": desc, "capacitat": cap
        })

df_parsed = pd.DataFrame(rows_parsed).sort_values(by=["edifici", "piso", "num"])

layout_3d = []
for (edifici, piso), group in df_parsed.groupby(["edifici", "piso"]):
    z = int(building_z.get(edifici, -100))
    y = int(piso * 18)
    x_base = int(building_x_base.get(edifici, -100))
    
    for idx, (_, room) in enumerate(group.iterrows()):
        layout_3d.append({
            "id": str(room["id"]), "x": int(x_base + (idx * 18)), 
            "y": int(y), "z": int(z), "desc": str(room["desc"]), 
            "capacitat": float(room["capacitat"])
        })

with open("layout_proposta.json", "w", encoding="utf-8") as f:
    json.dump(layout_3d, f, ensure_ascii=False, default=convert_types)

capacitat_aules = {str(aula["id"]): float(aula["capacitat"]) for aula in layout_3d}
print("-> layout_proposta.json generat correctament.")

# --- 2. GENERACIO DE L'OCUPACIO ---
print("2. Processant ocupacio de la proposta...")
s2 = df_merged.copy()
col_sess_aula = "aula"
s2 = s2.dropna(subset=[col_sess_aula])

def obtenir_blocs(row):
    try:
        h_str = str(row.get("h_ini", "0")).strip()
        if h_str == "nan": return []
        
        if ":" in h_str:
            h = int(h_str.split(":")[0])
            m = int(h_str.split(":")[1])
        elif "." in h_str:
            h = int(float(h_str))
            m = int((float(h_str) - h) * 60)
        else:
            h = int(h_str)
            m = 0
            
        durada = int(float(row.get("durada_min", 60)))
        start_mins = h * 60 + m
        end_mins = start_mins + durada
        start_h = start_mins // 60
        end_h = (end_mins - 1) // 60 
        
        blocs = []
        for current_h in range(start_h, end_h + 1):
            if 0 <= current_h < 24:
                blocs.append(f"{current_h:02d}:00")
        return blocs
    except Exception:
        return []

s2["blocs"] = s2.apply(obtenir_blocs, axis=1)
s2_exp = s2.explode("blocs")

def parse_dia(d):
    d = str(d).strip().upper()
    if "L" in d or d == "1" or "DILL" in d: return "L"
    if ("M" in d and "DI" not in d) or d == "2" or "DIMAR" in d: return "M"
    if "X" in d or "DIMEC" in d or d == "3" or d == "DC": return "X"
    if "J" in d or "DIJ" in d or d == "4" or d == "DJ": return "J"
    if "V" in d or "DIV" in d or d == "5" or "DV" in d: return "V"
    return d

s2_exp["dia_net"] = s2_exp["dia"].apply(parse_dia) if "dia" in s2_exp.columns else "L"
s2_exp = s2_exp.dropna(subset=["blocs"])

col_alumnes = "alumnes"
col_setmana = "setmana"

ocupacio = {"L":{}, "M":{}, "X":{}, "J":{}, "V":{}}
sessions_processades = 0

if col_setmana in s2_exp.columns:
    agrupat_setmana = s2_exp.groupby(["dia_net", "blocs", col_sess_aula, col_setmana])[col_alumnes].sum().reset_index()
    agrupat_final = agrupat_setmana.groupby(["dia_net", "blocs", col_sess_aula])[col_alumnes].max().reset_index()
else:
    agrupat_final = s2_exp.groupby(["dia_net", "blocs", col_sess_aula])[col_alumnes].mean().reset_index()

for _, row in agrupat_final.iterrows():
    dia = row["dia_net"]
    hora = row["blocs"]
    aula = str(row[col_sess_aula]).strip()
    alumnes_totals = row[col_alumnes]
    
    if dia not in ocupacio: ocupacio[dia] = {}
    if hora not in ocupacio[dia]: ocupacio[dia][hora] = {}
        
    cap = capacitat_aules.get(aula, 999)
    if alumnes_totals > cap:
        ocupacio[dia][hora][aula] = 2
    else:
        ocupacio[dia][hora][aula] = 1
    sessions_processades += 1

with open("ocupacio_proposta.json", "w", encoding="utf-8") as f:
    json.dump(ocupacio, f, ensure_ascii=False)

print(f"-> S'han guardat {sessions_processades} franges a ocupacio_proposta.json")

# --- 3. GENERACIO HTML ---
print("3. Generant visor3d-proposta.html...")

html_template = '''<!DOCTYPE html>
<html lang="ca">
<head>
    <meta charset="UTF-8">
    <title>Visor 3D Aules UAB (Proposta)</title>
    <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;700&display=swap" rel="stylesheet">
    <style>
        body { margin: 0; overflow: hidden; font-family: 'Nunito', 'Segoe UI', sans-serif; background-color: #636e72; }
        #ui { position: absolute; bottom: 30px; left: 50%; transform: translateX(-50%); background: rgba(255,255,255,0.95); padding: 15px 35px; border-radius: 12px; display: flex; gap: 25px; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .control { display: flex; flex-direction: column; gap: 8px; font-weight: 700; color: #2d3436; }
        select, input[type=range] { cursor: pointer; }
        select { padding: 5px; border-radius: 5px; border: 1px solid #b2bec3; font-weight: 700; }
        #legend { position: absolute; top: 20px; right: 20px; background: rgba(255,255,255,0.95); padding: 15px 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.15); color: #2d3436; font-weight: 700; }
        .leg-item { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 15px; }
        .box { width: 18px; height: 18px; border-radius: 4px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        #info { position: absolute; top: 20px; left: 20px; background: rgba(45, 52, 54, 0.9); color: white; padding: 15px 20px; border-radius: 12px; pointer-events: none; display: none; }
        #info strong { color: #74b9ff; font-size: 18px; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
</head>
<body>
    <div id="legend">
        <div class="leg-item"><div class="box" style="background: #dfe6e9;"></div>Lliure</div>
        <div class="leg-item"><div class="box" style="background: #00b894;"></div>Ocupada</div>
        <div class="leg-item"><div class="box" style="background: #d63031;"></div>Excés d\'Aforament</div>
    </div>
    <div id="info"></div>
    <div id="ui">
        <div class="control">
            <label>Dia:</label>
            <select id="dia">
                <option value="L">Dilluns</option><option value="M">Dimarts</option>
                <option value="X">Dimecres</option><option value="J">Dijous</option>
                <option value="V">Divendres</option>
            </select>
        </div>
        <div class="control">
            <label>Hora: <span id="hora-txt">08:00</span></label>
            <input type="range" id="hora" min="8" max="20" step="1" value="8" style="width: 200px;">
        </div>
    </div>
    <script>
        let layout = []; let ocupacio = {}; const rooms = {};
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(50, window.innerWidth/window.innerHeight, 0.1, 1000);
        camera.position.set(0, 150, 180);
        const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.shadowMap.enabled = true;
        document.body.appendChild(renderer.domElement);
        
        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.85); scene.add(ambientLight);
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.4); dirLight.position.set(50, 120, 80); dirLight.castShadow = true; scene.add(dirLight);

        const geo = new THREE.BoxGeometry(14, 10, 14);
        const terra = new THREE.Mesh(new THREE.PlaneGeometry(350, 300), new THREE.MeshLambertMaterial({color: 0x95a5a6}));
        terra.rotation.x = -Math.PI / 2; terra.position.y = -5; terra.receiveShadow = true; scene.add(terra);

        function createTextSprite(msg) {
            const canvas = document.createElement('canvas'); const ctx = canvas.getContext('2d');
            canvas.width = 256; canvas.height = 128; ctx.font = "bold 32px sans-serif";
            ctx.fillStyle = "rgba(45, 52, 54, 1.0)"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
            ctx.fillText(msg, 128, 64);
            const tex = new THREE.CanvasTexture(canvas);
            const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
            const sprite = new THREE.Sprite(mat); sprite.scale.set(16, 8, 1); return sprite;
        }

        function inicialitzarLayout(data) {
            layout = data;
            layout.forEach(aula => {
                const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({color: 0xdfe6e9}));
                mesh.position.set(aula.x, aula.y, aula.z); mesh.castShadow = true; mesh.userData = aula;
                scene.add(mesh); rooms[aula.id] = mesh;
                mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({color: 0xb2bec3})));
                const txt = createTextSprite(aula.id); txt.position.y = 9; mesh.add(txt);
            });
        }

        function actualitzar() {
            const dia = document.getElementById('dia').value;
            const hora = document.getElementById('hora').value.padStart(2, '0') + ':00';
            document.getElementById('hora-txt').textContent = hora;
            const dades = (ocupacio[dia] && ocupacio[dia][hora]) ? ocupacio[dia][hora] : {};
            Object.keys(rooms).forEach(id => {
                const est = dades[id] || 0;
                rooms[id].material.color.setHex(est === 1 ? 0x00b894 : (est === 2 ? 0xd63031 : 0xdfe6e9));
            });
        }

        document.getElementById('dia').addEventListener('change', actualitzar);
        document.getElementById('hora').addEventListener('input', actualitzar);

        Promise.all([fetch('layout_proposta.json').then(r=>r.json()), fetch('ocupacio_proposta.json').then(r=>r.json())])
        .then(([l, o]) => { ocupacio = o; inicialitzarLayout(l); actualitzar(); });

        const raycaster = new THREE.Raycaster(); const mouse = new THREE.Vector2();
        window.addEventListener('mousemove', (e) => {
            mouse.x = (e.clientX / window.innerWidth) * 2 - 1; mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
            raycaster.setFromCamera(mouse, camera);
            const intersects = raycaster.intersectObjects(Object.values(rooms));
            const info = document.getElementById('info');
            if (intersects.length > 0) {
                const d = intersects[0].object.userData;
                info.style.display = 'block'; info.innerHTML = `<strong>${d.id}</strong><br>${d.desc}<br>Capacitat: ${d.capacitat}`;
            } else { info.style.display = 'none'; }
        });

        function anim() { requestAnimationFrame(anim); renderer.render(scene, camera); }
        anim();
    </script>
</body>
</html>'''

with open("visor3d-proposta.html", "w", encoding="utf-8") as f:
    f.write(html_template)

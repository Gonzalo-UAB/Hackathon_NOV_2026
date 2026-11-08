import os
import re
import json
import duckdb
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# 1. Configuració de la pàgina
st.set_page_config(
    page_title="Assistent d'Horaris - UAB",
    page_icon="🎓",
    layout="wide"
)

# 2. Carregar variables d'entorn (.env)
load_dotenv()

@st.cache_resource
def get_openai_client():
    return OpenAI(
        base_url=os.getenv("OPENAI_BASE_URL"),
        api_key=os.getenv("OPENAI_API_KEY")
    )

client = get_openai_client()

# 3. Resolució de rutes dels fitxers CSV
def get_csv_path(filename: str) -> str:
    path_in_paquet = os.path.join("paquet", filename)
    if os.path.exists(path_in_paquet):
        return path_in_paquet.replace("\\", "/")
    elif os.path.exists(filename):
        return filename
    else:
        raise FileNotFoundError(f"No s'ha trobat el fitxer {filename}")

# 4. Inicialitzar DuckDB amb VISTES
@st.cache_resource
def init_duckdb():
    con = duckdb.connect(database=':memory:')
    sessions_csv = get_csv_path("sessions.csv")
    aules_csv = get_csv_path("aules.csv")
    activitats_csv = get_csv_path("activitats.csv")

    con.execute(f"CREATE VIEW sessions AS SELECT * FROM read_csv_auto('{sessions_csv}')")
    con.execute(f"CREATE VIEW aules AS SELECT * FROM read_csv_auto('{aules_csv}')")
    con.execute(f"CREATE VIEW activitats AS SELECT * FROM read_csv_auto('{activitats_csv}')")
    return con

con = init_duckdb()

def executar_sql_duckdb(query_sql: str) -> tuple[str, int]:
    try:
        clean_sql = query_sql.strip().rstrip(";")
        df = con.execute(clean_sql).df()
        if df.empty:
            return "[]", 0
        return df.head(20).to_json(orient="records"), len(df)
    except Exception as e:
        return json.dumps([{"error_sql": str(e)}]), 0

# --- PROMPTS DEL SISTEMA ---

PROMPT_GENERAR_SQL = """
Ets un expert en SQL per a DuckDB. La teva ÚNICA tasca és convertir la pregunta de l'usuari en una consulta SQL vàlida.

ESQUEMA DE LES TAULES I COLUMNES REALS:

1. `sessions` (classes assignades):
   - id_sessio (text, ex: 'S00001')
   - assignatura (text, ex: 'Aplicacions Informàtiques')
   - grup (text, ex: 'TE/21', 'PAUL/211', 'PLAB/413')
   - tipus (text: 'TE', 'PAUL', 'PLAB', 'SEM')
   - semestre (text: 'C/1', 'C/2')
   - dia (text: REGLA ESTRICTA DE DIES: 'L' = Dilluns, 'M' = Dimarts, 'X' = Dimecres, 'J' = Dijous, 'V' = Divendres)
   - h_ini (text: format 'HH:MM', ex: '08:30', '12:30')
   - h_fi (text: format 'HH:MM', ex: '10:30', '14:30')
   - aula_partida (text: nom de l'aula assignada, ex: 'Q3/0007', 'Q4/0011', o NULL si no té)
   - titulacions_curs (text, ex: 'GEI:1r')
   - alumnes (enter)
   - docents (text, ex: 'D225')

2. `aules` (espais de l'escola):
   - aula (text, ex: 'Q3/0007')
   - capacitat (enter)
   - tipus (text: 'Aules docents', 'Laboratoris docents', 'seminari', 'aula informatica')
   - ordinaria (enter: 1 o 0)

REGLES PER A GENERAR SQL:
1. SELECCIÓ DE COLUMNES OBLIGATÒRIA:
   - A la clàusula SELECT de `sessions`, inclou SEMPRE les columnes d'evidència: `id_sessio, assignatura, grup, dia, h_ini, h_fi, aula_partida`.
   - MAI facis `SELECT aula_partida` sol o `SELECT DISTINCT aula_partida`. Selecciona sempre totes les columnes d'evidència per poder verificar la resposta.
2. MAPPING DE DIES:
   * Dilluns -> 'L', Dimarts -> 'M', Dimecres -> 'X', Dijous -> 'J', Divendres -> 'V'
3. CERCA DE TEXT / ASSIGNATURES:
   - Utilitza `ILIKE` o coincidències parcials per cercar assignatures (ex: `assignatura ILIKE '%Anàlisi Estadística%'` o `assignatura ILIKE '%Estadística%'`).
4. LA COLUMNA D'AULA A `sessions` ÉS `aula_partida`.
5. FORMAT DE RESPOSTA:
   - Respon ÚNICAMENT amb la consulta SQL dins d'un bloc ```sql ... ```. No afegeixis cap text explicatiu.
"""

PROMPT_RESPOSTA_FINAL = """
Ets l'assistent oficial de Gestió Acadèmica de l'Escola d'Enginyeria de la UAB.
Respon a la pregunta de l'usuari utilitzant ÚNICAMENT les dades extretes de la base de dades JSON.

REGLES:
1. Si el JSON està buit (`[]`), respon clarament indicant que l'aula està lliure o que no hi ha dades registrades per a aquesta franja.
2. Si hi ha registres, explica la resposta de forma clara i cita SEMPRE l'evidència (`id_sessio`, `assignatura`, `grup` i `aula_partida`).
3. Mai t'inventis cap informació no present al JSON.
"""

def processar_pregunta(pregunta: str):
    res_sql = client.chat.completions.create(
        model="ornith",
        messages=[
            {"role": "system", "content": PROMPT_GENERAR_SQL},
            {"role": "user", "content": pregunta}
        ],
        temperature=0.0
    )
    
    text_sql_raw = res_sql.choices[0].message.content or ""
    match = re.search(r"```sql\s*(.*?)\s*```", text_sql_raw, re.DOTALL)
    query_sql = match.group(1) if match else text_sql_raw.strip()
    
    json_resultats, num_fils = executar_sql_duckdb(query_sql)
    
    res_final = client.chat.completions.create(
        model="ornith",
        messages=[
            {"role": "system", "content": PROMPT_RESPOSTA_FINAL},
            {"role": "user", "content": f"Pregunta: {pregunta}\n\nDades SQL (JSON):\n{json_resultats}"}
        ],
        temperature=0.2
    )
    
    resposta_text = res_final.choices[0].message.content or "No s'ha pogut obtenir cap resposta."
    return resposta_text, query_sql, json_resultats, num_fils

# --- INTERFÍCIE D'USUARI ---

st.title("🎓 Assistent d'Horaris - Escola d'Enginyeria UAB")
st.caption("Nivell 3 (IA) • Consultes deterministes a DuckDB amb el model `ornith` de la UAB")

# Gestió de l'historial del xat
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostrar l'historial
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "sql" in message and message["sql"]:
            with st.expander("🔍 Auditoria de Dades i Codi SQL (Per al Jurat)"):
                st.code(message["sql"], language="sql")
                st.caption(f"Files retornades: {message['rows_count']}")
                try:
                    st.json(json.loads(message["json_data"]))
                except Exception:
                    st.text(message["json_data"])

# Entrada de l'usuari
if prompt := st.chat_input("Fes una consulta (ex: 'Està ocupada l'aula Q3/0007 el dilluns a les 12:30?')"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Consultant la base de dades..."):
            try:
                resposta, sql_code, raw_json, rows_count = processar_pregunta(prompt)
                st.markdown(resposta)
                
                with st.expander("🔍 Auditoria de Dades i Codi SQL (Per al Jurat)"):
                    st.code(sql_code, language="sql")
                    st.caption(f"Files trobades a DuckDB: {rows_count}")
                    try:
                        st.json(json.loads(raw_json))
                    except Exception:
                        st.text(raw_json)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": resposta,
                    "sql": sql_code,
                    "json_data": raw_json,
                    "rows_count": rows_count
                })
            except Exception as e:
                error_msg = f"Error en processar la consulta: {e}"
                st.error(error_msg)
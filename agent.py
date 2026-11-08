import os
import re
import json
import duckdb
from dotenv import load_dotenv
from openai import OpenAI

# 1. Carregar variables d'entorn (.env)
load_dotenv()

client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY")
)

# 2. Resolució dinàmica de rutes dels fitxers CSV
def get_csv_path(filename: str) -> str:
    """Busca el fitxer CSV a 'paquet/filename' o al directori actual."""
    path_in_paquet = os.path.join("paquet", filename)
    if os.path.exists(path_in_paquet):
        return path_in_paquet.replace("\\", "/")
    elif os.path.exists(filename):
        return filename
    else:
        raise FileNotFoundError(f"No s'ha trobat el fitxer {filename} ni a './' ni a './paquet/'")

# 3. Inicialització de DuckDB amb VISTES
con = duckdb.connect(database=':memory:')

try:
    sessions_csv = get_csv_path("sessions.csv")
    aules_csv = get_csv_path("aules.csv")
    activitats_csv = get_csv_path("activitats.csv")

    con.execute(f"CREATE VIEW sessions AS SELECT * FROM read_csv_auto('{sessions_csv}')")
    con.execute(f"CREATE VIEW aules AS SELECT * FROM read_csv_auto('{aules_csv}')")
    con.execute(f"CREATE VIEW activitats AS SELECT * FROM read_csv_auto('{activitats_csv}')")
    print("✅ Base de dades DuckDB carregada correctament amb les vistes [sessions, aules, activitats].")
except Exception as e:
    print(f"⚠️ Error en carregar les dades a DuckDB: {e}")

def executar_sql_duckdb(query_sql: str) -> tuple[str, int]:
    """Executa la consulta SQL directament sobre les vistes de DuckDB."""
    try:
        clean_sql = query_sql.strip().rstrip(";")
        df = con.execute(clean_sql).df()
        if df.empty:
            return "[]", 0
        return df.head(20).to_json(orient="records"), len(df)
    except Exception as e:
        return json.dumps({"error_sql": str(e)}), 0

PROMPT_GENERAR_SQL = """
Ets un expert en SQL per a DuckDB. La teva ÚNICA tasca és convertir la pregunta de l'usuari en una consulta SQL vàlida.

ESQUEMA DE LES TAULES I COLUMNES REALS:

1. `sessions` (classes assignades):
   - id_sessio (text, ex: 'S00001')
   - assignatura (text, ex: 'Aplicacions Informàtiques')
   - grup (text, ex: 'TE/21', 'PAUL/211', 'PLAB/413')
   - tipus (text: 'TE', 'PAUL', 'PLAB', 'SEM')
   - semestre (text: 'C/1', 'C/2')
   - dia (text: REGLA STRICTA DE DIES: 'L' = Dilluns, 'M' = Dimarts, 'X' = Dimecres, 'J' = Dijous, 'V' = Divendres)
   - h_ini (text: format 'HH:MM', ex: '08:30', '12:30')
   - h_fi (text: format 'HH:MM', ex: '10:30', '14:30')
   - aula_partida (text: nom de l'aula assignada, ex: 'Q3/0007', 'Q4/0011', o NULL si no té)
   - cohort (text, ex: 'GEI:1r')
   - alumnes (enter)
   - docents (text, ex: 'D225')

2. `aules` (espais de l'escola):
   - aula (text, ex: 'Q3/0007')
   - capacitat (enter)
   - tipus (text: 'Aules docents', 'Laboratoris docents', 'seminari', 'aula informatica')
   - ordinaria (enter: 1 o 0)

REGRAS PER A GENERAR SQL:
- MAPPING DE DIES: Converteix SEMPRE els dies en català a la lletra corresponent:
  * Dilluns -> 'L'
  * Dimarts -> 'M'
  * Dimecres -> 'X'
  * Dijous -> 'J'
  * Divendres -> 'V'
- LA COLUMNA D'AULA A LA TAULA `sessions` ÉS `aula_partida` (NO 'aula').
- Per comprovar si una aula està ocupada en una hora H (ex: '12:30'), comprova: `h_ini <= '12:30' AND h_fi > '12:30'`.
- Respon ÚNICAMENT amb la consulta SQL dins d'un bloc ```sql ... ```. No afegeixis text explicatiu.
"""

PROMPT_RESPOSTA_FINAL = """
Ets l'assistent oficial de Gestió Acadèmica de l'Escola d'Enginyeria de la UAB.
Respon a la pregunta de l'usuari utilitzant ÚNICAMENT les dades extretes de la base de dades JSON.

REGRAS:
1. Si el JSON està buit (`[]`), respon clarament indicant que l'aula està lliure o que no hi ha dades registrades per a aquesta franja.
2. Si hi ha registres, explica la resposta de forma clara i cita SEMPRE l'evidència (`id_sessio`, `assignatura`, `grup` i `aula_partida`).
3. Mai t'inventis cap informació no present al JSON.
"""

def processar_pregunta(pregunta: str) -> str:
    # PAS 1: Generar la consulta SQL
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
        
    print(f"\n🔍 [SQL Generat]: {query_sql}")
    
    # PAS 2: Executar la consulta SQL a DuckDB
    json_resultats, num_fils = executar_sql_duckdb(query_sql)
    print(f"📊 [Resultats]: {num_fils} files trobades")
    
    # PAS 3: Redacció de la resposta final
    res_final = client.chat.completions.create(
        model="ornith",
        messages=[
            {"role": "system", "content": PROMPT_RESPOSTA_FINAL},
            {"role": "user", "content": f"Pregunta: {pregunta}\n\nDades SQL (JSON):\n{json_resultats}"}
        ],
        temperature=0.2
    )
    
    return res_final.choices[0].message.content or "No s'ha pogut obtenir cap resposta del model."

if __name__ == "__main__":
    print("🤖 Agent d'Horaris UAB (Model: ornith + DuckDB) actiu!")
    print("Escriu la teva pregunta (o 'sortir' per tancar):")
    
    while True:
        usuari = input("\n> ")
        if usuari.lower() in ["sortir", "exit", "quit"]:
            break
        
        if usuari.strip():
            print("Processant la consulta...")
            try:
                resposta = processar_pregunta(usuari)
                print(f"\nAgent:\n{resposta}")
            except Exception as e:
                print(f"\nError durant l'execució: {e}")
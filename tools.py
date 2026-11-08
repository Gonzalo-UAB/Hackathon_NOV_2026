import os
import duckdb
import json

class HorarisQueryEngine:
    def __init__(self, data_folder="paquet"):
        self.con = duckdb.connect(database=':memory:')
        self.data_folder = data_folder
        
        # Resolució de rutes
        sessions_path = self._get_path("sessions.csv")
        aules_path = self._get_path("aules.csv")
        activitats_path = self._get_path("activitats.csv")

        # Crear Vistes DuckDB
        self.con.execute(f"CREATE VIEW sessions AS SELECT * FROM read_csv_auto('{sessions_path}')")
        self.con.execute(f"CREATE VIEW aules AS SELECT * FROM read_csv_auto('{aules_path}')")
        self.con.execute(f"CREATE VIEW activitats AS SELECT * FROM read_csv_auto('{activitats_path}')")

    def _get_path(self, filename: str) -> str:
        path_in_paquet = os.path.join(self.data_folder, filename)
        if os.path.exists(path_in_paquet):
            return path_in_paquet.replace("\\", "/")
        elif os.path.exists(filename):
            return filename
        else:
            raise FileNotFoundError(f"No s'ha trobat {filename}")

    def executar_sql(self, query_sql: str) -> str:
        """Executa una consulta SQL directa sobre les vistes de DuckDB."""
        try:
            df = self.con.execute(query_sql).df()
            if df.empty:
                return json.dumps({"resultat": "Sense resultats", "fils": 0})
            return df.head(20).to_json(orient="records")
        except Exception as e:
            return json.dumps({"error": str(e)})

    def cercar_aula_lliure(self, dia: str, hora_inici: str, capacitat_min: int, semestre: str = 'C/2'):
        """Troba aules lliures en un dia (L, M, X, J, V) i hora específics."""
        sql = f"""
        SELECT a.aula, a.capacitat, a.tipus
        FROM aules a
        WHERE a.capacitat >= {capacitat_min}
          AND a.aula NOT IN (
              SELECT DISTINCT s.aula_partida 
              FROM sessions s
              WHERE s.dia = '{dia}' 
                AND s.semestre = '{semestre}'
                AND s.h_ini <= '{hora_inici}' 
                AND s.h_fi > '{hora_inici}' 
                AND s.aula_partida IS NOT NULL
          )
        ORDER BY a.capacitat ASC
        """
        return self.executar_sql(sql)
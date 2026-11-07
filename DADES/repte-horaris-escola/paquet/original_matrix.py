import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# 1. Cargar los datos
df = pd.read_csv('sessions.csv')

# Eliminamos filas que no tengan hora de inicio o turno requerido (opcional pero recomendado)
df = df.dropna(subset=['h_ini', 'torn_requerit']).copy()

# 2. Función para derivar el turno real según la hora
def calcular_turno_real(hora_str):
    try:
        horas, minutos = map(int, str(hora_str).split(':'))
        # 14:30 en minutos es 14 * 60 + 30 = 870
        if horas * 60 + minutos < 870:
            return 'mati'
        else:
            return 'tarda'
    except:
        return None

# Aplicar la función para crear la nueva columna
df['torn_actual'] = df['h_ini'].apply(calcular_turno_real)

# Normalizar textos para evitar errores por mayúsculas/minúsculas o espacios
df['torn_requerit'] = df['torn_requerit'].astype(str).str.lower().str.strip()
df['torn_actual'] = df['torn_actual'].astype(str).str.lower().str.strip()

# 3. Crear la matriz cruzada con crosstab
matriz_turnos = pd.crosstab(
    df['torn_requerit'], 
    df['torn_actual'], 
    rownames=['Turno Teórico (torn_requerit)'], 
    colnames=['Turno Real (torn_actual)']
)

print("Matriz de resultados:")
print(matriz_turnos)

# 4. Generar el mapa de calor con Seaborn
plt.figure(figsize=(8, 6))
sns.heatmap(matriz_turnos, annot=True, fmt='d', cmap='Blues', cbar=True)
plt.title('Matriz de Cruce de Turnos: Teórico vs Real')
plt.tight_layout()

# Mostrar el gráfico o guardarlo
plt.savefig('matrix_turnos.png')
plt.show()
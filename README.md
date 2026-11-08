# Repte d'Horaris i Espais:

Aquest repositori conté el codi font, els models d'optimització, les eines de visualització 3D i els scripts d'anàlisi de dades per afrontar el repte de gestió d'horaris, assignació d'aules i optimització d'espais.

---

## Estructura del Repositori

### Models d'Optimització i Codi Principal

- `app.py` / `agent.py` / `tools.py`: Aplicació principal basada en Streamlit o agents intel·ligents per interactuar amb el sistema d'horaris.

- `model_5-1.py` al `model_5-4.py`: Scripts iteratius de resolució i optimització dels horaris i assignació de recursos.

- `Generador_visor_proposta.py`: Script encarregat de processar les dades i generar els fitxers necessaris per als visualitzadors.

### Anàlisi i Gràfics

- `quadern_analisis.ipynb`: Quadern de Jupyter amb l'anàlisi exploratòria de dades (EDA) inicial (Nivell 1), mapes de calor d'ocupació i validació de capacitats.

- `grafic_umbral.py`: Script per generar gràfics d'anàlisi d'humbrals d'ocupació i limitacions d'aules.

- `grafics_analisi/`: Directori que emmagatzema les figures i gràfics generats durant les analítiques.

### Visualitzadors 3D i Interfícies

`visor3d.html`: Visor interactiu en 3D per explorar l'ocupació actual de les aules i espais.

`visor3d-proposta.html`: Visor interactiu en 3D per comparar l'estat actual amb la proposta d'horaris optimitzada.

### Dades i Configuracions

`proposta-aules.csv`: Fitxer amb la proposta d'assignació d'aules resultant del model.

`ocupacio.json` i `ocupacio_proposta.json`: Estructures de dades en format JSON que alimenten els visualitzadors amb l'ocupació base i la proposada.

`layout.json` i `layout_proposta.json`: Configuracions espacials i d'infraestructura per a la representació gràfica.

---

## Començar

- Instal·lar dependències: Assegura't de tenir Python instal·lat i les llibreries necessàries ( Pandas, Streamlit, etc.).

- Executar l'anàlisi: Pots explorar el quadern quadern_analisis.ipynb per veure les conclusions del Nivell 1.

- Llançar l'aplicació o visor: Obre visor3d.html al teu navegador o executa l'aplicació amb Streamlit mitjançant:

streamlit run app.py


👥 Autors i Context

Projecte desenvolupat per donar solució a la gestió d'espais docents i optimització de torns a l'Escola d'Enginyeria de la UAB.

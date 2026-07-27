# Transcriptor local de reuniones

Aplicación local para grabar, transcribir y diarizar reuniones. La implementación principal está en Python para poder reutilizarla más adelante desde Kivy, una API local o una aplicación de escritorio. El script Bash es solamente un lanzador.

## Cambios de esta versión

- Código Python separado por responsabilidades.
- CLI reutilizable.
- Perfiles independientes.
- `initial_prompt.txt` breve.
- `hotwords.txt` para nombres y términos técnicos.
- Evita explicaciones del tipo `“Meli” significa Mercado Libre`, que Whisper puede recitar como si fueran audio.
- Progreso calculado con los timestamps de WhisperX.
- Manejo seguro del código `255` de FFmpeg.
- Limpieza conservadora de repeticiones exactas.
- Tests unitarios con `pytest`.
- Preparado para una futura interfaz Kivy.

## Estructura

```text
transcriptor/
├── pyproject.toml
├── README.md
├── grabar_transcribir_diarizar.sh
├── src/
│   └── meetings_transcriber/
│       ├── __init__.py
│       ├── audio.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── postprocess.py
│       ├── profiles.py
│       ├── progress.py
│       └── transcription.py
└── tests/
    ├── test_audio.py
    ├── test_postprocess.py
    ├── test_profiles.py
    ├── test_progress.py
    └── test_transcription.py
```

Las reuniones quedan fuera del repositorio:

```text
textos_reuniones/
├── Shipii/
│   ├── initial_prompt.txt
│   ├── hotwords.txt
│   └── Reunion_2026-07-24_11-09-47/
│       ├── microfono.wav
│       ├── reunion_mezclada.wav
│       ├── reunion_mezclada.json
│       ├── sistema.wav
│       ├── transcripcion.txt
│       └── transcripcion_speakers.txt
└── motonave/
    ├── initial_prompt.txt
    ├── hotwords.txt
    └── Reunion_.../
```

## Instalación

```bash
cd ~/proyectos/meetings/transcriptor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install whisper-ctranslate2 whisperx
python -m pip install -e '.[dev]'
```

Dependencias del sistema:

```bash
sudo apt install ffmpeg pulseaudio-utils libnotify-bin
```

## Configuración

Archivo:

```text
~/.config/meetings-transcriptor.env
```

Ejemplo para CPU:

```bash
export HF_TOKEN='hf_REEMPLAZAR'
export TRANSCRIPTOR_VENV="$HOME/proyectos/meetings/transcriptor/.venv"
export WHISPERX_BIN="$TRANSCRIPTOR_VENV/bin/whisperx"
export WHISPER_CTRANSLATE2_BIN="$TRANSCRIPTOR_VENV/bin/whisper-ctranslate2"
export DEVICE=cpu
export COMPUTE_TYPE=int8
export MODELO=large-v3
export BATCH_SIZE=2
export THREADS=4
```

Para GPU NVIDIA, después de instalar correctamente CUDA y PyTorch:

```bash
export DEVICE=cuda
export COMPUTE_TYPE=float16
```

## Perfiles

Primera ejecución:

```bash
./grabar_transcribir_diarizar.sh --profile Shipii
```

Crea:

```text
textos_reuniones/Shipii/initial_prompt.txt
textos_reuniones/Shipii/hotwords.txt
```

### `initial_prompt.txt`

Debe ser corto y describir solo idioma y registro:

```text
Conversación informal de trabajo en español rioplatense de Argentina.
```

Se limita a 180 caracteres. Para vocabulario se usa `hotwords.txt`.

### `hotwords.txt`

Una palabra o frase por línea:

```text
Shipii
Javier
Mateo
Nacho
Tobías
Fulfillment
Tienda Nube
Mercado Libre
Meli
shipper
courier
tracking
Notion Calendar
Full
el finde
```

No escribir frases explicativas:

```text
“Full” es un servicio de Shipii.
“Meli” significa Mercado Libre.
“El finde” significa el fin de semana.
```

Esas oraciones completas pueden filtrarse a la transcripción.

## Español argentino o rioplatense

Para reuniones de Buenos Aires y gran parte de Argentina conviene:

```text
español rioplatense de Argentina
```

`Español argentino` es correcto, pero más amplio. `Rioplatense` describe mejor el voseo, la entonación y expresiones como `el finde`, `laburar`, `chabón` y `quilombo`. WhisperX sigue recibiendo `--language es`; la frase solo aporta contexto.

## Uso

Grabar:

```bash
./grabar_transcribir_diarizar.sh --profile Shipii
```

Procesar un audio existente:

```bash
./grabar_transcribir_diarizar.sh \
    --profile Shipii \
    --audio /ruta/reunion_mezclada.wav
```

Listar perfiles:

```bash
./grabar_transcribir_diarizar.sh --list-profiles
```

Ejecución directa en Python:

```bash
.venv/bin/python -m meetings_transcriber.cli --profile Shipii
```

## Progreso

WhisperX muestra líneas como:

```text
Transcript: [741.569 --> 768.856]
```

Son segundos desde el inicio del audio. La aplicación obtiene la duración con `ffprobe` y agrega:

```text
Progreso de audio: [ 64.07%] 12:49 / 20:00
```

Es progreso sobre la duración de audio transcripta, no una predicción exacta del tiempo restante. Después todavía pueden faltar alineación y diarización. También se activa `--print_progress True`.

## Reducción de alucinaciones

La ejecución usa:

```text
--condition_on_previous_text False
--vad_method pyannote
--initial_prompt <texto breve>
--hotwords <vocabulario>
```

El posprocesado elimina segmentos u oraciones consecutivas idénticas. Conserva repeticiones naturales como:

```text
No, no, no es un cambio.
```

## FFmpeg código 255

Al detener con `Ctrl+C`, FFmpeg puede devolver `255` aunque haya cerrado correctamente los WAV. Se aceptan `0`, `130` y `255`, pero se valida con `ffprobe` que cada archivo exista y tenga duración positiva.

## Tests

```bash
source .venv/bin/activate
pytest
```

Cobertura:

```bash
pytest --cov=meetings_transcriber --cov-report=term-missing
```

Lint:

```bash
ruff check .
```

## Diseño para Kivy

La GUI futura debería importar Python directamente, no ejecutar Bash:

```python
from meetings_transcriber.audio import record_meeting
from meetings_transcriber.config import load_settings
from meetings_transcriber.profiles import create_run_paths, ensure_profile
from meetings_transcriber.transcription import transcribe_whisperx
```

Una aplicación Kivy podrá listar perfiles, editar prompts y hotwords, iniciar/detener grabación, mostrar progreso, reprocesar audios, abrir transcripciones y mapear `SPEAKER_00` a nombres.

## GPU y monitores

WhisperX puede acelerarse con una NVIDIA y CUDA. Para `large-v3`, 8 GB de VRAM es un piso razonable; 12 GB da más margen. No hace falta reservar otra GPU solo para los monitores: el escritorio suele usar una fracción pequeña de recursos comparado con la transcripción.

Conectar ambos monitores a la misma NVIDIA simplifica drivers. Un adaptador VGA-DVI pasivo solo funciona si la salida DVI es DVI-I y entrega señal analógica. DVI-D a VGA requiere adaptador activo. Conviene revisar los conectores exactos antes de comprar.

## Seguridad

```bash
chmod 600 ~/.config/meetings-transcriptor.env
chmod 700 ~/proyectos/meetings/textos_reuniones
```

No versionar tokens, audios ni transcripciones.

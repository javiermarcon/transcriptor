# Transcriptor local de reuniones

Aplicación local para grabar, transcribir y diarizar reuniones. La implementación principal está en Python para poder reutilizarla más adelante desde Kivy, una API local o una aplicación de escritorio. El script Bash es solamente un lanzador.

Para controlar grabaciones desde Google Meet en Firefox, usá la extensión
[transcriptor-firefox](https://github.com/javiermarcon/transcriptor-firefox)
junto con el host Native Messaging de este repo (ver sección más abajo).

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
- Pregunta si transcribir después de `Ctrl+C` al grabar.
- `--meeting` transcribe una carpeta de reunión ya grabada, in situ.
- `--list-meetings` lista reuniones del perfil y marca si tienen transcripción.
- `DEVICE=auto` elige CUDA o CPU según la máquina; plantilla `meetings-transcriptor.env.example`.
- Knobs de WhisperX configurables (beam, VAD, umbrales) y filtro de alucinaciones en posprocesado.
- Preparado para una futura interfaz Kivy.
- Host Firefox Native Messaging (`com.meetings.transcriptor`) con captura por ventana X11/Wayland y fallback explícito a monitor; UI en [transcriptor-firefox](https://github.com/javiermarcon/transcriptor-firefox).

## Estructura

```text
transcriptor/
├── pyproject.toml
├── README.md
├── meetings-transcriptor.env.example
├── grabar_transcribir_diarizar.sh
├── scripts/
│   └── native-messaging.sh
├── src/
│   └── meetings_transcriber/
│       ├── __init__.py
│       ├── audio.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── native_controller.py
│       ├── native_host.py
│       ├── native_messaging_install.py
│       ├── native_protocol.py
│       ├── meet_events.py
│       ├── attribution.py
│       ├── audio_energy.py
│       ├── postprocess.py
│       ├── profiles.py
│       ├── progress.py
│       ├── transcription.py
│       └── window_capture.py
└── tests/
    ├── test_audio.py
    ├── test_attribution.py
    ├── test_cli.py
    ├── test_config.py
    ├── test_meet_events.py
    ├── test_native_controller.py
    ├── test_native_host.py
    ├── test_native_messaging_install.py
    ├── test_native_protocol.py
    ├── test_postprocess.py
    ├── test_profiles.py
    ├── test_progress.py
    ├── test_transcription.py
    └── test_window_capture.py
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
│       ├── reunion.mp4
│       ├── sistema.wav
│       ├── session.json
│       ├── meet_events.jsonl
│       ├── transcripcion.txt
│       ├── transcripcion_speakers.txt
│       └── transcripcion_atribuida.json
└── motonave/
    ├── initial_prompt.txt
    ├── hotwords.txt
    └── Reunion_.../
```

## Instalación

```bash
cd ~/proyectos/meetings/transcriptor
# Recomendado: Python 3.12 o 3.13 (WhisperX 3.8.x no declara soporte 3.14)
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install 'whisperx>=3.8.6' || pip install --no-deps 'whisperx>=3.8.6'
python -m pip install -r requirements.txt
python -m pip install -e '.[dev]'
```

`whisperx` va aparte porque su metadata exige `torch~=2.8.0` y el
resolver de pip falla si ya tenés un torch CUDA más nuevo (p. ej.
`2.11+cu128`) o Python 3.14; en ese caso `--no-deps` + `requirements.txt`
completan el resto. El archivo fija además `transformers` y
`huggingface-hub<1` (pip a veces los omite o sube el hub a >=1 y rompe
la alineación Wav2Vec2).

PyTorch suele venir con CUDA vía WhisperX; eso es lo adecuado para una
NVIDIA (p. ej. RTX 3090). Si en algún momento forzaste la build
**CPU-only** (como describe la sección siguiente), podés volver a CUDA
con el procedimiento de más abajo.

Dependencias del sistema:

```bash
sudo apt install ffmpeg pulseaudio-utils libnotify-bin
```

La grabación de video en GNOME/X11 también requiere `xrandr` (paquete `x11-xserver-utils`).

En **Wayland**, la captura de ventana/monitor usa el portal ScreenCast y GStreamer:

```bash
sudo apt install python3-gi gir1.2-glib-2.0 xdg-desktop-portal xdg-desktop-portal-gnome \
    gstreamer1.0-tools gstreamer1.0-pipewire
```

### PyTorch solo CPU (laptop sin GPU)

Si vas a usar solo CPU, conviene reemplazar torch/torchaudio/torchvision por builds CPU-only. Para evitar conflictos ante futuras actualizaciones, obtené las versiones dinámicamente:

```bash
source .venv/bin/activate

# Extrae las versiones de torch, torchaudio y torchvision ya instaladas
TORCH_VERSION=$(python -c "import torch; print(torch.__version__.split('+')[0])")
TORCHAUDIO_VERSION=$(python -c "import torchaudio; print(torchaudio.__version__.split('+')[0])")
TORCHVISION_VERSION=$(python -c "import torchvision; print(torchvision.__version__.split('+')[0])")

# Reinstala todas con build CPU-only
pip install --force-reinstall \
    "torch==${TORCH_VERSION}" \
    "torchaudio==${TORCHAUDIO_VERSION}" \
    "torchvision==${TORCHVISION_VERSION}" \
    --index-url https://download.pytorch.org/whl/cpu
```

Verificación esperada:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# Ejemplo: 2.8.0+cpu False
```

### Volver a PyTorch con CUDA (después de haber instalado CPU-only)

Si antes instalaste las wheels CPU y ahora tenés una NVIDIA (p. ej. GeForce RTX 3090), reinstalá las mismas versiones desde el índice CUDA:

```bash
cd ~/proyectos/meetings/transcriptor
source .venv/bin/activate

TORCH_VERSION=$(python -c "import torch; print(torch.__version__.split('+')[0])")
TORCHAUDIO_VERSION=$(python -c "import torchaudio; print(torchaudio.__version__.split('+')[0])")
TORCHVISION_VERSION=$(python -c "import torchvision; print(torchvision.__version__.split('+')[0])")

# cu128 encaja con drivers recientes (CUDA 12.8 en el wheel).
# Alternativas: cu126 o cu124 si tu driver es más viejo.
# Ver opciones en https://pytorch.org/get-started/locally/
CUDA_INDEX_URL=https://download.pytorch.org/whl/cu128

pip install --force-reinstall \
    "torch==${TORCH_VERSION}" \
    "torchaudio==${TORCHAUDIO_VERSION}" \
    "torchvision==${TORCHVISION_VERSION}" \
    --index-url "${CUDA_INDEX_URL}"
```

Verificación esperada:

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'sin GPU')"
# Ejemplo: 2.8.0+cu128 / True / NVIDIA GeForce RTX 3090
```

Con `DEVICE=auto` en `~/.config/meetings-transcriptor.env`, la próxima ejecución debería mostrar `Dispositivo: cuda (float16)`.

Notas:

- No hace falta desinstalar a mano: `--force-reinstall` desde el índice CUDA reemplaza `+cpu` por `+cu128` (u otro).
- El driver NVIDIA debe estar instalado (`nvidia-smi` tiene que listar la placa). El toolkit CUDA completo en el sistema no es obligatorio: el wheel trae las libs que PyTorch necesita.
- Si `torch.cuda.is_available()` sigue en `False`, revisá el driver y que no quede otra instalación de torch en el PATH; confirmá que estás dentro de `.venv`.

### Warnings de NNPACK y checkpoint en CPU

Nota: si tienes instalada una versión de PyTorch compilada con soporte CUDA (por ejemplo `torch 2.8.0+cu128`), pueden aparecer advertencias como "Could not initialize NNPACK! Reason: Unsupported hardware." aunque `DEVICE` esté configurado a `cpu`. Esas líneas son warnings de optimizaciones por CPU (NNPACK) y no implican que el programa esté pidiendo GPU.

Durante la diarización con `pyannote`, también es normal ver mensajes de `NNPACK` en la consola. Son informativos y no detienen la transcripción ni implican uso de CUDA. Si el proceso te sugiere actualizar el checkpoint de Lightning, en un sistema CPU-only conviene hacerlo con `--map-to-cpu` (o con un pequeño script Python que cargue el checkpoint con `weights_only=False` y lo guarde otra vez):

```bash
source .venv/bin/activate
python - <<'PY'
import torch
from pathlib import Path

path = Path('.venv/lib/python3.12/site-packages/whisperx/assets/pytorch_model.bin')
checkpoint = torch.load(path, map_location='cpu', weights_only=False)
torch.save(checkpoint, path)
print('Checkpoint actualizado para CPU')
PY
```

Si prefieres usar la utilidad oficial de Lightning, ten en cuenta que en esta combinación de PyTorch + Lightning el flag `--map-to-cpu` puede fallar con `pickle.UnpicklingError` por el cambio de `weights_only` en versiones recientes. En ese caso, el snippet de Python de arriba es la opción más fiable.

```bash
source .venv/bin/activate
python -m lightning.pytorch.utilities.upgrade_checkpoint \
  .venv/lib/python3.12/site-packages/whisperx/assets/pytorch_model.bin \
  --map-to-cpu
```

Si el comando anterior falla, usa el snippet de Python mostrado más arriba. En esta configuración, ese método sí funciona.

## Configuración

Archivo (única fuente de parámetros por máquina):

```text
~/.config/meetings-transcriptor.env
```

Plantilla en el repo:

```bash
mkdir -p ~/.config
cp meetings-transcriptor.env.example ~/.config/meetings-transcriptor.env
chmod 600 ~/.config/meetings-transcriptor.env
```

Editá el archivo y poné tu `HF_TOKEN`. El CLI lo carga al arrancar (también podés pasar otra ruta con `--config`).

### Dispositivo: CPU o GPU

| Valor de `DEVICE` | Comportamiento |
|---|---|
| `auto` (default) | Si PyTorch detecta CUDA (p. ej. GeForce RTX 3090), usa `cuda`; si no, `cpu`. |
| `cuda` | Fuerza GPU. |
| `cpu` | Fuerza CPU. |

Si no definís `COMPUTE_TYPE`, se elige solo:

| Dispositivo resuelto | `COMPUTE_TYPE` por defecto |
|---|---|
| `cuda` | `float16` |
| `cpu` | `int8` |

Misma plantilla con `DEVICE=auto` sirve en escritorio (GPU) y laptop (CPU). Al iniciar una grabación o transcripción verás:

```text
Dispositivo: cuda (float16)
```

### Perfil optimizado para CPU (laptop)

Prioriza memoria y estabilidad. `BATCH_SIZE` bajo; umbrales anti-alucinación un poco más estrictos en VAD/silencio.

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

export VAD_METHOD=pyannote
export VAD_ONSET=0.55
export VAD_OFFSET=0.40
export CHUNK_SIZE=30

export TEMPERATURE=0
export BEAM_SIZE=5
export PATIENCE=1.0
export COMPRESSION_RATIO_THRESHOLD=2.4
export LOGPROB_THRESHOLD=-1.0
export NO_SPEECH_THRESHOLD=0.65
export CONDITION_ON_PREVIOUS_TEXT=0
export FILTER_HALLUCINATIONS=1
```

Usá PyTorch CPU-only en esa máquina (sección de instalación).

### Perfil optimizado para CUDA (p. ej. RTX 3090)

Valores validados en escritorio con RTX 3090 (buen equilibrio vocabulario / cobertura / sin basura de silencio). Son los mismos que trae `meetings-transcriptor.env.example`.

```bash
export HF_TOKEN='hf_REEMPLAZAR'
export TRANSCRIPTOR_VENV="$HOME/proyectos/meetings/transcriptor/.venv"
export WHISPERX_BIN="$TRANSCRIPTOR_VENV/bin/whisperx"
export WHISPER_CTRANSLATE2_BIN="$TRANSCRIPTOR_VENV/bin/whisper-ctranslate2"

export DEVICE=cuda
export COMPUTE_TYPE=float16
export MODELO=large-v3
export BATCH_SIZE=16
export THREADS=8

export VAD_METHOD=pyannote
export VAD_ONSET=0.45
export VAD_OFFSET=0.363
export CHUNK_SIZE=30

export TEMPERATURE=0
export BEST_OF=5
export BEAM_SIZE=8
export PATIENCE=1.0
export TEMPERATURE_INCREMENT_ON_FALLBACK=0.2
export COMPRESSION_RATIO_THRESHOLD=2.4
export LOGPROB_THRESHOLD=-1.0
export NO_SPEECH_THRESHOLD=0.55
export CONDITION_ON_PREVIOUS_TEXT=0
export FILTER_HALLUCINATIONS=1
# Opcional si conocés cuántas personas hay:
# export MIN_SPEAKERS=2
# export MAX_SPEAKERS=5
```

Notas:

- `BATCH_SIZE` alto acelera; no mejora fidelidad.
- `VAD_ONSET=0.45` + `NO_SPEECH_THRESHOLD=0.55` recupera más habla baja/rápida que umbrales más estrictos; el filtro de alucinaciones limpia basura residual.
- Si cortás habla real, bajá un poco más `VAD_ONSET` / `NO_SPEECH_THRESHOLD`; si vuelve basura de silencio, subilos.
- `hotwords.txt` ayuda con nombres (`Shipii`), pero Whisper igual puede escribir variantes fonéticas en algunos tramos; no es un diccionario forzoso.
- `FILTER_HALLUCINATIONS=1` elimina en posprocesado frases típicas de silencio (`gracias por ver el video`, créditos, etc.). Ampliá con `EXTRA_HALLUCINATION_PHRASES`.

### Variables de configuración

| Variable | Rol | Default |
|---|---|---|
| `HF_TOKEN` | Token Hugging Face (diarización) | obligatorio para transcribir |
| `BASE_DIR` | Perfiles/reuniones | `~/proyectos/meetings/textos_reuniones` |
| `WHISPERX_BIN` | Binario WhisperX | `.venv/bin/whisperx` |
| `DEVICE` | `auto` / `cuda` / `cpu` | `auto` |
| `COMPUTE_TYPE` | `float16` / `int8` / `float32` | según device |
| `MODELO` | Modelo Whisper | `large-v3` |
| `BATCH_SIZE` | Batch WhisperX | `2` |
| `THREADS` | Hilos | `4` |
| `VAD_METHOD` | `pyannote` o `silero` | `pyannote` |
| `VAD_ONSET` / `VAD_OFFSET` | Sensibilidad VAD | `0.500` / `0.363` |
| `CHUNK_SIZE` | Fusión de segmentos VAD (s) | `30` |
| `TEMPERATURE` | Sampling (0 = beam search) | `0` |
| `BEST_OF` | Candidatos si temperature > 0 | `5` |
| `BEAM_SIZE` | Ancho de beam | `5` |
| `PATIENCE` | Paciencia del beam | `1.0` |
| `LENGTH_PENALTY` | Penalización de longitud (opcional) | sin flag |
| `SUPPRESS_TOKENS` | Tokens a suprimir | `-1` |
| `SUPPRESS_NUMERALS` | `1`/`0` suprimir numerales | `0` |
| `TEMPERATURE_INCREMENT_ON_FALLBACK` | Sube temperature al fallar umbrales | `0.2` |
| `COMPRESSION_RATIO_THRESHOLD` | Descarta decodificaciones “repetitivas” | `2.4` |
| `LOGPROB_THRESHOLD` | Descarta baja confianza | `-1.0` |
| `NO_SPEECH_THRESHOLD` | Trata segmento como silencio | `0.6` |
| `CONDITION_ON_PREVIOUS_TEXT` | Condicionar con texto previo | `0` (recomendado) |
| `MIN_SPEAKERS` / `MAX_SPEAKERS` | Cotas de diarización (opcionales) | sin flag |
| `FILTER_HALLUCINATIONS` | Filtrar frases basura en posprocesado | `1` |
| `EXTRA_HALLUCINATION_PHRASES` | Frases extra, separadas por coma | vacío |
| `VOLUMEN_SISTEMA` / `VOLUMEN_MICROFONO` | Mezcla al grabar | `0.70` / `2.00` |
| `SINK` / `MIC` | PulseAudio | defaults del sistema |
| `RECORD_VIDEO` | Grabar el monitor y audio mezclado en MP4 | `true` |
| `VIDEO_MONITOR` | Salida `primary` de xrandr o nombre explícito | `primary` |
| `VIDEO_FPS` | Frames por segundo de la captura | `10` |
| `NATIVE_MESSAGING_PROFILE` | Perfil default del host Firefox (fallback si la extensión no envía `profile`) | opcional |
| `NATIVE_VIDEO_SOURCE` | `window` (default del host) o `monitor` (fallback explícito) | `window` |
| `LOCAL_PARTICIPANT_NAME` | Nombre del hablante local (mic) para atribución; sin inventar IDs | opcional |

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

El lanzador público es `./grabar_transcribir_diarizar.sh`. Equivale a
`python -m meetings_transcriber.cli` dentro del entorno virtual.

### Flags

| Flag | Descripción |
|---|---|
| `--profile` / `-p` | Perfil obligatorio salvo con `--list-profiles`. |
| `--audio` / `-a` | Uno o más audios existentes. Crea una carpeta `Reunion_...` nueva, copia o concatena el audio ahí y transcribe. |
| `--meeting` | Carpeta de una reunión ya grabada. Usa `reunion_mezclada.wav` de esa carpeta y escribe la transcripción en el mismo lugar. No crea otra `Reunion_...`. |
| `--list-profiles` | Lista perfiles en el directorio base. |
| `--list-meetings` | Lista reuniones del `--profile` y marca cuáles tienen o no `transcripcion.txt`. |
| `--config` | Ruta al archivo de entorno. Por defecto `~/.config/meetings-transcriptor.env`. |

`--audio` y `--meeting` son mutuamente excluyentes. `--list-meetings` no se combina con `--audio` ni `--meeting`.

### Grabar

```bash
./grabar_transcribir_diarizar.sh --profile Shipii
```

Arranca una única ejecución de FFmpeg y graba `sistema.wav`, `microfono.wav`,
`reunion_mezclada.wav` y, con `RECORD_VIDEO=true`, `reunion.mp4` en una carpeta nueva
`Reunion_AAAA-MM-DD_HH-MM-SS` dentro del perfil. El MP4 captura solamente el monitor
seleccionado por `VIDEO_MONITOR`, incluye el cursor y lleva la misma mezcla de audio.

Con `RECORD_VIDEO=false`, la grabación conserva el flujo anterior de solo audio y no
requiere `DISPLAY` ni `xrandr`.

Para dejar de grabar, `Ctrl+C`. FFmpeg cierra los WAV y el programa pregunta:

```text
¿Transcribir ahora? [S/n]
```

- `S`, Enter, `s`, `si` o `yes`: transcribe y diariza ahora.
- `n` o `no`: termina sin transcribir. Los audios quedan en la carpeta de la reunión. El programa imprime el comando para transcribir después con `--meeting`.
- Si la entrada no es una terminal (pipes, tests, CI), transcribe automáticamente.

### Transcribir una reunión ya grabada

```bash
./grabar_transcribir_diarizar.sh \
    --profile Shipii \
    --meeting /home/javier/proyectos/meetings/textos_reuniones/Shipii/Reunion_2026-07-24_11-09-47
```

También acepta el nombre de la carpeta si está bajo el perfil:

```bash
./grabar_transcribir_diarizar.sh \
    --profile Shipii \
    --meeting Reunion_2026-07-24_11-09-47
```

Requisitos:

- La carpeta debe existir.
- Debe contener `reunion_mezclada.wav` con tamaño mayor a cero.
- El `--profile` aporta `initial_prompt.txt` y `hotwords.txt`. Usá el mismo perfil con el que se grabó.

La salida (`reunion_mezclada.json`, `transcripcion.txt`, `transcripcion_speakers.txt`) se escribe en esa misma carpeta. Si ya había transcripciones, se sobrescriben.

Si la ruta es relativa, primero se busca en el directorio actual y, si no existe, en la carpeta del perfil.

### Procesar audios externos

```bash
./grabar_transcribir_diarizar.sh \
    --profile Shipii \
    --audio /ruta/parte1.ogg /ruta/parte2.ogg /ruta/parte3.ogg
```

También funciona con varias banderas `--audio`:

```bash
./grabar_transcribir_diarizar.sh \
    --profile Shipii \
    --audio /ruta/parte1.ogg \
    --audio /ruta/parte2.ogg
```

A diferencia de `--meeting`, esto crea una carpeta `Reunion_...` nueva y copia o concatena los archivos a `reunion_mezclada.wav` ahí. Transcribe de inmediato, sin preguntar.

### Listar perfiles

```bash
./grabar_transcribir_diarizar.sh --list-profiles
```

### Listar reuniones de un perfil

```bash
./grabar_transcribir_diarizar.sh --profile Shipii --list-meetings
```

Lista carpetas `Reunion_AAAA-MM-DD_HH-MM-SS` del perfil, en orden alfabético (cronológico por el nombre). Cada línea indica el estado de la transcripción:

```text
Reunion_2026-07-24_11-09-47	con transcripción
Reunion_2026-07-25_09-00-00	sin transcripción
```

Se considera **con transcripción** si existe `transcripcion.txt` con tamaño mayor a cero. Si no hay reuniones, imprime un mensaje y sale con código `0`.

Para transcribir una marcada como `sin transcripción`:

```bash
./grabar_transcribir_diarizar.sh --profile Shipii --meeting Reunion_2026-07-25_09-00-00
```

### Ejecución directa en Python

```bash
.venv/bin/python -m meetings_transcriber.cli --profile Shipii
```

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | Éxito, incluida grabación guardada sin transcribir. |
| `1` | Error de configuración, archivos, FFmpeg, WhisperX u otra falla de dominio. |
| `2` | Error de argumentos (por ejemplo `--audio` junto con `--meeting`, `--list-meetings` sin `--profile`, o combinaciones inválidas). |
| `130` | Interrumpido con `Ctrl+C` fuera de la detención normal de la grabación. |

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

La ejecución usa (valores por defecto o los del `.env`):

```text
--condition_on_previous_text False
--vad_method pyannote
--no_speech_threshold / --logprob_threshold / --compression_ratio_threshold
--initial_prompt <texto breve>
--hotwords <vocabulario>
```

El posprocesado:

- elimina segmentos u oraciones consecutivas idénticas;
- con `FILTER_HALLUCINATIONS=1`, descarta frases típicas de silencio (`gracias por ver el video`, créditos de subtítulos, etc.).

Conserva repeticiones naturales como:

```text
No, no, no es un cambio.
```

Los `hotwords` mejoran nombres frecuentes pero **no fuerzan** cada ocurrencia: en audio ruidoso o rápido Whisper puede seguir escribiendo variantes (`Jipi` por `Shipii`). Ajustá VAD/umbrales y el filtro de frases para la basura de silencios.

## FFmpeg código 255

Al detener con `Ctrl+C`, FFmpeg puede devolver `255` aunque haya cerrado correctamente los
archivos. Se aceptan `0`, `130` y `255`, pero se valida con `ffprobe` que cada WAV exista y
tenga duración positiva. Cuando el video está habilitado también se exige un MP4 legible,
con duración positiva y streams de audio y video. Después de esa detención, el programa
pregunta si transcribir ahora.

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
mypy src
```

Instalar el hook que ejecuta Ruff, mypy y pytest antes de cada commit:

```bash
pip install -e '.[dev]'
.venv/bin/pre-commit install
.venv/bin/pre-commit run --all-files
```

## Native Messaging (extensión Firefox)

La UI de Firefox vive en un repo aparte:
[javiermarcon/transcriptor-firefox](https://github.com/javiermarcon/transcriptor-firefox).

Este proyecto es el **host** nativo `com.meetings.transcriptor`: graba con
FFmpeg/WhisperX. La extensión solo controla (popup, Meet, Native Messaging).
**No** se implementa la UI aquí y **no** se graba desde JavaScript.

### Uso con la extensión

1. **Instalá este host** (deps Python, `.env` con `HF_TOKEN`, perfiles bajo
   `BASE_DIR`) y registrá el manifiesto:
   ```bash
   ./scripts/native-messaging.sh install
   ./scripts/native-messaging.sh verify
   ```
2. **Cloná y cargá la extensión** (carga temporal; se pierde al cerrar Firefox):
   ```bash
   git clone https://github.com/javiermarcon/transcriptor-firefox.git
   ```
   En Firefox: `about:debugging#/runtime/this-firefox` →
   **Cargar complemento temporal…** → elegí el `manifest.json` del clone.
   ID fijo: `meetings-transcriptor@example.org` (debe coincidir con
   `allowed_extensions` del manifiesto nativo).
3. Abrí una pestaña `https://meet.google.com/…`, abrí el popup de la extensión.
4. Elegí el **perfil** (la extensión llama `list_profiles`; si no mandás
   `profile`, el host usa `NATIVE_MESSAGING_PROFILE`).
5. **Iniciar grabación** / **Detener**. Al detener, la extensión puede pedir
   transcribir ahora; el host corre WhisperX y el popup muestra el progreso.
6. Si el popup dice **Desconectado**, el host no está instalado o el manifiesto
   no apunta al wrapper correcto: volvé a `./scripts/native-messaging.sh verify`.

Detalle de UI, pruebas y limitaciones de la extensión: README y docs del
[repo Firefox](https://github.com/javiermarcon/transcriptor-firefox).

### Protocolo v1

| Acción | Payload | Respuesta `data` (éxito) |
|---|---|---|
| `get_status` | `{}` | `{ "status": "ready"\|"recording"\|"error"\|"transcribing", "session_id"?: "…", "progress"?: … }` |
| `list_profiles` | `{}` | `{ "profiles": ["Shipii", …], "default_profile"?: "Shipii" }` |
| `start_recording` | `{ "url", "title", "profile"? }` | incluye `session_id`, `status`, `profile`, `video_source`, `meeting_dir` |
| `stop_recording` | `{ "session_id", "transcribe"? }` | `{ "status": "ready", "transcribed", … archivos … }` |
| `record_meet_event` | evento Meet (ver extensión) | `{ "recorded": true }` |

Con `transcribe: true` el host detiene FFmpeg y luego corre WhisperX (puede
demorar varios minutos). Con `false` o ausente solo guarda la grabación.

La extensión envía `record_meet_event` (metadatos de participantes/hablante
visual en Meet). El host los persiste en `meet_events.jsonl` de la reunión
activa (ver atribución más abajo).

### Atribución de hablantes

WhisperX diariza sobre `reunion_mezclada.wav` y produce `SPEAKER_00`,
`SPEAKER_01`, …. Esos IDs **se conservan**.

Tras la transcripción se genera `transcripcion_atribuida.json` (salida
adicional; no reemplaza `reunion_mezclada.json` ni `transcripcion_speakers.txt`).

**Pistas de audio:** la grabación ya guarda por separado `microfono.wav`
(local) y `sistema.wav` (remoto/monitor del sink). WhisperX solo oye la
mezcla, así que con la mezcla sola no se puede saber si `SPEAKER_00` es
Javier o Nacho. Con las pistas separadas sí se puede estimar qué cluster
corresponde al micrófono local. **No** hace falta cambiar el pipeline de
FFmpeg: las pistas independientes ya existen.

**Fuentes de evidencia (ninguna alcanza sola si es débil):**

| Fuente | Qué prueba | Límites |
|---|---|---|
| `local_microphone` | Dominio claro de energía en `microfono.wav` vs `sistema.wav` en los segmentos de un `SPEAKER_*` | Requiere `LOCAL_PARTICIPANT_NAME` (p. ej. `Javier`). Eco/auriculares pueden confundir. |
| `meet_active_speaker` | Eventos `active_speaker_changed` alineados al audio con ventana de incertidumbre (~1.5 s) | No usa solo el roster (`participant_joined`). Un blink visual no atribuye un segmento entero. |
| `combined` | Mic y Meet coinciden en el mismo nombre para el mismo `SPEAKER_*` | Si discrepan, se deja desconocido. |

No se asignan nombres por orden de IDs (`SPEAKER_00`≠Javier por convención).
Si la evidencia no alcanza, `attributed_name` queda `null`.

Configuración:

```bash
export LOCAL_PARTICIPANT_NAME=Javier
```

#### Esquema de `transcripcion_atribuida.json`

```json
{
  "schema_version": 1,
  "notes": ["…"],
  "speakers": {
    "SPEAKER_00": {
      "attributed_name": "Javier",
      "confidence": 0.81,
      "source": "local_microphone",
      "evidence": { "mic_dominance": 0.91, "speech_s": 42.5 }
    }
  },
  "segments": [
    {
      "start": 12.4,
      "end": 15.1,
      "text": "…",
      "speaker_id": "SPEAKER_00",
      "attributed_name": "Javier",
      "attribution": {
        "confidence": 0.81,
        "source": "local_microphone",
        "meet_event_refs": []
      }
    }
  ]
}
```

### Captura de video desde la extensión

- Por defecto el host usa `NATIVE_VIDEO_SOURCE=window`.
- **X11:** resuelve una ventana Firefox visible cuyo título coincida con la
  pestaña de Meet (`xwininfo`/`xprop` + `ffmpeg -f x11grab -window_id …`).
- **Wayland:** usa el portal `xdg-desktop-portal` ScreenCast (tipo ventana) +
  GStreamer `pipewiresrc` → FFmpeg. Aparece el selector del sistema: elegí la
  ventana de Meet. Requiere `python3-gi`, `xdg-desktop-portal` y
  `gstreamer1.0-pipewire` (paquetes del sistema; el worker corre con
  `/usr/bin/python3`).
- Si la captura de ventana no es posible, el host **responde error** explícito.
  **No** cambia solo al monitor completo.
- El fallback de monitor es **explícito**:
  ```bash
  export NATIVE_VIDEO_SOURCE=monitor
  ```
  - En X11: monitor de `VIDEO_MONITOR` vía `x11grab`.
  - En Wayland: portal ScreenCast (tipo monitor) + PipeWire/GStreamer.
  La respuesta incluye `"video_source": "monitor"` (no afirma que sea solo Meet).
- La CLI en Wayland también usa el portal para el monitor al grabar video.

### Instalación del host (manual)

No se registra solo. Tras `pip install -e .` (o con el `.venv` del proyecto):

```bash
# 1) Opcional: perfil default y modo de video en ~/.config/meetings-transcriptor.env
#    NATIVE_MESSAGING_PROFILE=shipii   # fallback si la extensión no envía profile
#    NATIVE_VIDEO_SOURCE=window       # o monitor

# 2) Registrá el manifiesto para Firefox (acción explícita)
./scripts/native-messaging.sh install
# equivalente:
#   .venv/bin/python -m meetings_transcriber.native_messaging_install install

# 3) Verificá
./scripts/native-messaging.sh verify
```

El instalador:

- resuelve el Python del `.venv` del proyecto (o `NATIVE_HOST_PYTHON` / `sys.executable`);
- escribe un wrapper ejecutable bajo `XDG_DATA_HOME/meetings-transcriptor/`
  (por defecto `~/.local/share/meetings-transcriptor/`);
- escribe `~/.mozilla/native-messaging-hosts/com.meetings.transcriptor.json`
  con `allowed_extensions: ["meetings-transcriptor@example.org"]` exactamente.

Desinstalación (no borra grabaciones ni el `.env`):

```bash
./scripts/native-messaging.sh uninstall
```

### Seguridad del host

- Framing: 4 bytes LE + JSON UTF-8; tamaño máximo acotado.
- Solo acciones allowlisted; sin shell arbitrario.
- `stdout` es solo protocolo; logs a `stderr`.
- Si Firefox cierra el pipe, el host envía `SIGINT` a FFmpeg y valida/cierra la sesión.

## Diseño para Kivy

La GUI futura debería importar Python directamente, no ejecutar Bash:

```python
from meetings_transcriber.audio import record_meeting
from meetings_transcriber.config import load_settings
from meetings_transcriber.profiles import create_run_paths, ensure_profile, list_meetings, load_existing_run_paths
from meetings_transcriber.transcription import transcribe_whisperx
```

Una aplicación Kivy podrá listar perfiles, listar reuniones con estado de transcripción, editar prompts y hotwords, iniciar/detener grabación, preguntar si transcribir al cortar, mostrar progreso, reprocesar una carpeta de reunión existente, abrir transcripciones y mapear `SPEAKER_00` a nombres.

## GPU y monitores

WhisperX puede acelerarse con una NVIDIA y CUDA. Para `large-v3`, 8 GB de VRAM es un piso razonable; 12 GB da más margen. No hace falta reservar otra GPU solo para los monitores: el escritorio suele usar una fracción pequeña de recursos comparado con la transcripción.

Conectar ambos monitores a la misma NVIDIA simplifica drivers. Un adaptador VGA-DVI pasivo solo funciona si la salida DVI es DVI-I y entrega señal analógica. DVI-D a VGA requiere adaptador activo. Conviene revisar los conectores exactos antes de comprar.

## Seguridad

```bash
chmod 600 ~/.config/meetings-transcriptor.env
chmod 700 ~/proyectos/meetings/textos_reuniones
```

No versionar tokens, audios ni transcripciones.

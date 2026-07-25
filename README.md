# Transcriptor local de reuniones

Este repositorio contiene un flujo completamente local para grabar reuniones, transcribirlas con Whisper Large V3 y separar hablantes con WhisperX + pyannote.

## Estructura

```text
~/proyectos/meetings/
├── meetily/
├── textos_reuniones/
│   ├── Shipii/
│   │   ├── initial_prompt.txt
│   │   └── Reunion_2026-07-24_01-11-22/
│   │       ├── microfono.wav
│   │       ├── reunion_mezclada.wav
│   │       ├── reunion_mezclada.json
│   │       ├── sistema.wav
│   │       ├── transcripcion.txt
│   │       └── transcripcion_speakers.txt
│   └── motonave/
│       ├── initial_prompt.txt
│       └── Reunion_2026-07-24_11-09-47/
│           ├── microfono.wav
│           ├── reunion_mezclada.wav
│           ├── reunion_mezclada.json
│           ├── sistema.wav
│           ├── transcripcion.txt
│           └── transcripcion_speakers.txt
└── transcriptor/
    ├── .git/
    ├── .venv/
    ├── grabar_y_transcribir_large.sh
    ├── grabar_transcribir_diarizar.sh
    └── README.md
```

El repositorio Git es `~/proyectos/meetings/transcriptor/`. Las grabaciones y transcripciones quedan fuera del repositorio, dentro de `~/proyectos/meetings/textos_reuniones/`.

## Script principal

`grabar_transcribir_diarizar.sh`:

- carga automáticamente `~/.config/meetings-transcriptor.env` si existe;
- usa perfiles independientes;
- crea un `initial_prompt.txt` por perfil;
- graba audio del sistema, micrófono y mezcla;
- usa WhisperX como camino principal;
- aplica VAD, `initial_prompt` y `condition_on_previous_text=False`;
- diariza con pyannote;
- genera texto plano y texto con hablantes;
- elimina repeticiones exactas consecutivas de forma conservadora;
- permite reprocesar un audio existente;
- trata el código 255 de FFmpeg como cierre normal cuando fue provocado por `Ctrl+C` y los WAV son válidos.

## Dependencias del sistema

```bash
sudo apt update
sudo apt install -y \
    ffmpeg \
    pulseaudio-utils \
    pavucontrol \
    python3 \
    python3-venv \
    python3-pip \
    libnotify-bin
```

Verificar:

```bash
ffmpeg -version
ffprobe -version
pactl --version
python3 --version
```

## Entorno virtual único

Se usa un solo virtualenv para `whisper-ctranslate2`, `whisperx`, `pyannote.audio`, `faster-whisper`, CTranslate2 y PyTorch.

```bash
cd ~/proyectos/meetings/transcriptor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install whisper-ctranslate2 whisperx
```

Verificar:

```bash
python -m pip show whisper-ctranslate2
python -m pip show whisperx
python -m pip show pyannote.audio
python -m pip check
./.venv/bin/whisper-ctranslate2 --help
./.venv/bin/whisperx --help
```

## Hugging Face y pyannote

La diarización necesita un token de Hugging Face y acceso al modelo gated.

1. Crear cuenta en `https://huggingface.co/join`.
2. Crear un token de lectura en `https://huggingface.co/settings/tokens`.
3. Aceptar la licencia en `https://huggingface.co/pyannote/speaker-diarization-community-1`.
4. Si WhisperX pide otros modelos, aceptar también los repositorios indicados, por ejemplo `speaker-diarization-3.1` o `segmentation-3.0`.

La página debe indicar:

```text
You have been granted access to this model
```

## Configuración

Crear:

```bash
mkdir -p ~/.config
nano ~/.config/meetings-transcriptor.env
```

Contenido recomendado:

```bash
export HF_TOKEN='hf_REEMPLAZAR'
export TRANSCRIPTOR_VENV="$HOME/proyectos/meetings/transcriptor/.venv"
export WHISPERX_BIN="$TRANSCRIPTOR_VENV/bin/whisperx"
export WHISPER_CTRANSLATE2_BIN="$TRANSCRIPTOR_VENV/bin/whisper-ctranslate2"
```

Proteger:

```bash
chmod 600 ~/.config/meetings-transcriptor.env
```

El script hace `source` automáticamente si el archivo existe, así que no hace falta cargarlo manualmente antes de cada reunión.

La autenticación persistente del CLI es opcional:

```bash
source ~/proyectos/meetings/transcriptor/.venv/bin/activate
hf auth login
hf auth whoami
```

Cuando pregunte si debe agregar el token como credencial Git, se puede responder `n`.

## Perfiles

Cada perfil representa un proyecto o empresa, por ejemplo:

```text
Shipii
motonave
Powermoto
ANDIS
```

La primera vez que se usa un perfil:

```bash
./grabar_transcribir_diarizar.sh --profile Shipii
```

el script crea:

```text
~/proyectos/meetings/textos_reuniones/Shipii/initial_prompt.txt
```

Editar luego:

```bash
nano ~/proyectos/meetings/textos_reuniones/Shipii/initial_prompt.txt
```

## initial_prompt.txt

Sirve para mejorar nombres propios, empresas, productos, siglas, modismos y términos técnicos.

No conviene escribir una explicación demasiado extensa. Funciona mejor como vocabulario y contexto breve.

### Ejemplo Shipii

```text
Reunión de Shipii en español rioplatense.

Participantes frecuentes: Javier, Mateo, Nacho, Ignacio, Tobías.

Términos frecuentes: Shipii, Full, Go, Fulfillment, Tienda Nube,
Mercado Libre, Meli, shipper, courier, tracking, QR, API token,
Notion, Notion Calendar, Google Calendar, cupones, suscripciones,
aseguradoras, hoja de ruta, frontend, backend, producción, dev.

Expresiones frecuentes:
“el finde” significa “el fin de semana”.
“Full” es un servicio de Shipii.
“Meli” significa Mercado Libre.
```

### Ejemplo Motonave

```text
Reunión de Motonave Group y Powermoto en español rioplatense.

Participantes frecuentes: Javier, Mariano, Florencia.

Términos frecuentes: Motonave, Powermoto, Mercado Libre,
WooCommerce, WordPress, Martfury, Meta Business, ManyChat,
WhatsApp Business, Merchant Center, SKU, GTIN, EAN, checkout,
Mercado Pago, catálogo, publicidad, campaña, pixel.
```

## Dispositivos de audio

```bash
pactl get-default-sink
pactl get-default-source
pactl list short sinks
pactl list short sources
```

El script usa por defecto el sink y source actuales. También se pueden sobrescribir:

```bash
SINK='nombre_del_sink' \
MIC='nombre_del_source' \
./grabar_transcribir_diarizar.sh --profile Shipii
```

## Grabación

```bash
cd ~/proyectos/meetings/transcriptor
./grabar_transcribir_diarizar.sh --profile Shipii
```

También acepta el perfil como argumento posicional:

```bash
./grabar_transcribir_diarizar.sh Shipii
```

Para Motonave:

```bash
./grabar_transcribir_diarizar.sh --profile motonave
```

Al terminar la reunión, presionar `Ctrl+C`.

El script conserva:

```text
sistema.wav
microfono.wav
reunion_mezclada.wav
```

Luego inicia la transcripción.

## Mezcla de audio

Valores predeterminados:

```bash
VOLUMEN_SISTEMA=0.70
VOLUMEN_MICROFONO=2.00
```

La mezcla aplica volumen, suma ambas entradas y limita picos a 0.95.

Sobrescribir temporalmente:

```bash
VOLUMEN_SISTEMA=0.75 \
VOLUMEN_MICROFONO=2.30 \
./grabar_transcribir_diarizar.sh --profile Shipii
```

## WhisperX

La ruta principal usa:

```text
WhisperX
├── VAD
├── Whisper Large V3
├── alineación
└── diarización
```

Parámetros principales:

```bash
--model large-v3
--language es
--device cpu
--compute_type int8
--batch_size 2
--vad_method pyannote
--initial_prompt "..."
--condition_on_previous_text False
--diarize
```

Desactivar `condition_on_previous_text` ayuda a reducir loops de texto en grabaciones largas. Puede perderse algo de continuidad entre ventanas, pero evita que una alucinación se propague durante muchos segmentos.

## VAD

El detector de actividad de voz ayuda a no transcribir silencios, ruido ambiente o fragmentos sin habla clara.

Variables:

```bash
VAD_METHOD=pyannote
VAD_ONSET=0.500
VAD_OFFSET=0.363
```

Ejemplo:

```bash
VAD_ONSET=0.55 \
VAD_OFFSET=0.40 \
./grabar_transcribir_diarizar.sh --profile Shipii
```

## Diarización

La diarización genera etiquetas como:

```text
[SPEAKER_00]
[SPEAKER_01]
[SPEAKER_02]
```

No identifica nombres reales. Para mapear nombres haría falta identificación manual, muestras de voz o metadata externa de Google Meet.

## Archivos generados

### reunion_mezclada.json

Salida estructurada de WhisperX con segmentos, timestamps, palabras y hablantes.

### transcripcion.txt

Texto sin etiquetas de hablantes.

### transcripcion_speakers.txt

Texto agrupado por hablante:

```text
[SPEAKER_00] Creo que este finde termino de hacer lo que me anotaste.
[SPEAKER_01] El lunes o martes podemos hacer una prueba.
```

## Limpieza de repeticiones

El script elimina segmentos consecutivos idénticos y oraciones completas idénticas repetidas dentro de un mismo segmento.

Ejemplo:

```text
¿Qué?
¿Qué?
¿Qué?
```

queda como:

```text
¿Qué?
```

No elimina repeticiones normales del habla como:

```text
No, no, no es un cambio.
```

La limpieza compara igualdad textual normalizada y no usa similitud aproximada.

## Reprocesar una reunión existente

```bash
cd ~/proyectos/meetings/transcriptor

./grabar_transcribir_diarizar.sh \
    --profile Shipii \
    --audio ~/proyectos/meetings/textos_reuniones/Reunion_2026-07-24_11-09-47/reunion_mezclada.wav
```

El script crea una nueva reunión dentro del perfil, copia el audio, usa el `initial_prompt.txt` del perfil y ejecuta WhisperX.

## Listar perfiles

```bash
./grabar_transcribir_diarizar.sh --list-profiles
```

## Variables configurables

| Variable | Predeterminado | Descripción |
|---|---|---|
| `BASE_DIR` | `~/proyectos/meetings/textos_reuniones` | Directorio de perfiles |
| `PROFILE` | vacío | Perfil predeterminado |
| `MODELO` | `large-v3` | Modelo Whisper |
| `THREADS` | `4` | Hilos del fallback |
| `BATCH_SIZE` | `2` | Batch de WhisperX |
| `VOLUMEN_SISTEMA` | `0.70` | Volumen del sistema |
| `VOLUMEN_MICROFONO` | `2.00` | Volumen del micrófono |
| `VAD_METHOD` | `pyannote` | Backend VAD |
| `VAD_ONSET` | `0.500` | Umbral de inicio |
| `VAD_OFFSET` | `0.363` | Umbral de finalización |
| `SINK` | sink predeterminado | Salida de audio |
| `MIC` | source predeterminado | Micrófono |
| `HF_TOKEN` | vacío | Token de Hugging Face |
| `WHISPERX_BIN` | autodetectado | Ejecutable WhisperX |
| `WHISPER_CTRANSLATE2_BIN` | autodetectado | Ejecutable fallback |

## Código 255 de FFmpeg

Al detener con `Ctrl+C`, FFmpeg puede devolver 255 aunque haya cerrado correctamente los WAV.

El script acepta 0, 130 y 255, pero solo continúa si los tres archivos existen, no están vacíos, son legibles por `ffprobe` y tienen duración positiva.

Si todo es válido, muestra:

```text
FFmpeg recibió Ctrl+C y cerró correctamente los tres WAV.
```

## Advertencia de Lightning

Puede aparecer:

```text
Lightning automatically upgraded your loaded checkpoint...
```

No es un error. No hace falta reescribir el checkpoint para que WhisperX funcione.

## Primer uso

La primera ejecución puede tardar más porque descarga modelos, construye cachés y prepara Matplotlib.

Mensajes como:

```text
Matplotlib is building the font cache
```

son normales.

## Rendimiento en CPU

En un Intel Core i7-3770K con 32 GB de RAM, Whisper Large V3 puede tardar bastante. El flujo está pensado para grabar durante la reunión y procesar después.

Ajustes iniciales:

```bash
BATCH_SIZE=2
MODELO=large-v3
```

Si falta memoria:

```bash
BATCH_SIZE=1
```

Para mayor velocidad con menor precisión:

```bash
MODELO=medium
```

## Fallback sin diarización

Si WhisperX o `HF_TOKEN` no están disponibles, el script puede usar `whisper-ctranslate2` y generar solamente `transcripcion.txt`.

WhisperX sigue siendo la opción recomendada por su VAD, alineación y diarización.

## Solución de problemas

### hf auth whoami muestra Not logged in

`HF_TOKEN` y `hf auth login` son mecanismos distintos. WhisperX puede funcionar solo con `HF_TOKEN`.

### Error 401 o 403

Verificar que el token esté cargado y que la licencia del modelo gated haya sido aceptada.

```bash
source ~/.config/meetings-transcriptor.env
printf '%s\n' "${HF_TOKEN:+HF_TOKEN configurado}"
```

No imprimir ni compartir el token completo.

### WHISPERX_BIN apunta a entornos viejos

Usar el virtualenv único:

```bash
export TRANSCRIPTOR_VENV="$HOME/proyectos/meetings/transcriptor/.venv"
export WHISPERX_BIN="$TRANSCRIPTOR_VENV/bin/whisperx"
export WHISPER_CTRANSLATE2_BIN="$TRANSCRIPTOR_VENV/bin/whisper-ctranslate2"
```

### El prompt no corrige una palabra

Agregar la forma correcta a `initial_prompt.txt`, por ejemplo:

```text
Fulfillment
el finde
Tienda Nube
Mercado Libre
Meli
```

El prompt ayuda, pero no garantiza corrección absoluta.

### Muchas repeticiones

Verificar VAD y `--condition_on_previous_text False`. Revisar silencios largos, ruido, voces bajas, clipping o voces superpuestas.

### La diarización asigna mal hablantes

Puede ocurrir por superposición, voces parecidas, grabación mono, eco o participantes que hablan muy poco.

### Micrófono demasiado fuerte

```bash
VOLUMEN_MICROFONO=1.50
```

### Participantes demasiado bajos

```bash
VOLUMEN_SISTEMA=0.85
```

## Seguridad y privacidad

No versionar audios, transcripciones, JSON, tokens, archivos `.env`, modelos ni cachés.

```bash
chmod 600 ~/.config/meetings-transcriptor.env
chmod 700 ~/proyectos/meetings/textos_reuniones
```

Si un token fue compartido accidentalmente, revocarlo y generar uno nuevo.

## .gitignore

```gitignore
.venv/
.venv*/
.venv-*/

__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.cache/

.env
*.env

*.wav
*.mp3
*.ogg
*.m4a
*.flac
*.json

models/
.DS_Store
```

`textos_reuniones` está fuera de la raíz del repositorio, por lo que Git no lo versiona.

## Flujo recomendado

1. Elegir perfil.
2. Revisar `initial_prompt.txt`.
3. Iniciar la reunión.
4. Ejecutar el script.
5. Presionar `Ctrl+C` al terminar.
6. Esperar WhisperX.
7. Revisar `transcripcion_speakers.txt`.
8. Corregir términos si hace falta.
9. Actualizar `initial_prompt.txt` para futuras reuniones.

## Limitaciones

Este flujo no ingresa automáticamente a Google Meet, no obtiene nombres de participantes, no reconoce identidades por voz y no reemplaza la revisión humana.

Puede equivocarse con modismos, nombres, términos técnicos, superposición de voces o asignación de hablantes.

## Posibles mejoras futuras

- resumen con Ollama;
- extracción de tareas y decisiones;
- minuta automática;
- identificación persistente de hablantes;
- configuración YAML por perfil;
- procesamiento por lotes;
- limpieza con un LLM local;
- exportación a Markdown;
- integración con Notion;
- uso de metadata de Google Meet.

## Comandos rápidos

```bash
# Grabar Shipii
./grabar_transcribir_diarizar.sh --profile Shipii

# Grabar Motonave
./grabar_transcribir_diarizar.sh --profile motonave

# Listar perfiles
./grabar_transcribir_diarizar.sh --list-profiles

# Reprocesar audio
./grabar_transcribir_diarizar.sh \
    --profile Shipii \
    --audio /ruta/reunion_mezclada.wav
```

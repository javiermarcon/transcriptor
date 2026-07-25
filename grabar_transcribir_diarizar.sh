#!/usr/bin/env bash
set -Eeuo pipefail

# Graba en paralelo:
#   1) audio del sistema (participantes remotos)
#   2) micrófono local
#   3) mezcla balanceada
#
# Luego usa WhisperX como opción principal para:
#   - VAD
#   - transcripción
#   - alineación
#   - diarización
#
# Los perfiles permiten separar reuniones y vocabulario contextual:
#
#   textos_reuniones/
#   ├── Shipii/
#   │   ├── initial_prompt.txt
#   │   └── Reunion_YYYY-MM-DD_HH-MM-SS/
#   └── motonave/
#       ├── initial_prompt.txt
#       └── Reunion_YYYY-MM-DD_HH-MM-SS/
#
# Uso:
#   ./grabar_transcribir_diarizar.sh --profile Shipii
#   ./grabar_transcribir_diarizar.sh Shipii
#
# También se puede reprocesar un audio existente:
#   ./grabar_transcribir_diarizar.sh --profile Shipii \
#       --audio /ruta/reunion_mezclada.wav

CONFIG_FILE="${CONFIG_FILE:-$HOME/.config/meetings-transcriptor.env}"

if [[ -r "$CONFIG_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
fi

BASE_DIR="${BASE_DIR:-$HOME/proyectos/meetings/textos_reuniones}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_VENV="$SCRIPT_DIR/.venv"

PROFILE="${PROFILE:-}"
AUDIO_EXISTENTE=""
LIST_PROFILES=0

usage() {
    cat <<'EOF'
Uso:
  grabar_transcribir_diarizar.sh --profile PERFIL
  grabar_transcribir_diarizar.sh PERFIL
  grabar_transcribir_diarizar.sh --profile PERFIL --audio ARCHIVO.wav
  grabar_transcribir_diarizar.sh --list-profiles

Opciones:
  -p, --profile PERFIL   Perfil de reunión: Shipii, motonave, etc.
  -a, --audio ARCHIVO    No graba; procesa una mezcla WAV ya existente.
      --list-profiles    Lista perfiles existentes.
  -h, --help             Muestra esta ayuda.

Variables:
  BASE_DIR               Directorio raíz de perfiles.
  PROFILE                Perfil predeterminado.
  MODELO                 Modelo Whisper; por defecto large-v3.
  BATCH_SIZE             Batch de WhisperX; por defecto 2.
  VOLUMEN_SISTEMA        Volumen de sistema en la mezcla; por defecto 0.70.
  VOLUMEN_MICROFONO      Volumen de micrófono en la mezcla; por defecto 2.00.
EOF
}

while (($#)); do
    case "$1" in
        -p|--profile)
            [[ $# -ge 2 ]] || { printf 'Falta el valor de %s\n' "$1" >&2; exit 2; }
            PROFILE="$2"
            shift 2
            ;;
        -a|--audio)
            [[ $# -ge 2 ]] || { printf 'Falta el valor de %s\n' "$1" >&2; exit 2; }
            AUDIO_EXISTENTE="$2"
            shift 2
            ;;
        --list-profiles)
            LIST_PROFILES=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            printf 'Opción desconocida: %s\n\n' "$1" >&2
            usage >&2
            exit 2
            ;;
        *)
            if [[ -z "$PROFILE" ]]; then
                PROFILE="$1"
                shift
            else
                printf 'Argumento inesperado: %s\n\n' "$1" >&2
                usage >&2
                exit 2
            fi
            ;;
    esac
done

mkdir -p "$BASE_DIR"

if (( LIST_PROFILES )); then
    find "$BASE_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
    exit 0
fi

if [[ -z "$PROFILE" ]]; then
    printf 'Tenés que indicar un perfil.\n\n' >&2
    usage >&2
    exit 2
fi

# Evita rutas relativas, traversal y caracteres problemáticos.
if [[ ! "$PROFILE" =~ ^[[:alnum:]_.-]+$ || "$PROFILE" == "." || "$PROFILE" == ".." ]]; then
    printf 'Nombre de perfil inválido: %s\n' "$PROFILE" >&2
    printf 'Usá solamente letras, números, guion, punto o guion bajo.\n' >&2
    exit 2
fi

PROFILE_DIR="$BASE_DIR/$PROFILE"
PROMPT_FILE="$PROFILE_DIR/initial_prompt.txt"
FECHA="$(date '+%Y-%m-%d_%H-%M-%S')"
RUN_DIR="$PROFILE_DIR/Reunion_$FECHA"

AUDIO_SISTEMA="$RUN_DIR/sistema.wav"
AUDIO_MICROFONO="$RUN_DIR/microfono.wav"
AUDIO_MEZCLA="$RUN_DIR/reunion_mezclada.wav"

TXT_NORMAL="$RUN_DIR/transcripcion.txt"
TXT_SPEAKERS="$RUN_DIR/transcripcion_speakers.txt"

mkdir -p "$PROFILE_DIR"

if [[ ! -e "$PROMPT_FILE" ]]; then
    cat >"$PROMPT_FILE" <<EOF
Reunión del perfil $PROFILE en español rioplatense.
Agregar aquí nombres de participantes, productos, empresas, siglas,
modismos y términos técnicos frecuentes.
EOF
    printf 'Se creó el prompt inicial del perfil:\n%s\n\n' "$PROMPT_FILE"
    printf 'Editalo para mejorar nombres propios y vocabulario específico.\n\n'
fi

SINK="${SINK:-$(pactl get-default-sink)}"
MIC="${MIC:-$(pactl get-default-source)}"

VOLUMEN_SISTEMA="${VOLUMEN_SISTEMA:-0.70}"
VOLUMEN_MICROFONO="${VOLUMEN_MICROFONO:-2.00}"

MODELO="${MODELO:-large-v3}"
THREADS="${THREADS:-4}"
BATCH_SIZE="${BATCH_SIZE:-2}"
VAD_METHOD="${VAD_METHOD:-pyannote}"
VAD_ONSET="${VAD_ONSET:-0.500}"
VAD_OFFSET="${VAD_OFFSET:-0.363}"

# Compatible con un único .venv y con rutas definidas en el archivo de configuración.
WHISPERX_BIN="${WHISPERX_BIN:-}"
WHISPER_CTRANSLATE2_BIN="${WHISPER_CTRANSLATE2_BIN:-}"

if [[ -z "$WHISPERX_BIN" && -x "$DEFAULT_VENV/bin/whisperx" ]]; then
    WHISPERX_BIN="$DEFAULT_VENV/bin/whisperx"
fi
if [[ -z "$WHISPER_CTRANSLATE2_BIN" && -x "$DEFAULT_VENV/bin/whisper-ctranslate2" ]]; then
    WHISPER_CTRANSLATE2_BIN="$DEFAULT_VENV/bin/whisper-ctranslate2"
fi

WHISPERX_BIN="${WHISPERX_BIN:-$(command -v whisperx || true)}"
WHISPER_CTRANSLATE2_BIN="${WHISPER_CTRANSLATE2_BIN:-$(command -v whisper-ctranslate2 || true)}"

cleanup_on_error() {
    local exit_code=$?
    if (( exit_code != 0 )); then
        printf '\nERROR: el proceso terminó con código %s.\n' "$exit_code" >&2
        printf 'Los archivos se conservaron en: %s\n' "$RUN_DIR" >&2
        command -v notify-send >/dev/null 2>&1 &&
            notify-send -u critical "Error de grabación/transcripción" \
                "Los archivos se conservaron en $RUN_DIR" || true
    fi
}
trap cleanup_on_error EXIT

read_initial_prompt() {
    python3 - "$PROMPT_FILE" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8").strip()
# Convierte saltos de línea en espacios para pasarlo como un único argumento CLI.
print(" ".join(text.split()))
PY
}

validar_audio() {
    local audio="$1"

    [[ -s "$audio" ]] || {
        printf 'El audio no existe o está vacío: %s\n' "$audio" >&2
        return 1
    }

    # Confirma que FFprobe pueda leer una duración positiva.
    local duracion
    duracion="$(
        ffprobe -v error \
            -show_entries format=duration \
            -of default=noprint_wrappers=1:nokey=1 \
            "$audio" 2>/dev/null || true
    )"

    python3 - "$duracion" <<'PY'
import sys
try:
    duration = float(sys.argv[1])
except (ValueError, IndexError):
    raise SystemExit(1)
raise SystemExit(0 if duration > 0 else 1)
PY
}

if [[ -n "$AUDIO_EXISTENTE" ]]; then
    AUDIO_EXISTENTE="$(realpath -- "$AUDIO_EXISTENTE")"
    validar_audio "$AUDIO_EXISTENTE" || {
        printf 'No se pudo validar el audio existente.\n' >&2
        exit 1
    }

    mkdir -p "$RUN_DIR"
    cp -- "$AUDIO_EXISTENTE" "$AUDIO_MEZCLA"

    printf '%s\n' "=============================================================="
    printf '%s\n' "PROCESANDO AUDIO EXISTENTE"
    printf '%s\n' "=============================================================="
    printf 'Perfil:       %s\n' "$PROFILE"
    printf 'Origen:       %s\n' "$AUDIO_EXISTENTE"
    printf 'Directorio:   %s\n' "$RUN_DIR"
else
    mkdir -p "$RUN_DIR"

    printf '%s\n' "=============================================================="
    printf '%s\n' "GRABANDO REUNIÓN"
    printf '%s\n' "=============================================================="
    printf 'Perfil:       %s\n' "$PROFILE"
    printf 'Prompt:       %s\n' "$PROMPT_FILE"
    printf 'Salida:       %s\n' "$SINK"
    printf 'Micrófono:    %s\n' "$MIC"
    printf 'Directorio:   %s\n' "$RUN_DIR"
    printf 'Sistema:      %s\n' "$AUDIO_SISTEMA"
    printf 'Micrófono:    %s\n' "$AUDIO_MICROFONO"
    printf 'Mezcla:       %s\n' "$AUDIO_MEZCLA"
    printf '\nPresioná Ctrl+C cuando termine la reunión.\n'
    printf '%s\n' "=============================================================="

    set +e
    ffmpeg \
        -hide_banner \
        -loglevel warning \
        -f pulse -i "${SINK}.monitor" \
        -f pulse -i "$MIC" \
        -filter_complex \
        "[0:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,asplit=2[sistema_guardar][sistema_mezclar]; \
         [1:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,asplit=2[micro_guardar][micro_mezclar]; \
         [sistema_mezclar]volume=${VOLUMEN_SISTEMA}[sistema_nivel]; \
         [micro_mezclar]volume=${VOLUMEN_MICROFONO}[micro_nivel]; \
         [sistema_nivel][micro_nivel]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[mezcla]" \
        -map "[sistema_guardar]" -c:a pcm_s16le -ar 16000 -ac 1 "$AUDIO_SISTEMA" \
        -map "[micro_guardar]"   -c:a pcm_s16le -ar 16000 -ac 1 "$AUDIO_MICROFONO" \
        -map "[mezcla]"          -c:a pcm_s16le -ar 16000 -ac 1 "$AUDIO_MEZCLA"
    FFMPEG_EXIT=$?
    set -e

    # FFmpeg devuelve frecuentemente 255 al recibir Ctrl+C/SIGINT aunque haya
    # cerrado correctamente los WAV. No se considera advertencia si los tres
    # archivos son válidos y tienen duración positiva.
    if [[ "$FFMPEG_EXIT" -ne 0 && "$FFMPEG_EXIT" -ne 130 && "$FFMPEG_EXIT" -ne 255 ]]; then
        printf 'FFmpeg terminó con un código inesperado: %s\n' "$FFMPEG_EXIT" >&2
        exit "$FFMPEG_EXIT"
    fi

    for audio in "$AUDIO_SISTEMA" "$AUDIO_MICROFONO" "$AUDIO_MEZCLA"; do
        if ! validar_audio "$audio"; then
            printf 'No se generó correctamente: %s\n' "$audio" >&2
            exit 1
        fi
    done

    if [[ "$FFMPEG_EXIT" -eq 255 ]]; then
        printf '\nFFmpeg recibió Ctrl+C y cerró correctamente los tres WAV.\n'
    else
        printf '\nGrabación finalizada. Se conservarán los tres audios.\n'
    fi
fi

INITIAL_PROMPT="$(read_initial_prompt)"

if [[ -n "$WHISPERX_BIN" && -x "$WHISPERX_BIN" && -n "${HF_TOKEN:-}" ]]; then
    printf '%s\n' "=============================================================="
    printf '%s\n' "TRANSCRIBIENDO Y DIARIZANDO CON WHISPERX"
    printf '%s\n' "=============================================================="
    printf 'Modelo: %s | CPU int8 | batch_size=%s | VAD=%s\n' \
        "$MODELO" "$BATCH_SIZE" "$VAD_METHOD"
    printf 'Prompt: %s\n' "$PROMPT_FILE"

    "$WHISPERX_BIN" "$AUDIO_MEZCLA" \
        --model "$MODELO" \
        --language es \
        --device cpu \
        --compute_type int8 \
        --batch_size "$BATCH_SIZE" \
        --vad_method "$VAD_METHOD" \
        --vad_onset "$VAD_ONSET" \
        --vad_offset "$VAD_OFFSET" \
        --initial_prompt "$INITIAL_PROMPT" \
        --condition_on_previous_text False \
        --diarize \
        --hf_token "$HF_TOKEN" \
        --output_dir "$RUN_DIR" \
        --output_format json

    JSON_RESULTADO="$(find "$RUN_DIR" -maxdepth 1 -type f -name '*.json' -printf '%T@ %p\n' |
        sort -nr |
        head -n1 |
        cut -d' ' -f2-)"

    if [[ -z "$JSON_RESULTADO" || ! -s "$JSON_RESULTADO" ]]; then
        printf 'WhisperX terminó, pero no se encontró el JSON resultante.\n' >&2
        exit 1
    fi

    python3 - "$JSON_RESULTADO" "$TXT_SPEAKERS" "$TXT_NORMAL" <<'PY'
import json
import re
import sys
from pathlib import Path

json_path = Path(sys.argv[1])
speakers_path = Path(sys.argv[2])
plain_path = Path(sys.argv[3])

data = json.loads(json_path.read_text(encoding="utf-8"))
segments = data.get("segments", [])

_space_re = re.compile(r"\s+")
_sentence_re = re.compile(r"[^.!?¡¿\n]+(?:[.!?]+|$)", re.UNICODE)

def normalize(text: str) -> str:
    text = _space_re.sub(" ", text).strip().casefold()
    return text.strip(" \t\r\n.,;:!?¡¿\"'()[]{}")

def collapse_repeated_sentences(text: str) -> str:
    """Elimina repeticiones consecutivas exactas dentro de un segmento.

    Conserva repeticiones naturales que pertenecen a una sola oración, por
    ejemplo: "No, no, no es un cambio".
    """
    units = [match.group(0).strip() for match in _sentence_re.finditer(text)]
    if not units:
        return _space_re.sub(" ", text).strip()

    result: list[str] = []
    previous = ""
    for unit in units:
        key = normalize(unit)
        if key and key == previous:
            continue
        result.append(unit)
        previous = key

    return _space_re.sub(" ", " ".join(result)).strip()

clean_segments: list[dict] = []
previous_text = ""

for segment in segments:
    raw_text = str(segment.get("text", "")).strip()
    text = collapse_repeated_sentences(raw_text)
    key = normalize(text)

    if not key:
        continue

    # Suprime segmentos consecutivos idénticos. Es conservador: solo compara
    # igualdad textual normalizada, no similitud aproximada.
    if key == previous_text:
        continue

    previous_text = key
    cleaned = dict(segment)
    cleaned["text"] = text
    clean_segments.append(cleaned)

speaker_lines: list[str] = []
plain_lines: list[str] = []
current_speaker: str | None = None
current_parts: list[str] = []

def flush() -> None:
    global current_speaker, current_parts
    text = " ".join(part.strip() for part in current_parts if part.strip()).strip()
    text = collapse_repeated_sentences(text)
    if text:
        speaker_lines.append(f"[{current_speaker or 'SPEAKER_UNKNOWN'}] {text}")
    current_speaker = None
    current_parts = []

for segment in clean_segments:
    text = segment["text"]

    speaker = segment.get("speaker")
    if not speaker:
        for word in segment.get("words") or []:
            if word.get("speaker"):
                speaker = word["speaker"]
                break
    speaker = speaker or "SPEAKER_UNKNOWN"

    plain_lines.append(text)

    if current_speaker is None:
        current_speaker = speaker
    elif speaker != current_speaker:
        flush()
        current_speaker = speaker

    current_parts.append(text)

flush()

plain_path.write_text(
    "\n".join(plain_lines).rstrip() + "\n",
    encoding="utf-8",
)
speakers_path.write_text(
    "\n".join(speaker_lines).rstrip() + "\n",
    encoding="utf-8",
)
PY

    printf '\nTranscripción con hablantes:\n%s\n' "$TXT_SPEAKERS"
    printf 'Transcripción sin etiquetas:\n%s\n' "$TXT_NORMAL"

elif [[ -n "$WHISPER_CTRANSLATE2_BIN" && -x "$WHISPER_CTRANSLATE2_BIN" ]]; then
    printf '%s\n' "=============================================================="
    printf '%s\n' "WHISPERX/HF_TOKEN NO DISPONIBLES: TRANSCRIPCIÓN SIN DIARIZAR"
    printf '%s\n' "=============================================================="

    "$WHISPER_CTRANSLATE2_BIN" "$AUDIO_MEZCLA" \
        --model "$MODELO" \
        --language es \
        --task transcribe \
        --compute_type int8 \
        --threads "$THREADS" \
        --beam_size 5 \
        --vad_filter True \
        --initial_prompt "$INITIAL_PROMPT" \
        --condition_on_previous_text False \
        --output_dir "$RUN_DIR" \
        --output_format txt

    GENERADO="${AUDIO_MEZCLA%.wav}.txt"
    if [[ -s "$GENERADO" ]]; then
        mv -- "$GENERADO" "$TXT_NORMAL"
    else
        printf 'No se encontró el TXT generado por whisper-ctranslate2.\n' >&2
        exit 1
    fi

    printf '\nTranscripción sin hablantes:\n%s\n' "$TXT_NORMAL"
    printf '\nPara diarizar, instalá WhisperX y definí HF_TOKEN.\n'
else
    printf '\nNo se encontró WhisperX ni whisper-ctranslate2.\n' >&2
    printf 'Los audios quedaron guardados en: %s\n' "$RUN_DIR" >&2
    exit 1
fi

command -v notify-send >/dev/null 2>&1 &&
    notify-send "Reunión procesada" \
        "Perfil $PROFILE: resultados guardados en $RUN_DIR" || true

trap - EXIT
printf '\nProceso completado.\nPerfil: %s\nDirectorio: %s\n' "$PROFILE" "$RUN_DIR"

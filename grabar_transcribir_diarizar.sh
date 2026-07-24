#!/usr/bin/env bash
set -Eeuo pipefail

# Graba en paralelo:
#   1) audio del sistema (participantes remotos)
#   2) micrófono local
#   3) mezcla balanceada
# Luego transcribe y, si WhisperX + HF_TOKEN están disponibles, diariza
# la mezcla como SPEAKER_00, SPEAKER_01, etc.

BASE_DIR="${BASE_DIR:-$HOME/proyectos/meetings/textos_reuniones}"
FECHA="$(date '+%Y-%m-%d_%H-%M-%S')"
RUN_DIR="$BASE_DIR/Reunion_$FECHA"

AUDIO_SISTEMA="$RUN_DIR/sistema.wav"
AUDIO_MICROFONO="$RUN_DIR/microfono.wav"
AUDIO_MEZCLA="$RUN_DIR/reunion_mezclada.wav"

TXT_NORMAL="$RUN_DIR/transcripcion.txt"
TXT_SPEAKERS="$RUN_DIR/transcripcion_speakers.txt"

SINK="${SINK:-$(pactl get-default-sink)}"
MIC="${MIC:-$(pactl get-default-source)}"

# Ajustes de volumen para la mezcla.
VOLUMEN_SISTEMA="${VOLUMEN_SISTEMA:-0.70}"
VOLUMEN_MICROFONO="${VOLUMEN_MICROFONO:-2.00}"

MODELO="${MODELO:-large-v3}"
THREADS="${THREADS:-4}"
BATCH_SIZE="${BATCH_SIZE:-2}"

# Se recomienda instalar WhisperX en un venv aislado y exportar:
#   WHISPERX_BIN="$HOME/proyectos/meetings/transcriptor/.venv/bin/whisperx"
WHISPERX_BIN="${WHISPERX_BIN:-$(command -v whisperx || true)}"
WHISPER_CTRANSLATE2_BIN="${WHISPER_CTRANSLATE2_BIN:-$(command -v whisper-ctranslate2 || true)}"

mkdir -p "$RUN_DIR"

cleanup_on_error() {
    local exit_code=$?
    if (( exit_code != 0 )); then
        printf '\nERROR: el proceso terminó con código %s.\n' "$exit_code" >&2
        printf 'Los audios se conservaron en: %s\n' "$RUN_DIR" >&2
        command -v notify-send >/dev/null 2>&1 &&
            notify-send -u critical "Error de grabación/transcripción" \
                "Los audios se conservaron en $RUN_DIR" || true
    fi
}
trap cleanup_on_error EXIT

printf '%s\n' "=============================================================="
printf '%s\n' "GRABANDO REUNIÓN"
printf '%s\n' "=============================================================="
printf 'Salida:       %s\n' "$SINK"
printf 'Micrófono:    %s\n' "$MIC"
printf 'Directorio:   %s\n' "$RUN_DIR"
printf 'Sistema:      %s\n' "$AUDIO_SISTEMA"
printf 'Micrófono:    %s\n' "$AUDIO_MICROFONO"
printf 'Mezcla:       %s\n' "$AUDIO_MEZCLA"
printf '\nPresioná Ctrl+C cuando termine la reunión.\n'
printf '%s\n' "=============================================================="

# Cada entrada se divide en dos:
# - una copia limpia para guardar por separado;
# - otra copia con volumen ajustado para la mezcla.
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

# Ctrl+C suele devolver 130; FFmpeg también puede devolver 255 al recibir SIGINT,
# aunque cierre correctamente los WAV.
if [[ "$FFMPEG_EXIT" -ne 0 && "$FFMPEG_EXIT" -ne 130 && "$FFMPEG_EXIT" -ne 255 ]]; then
    printf 'FFmpeg terminó con un código inesperado: %s\n' "$FFMPEG_EXIT" >&2
    exit "$FFMPEG_EXIT"
fi

for audio in "$AUDIO_SISTEMA" "$AUDIO_MICROFONO" "$AUDIO_MEZCLA"; do
    if [[ ! -s "$audio" ]]; then
        printf 'No se generó correctamente: %s\n' "$audio" >&2
        exit 1
    fi
done

printf '\nGrabación finalizada. Se conservarán los tres audios.\n'

if [[ -n "$WHISPERX_BIN" && -x "$WHISPERX_BIN" && -n "${HF_TOKEN:-}" ]]; then
    printf '%s\n' "=============================================================="
    printf '%s\n' "TRANSCRIBIENDO Y DIARIZANDO CON WHISPERX"
    printf '%s\n' "=============================================================="
    printf 'Modelo: %s | CPU int8 | batch_size=%s\n' "$MODELO" "$BATCH_SIZE"

    "$WHISPERX_BIN" "$AUDIO_MEZCLA" \
        --model "$MODELO" \
        --language es \
        --device cpu \
        --compute_type int8 \
        --batch_size "$BATCH_SIZE" \
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
import sys
from pathlib import Path

json_path = Path(sys.argv[1])
speakers_path = Path(sys.argv[2])
plain_path = Path(sys.argv[3])

data = json.loads(json_path.read_text(encoding="utf-8"))
segments = data.get("segments", [])

speaker_lines = []
plain_lines = []
current_speaker = None
current_parts = []

def flush() -> None:
    global current_speaker, current_parts
    text = " ".join(part.strip() for part in current_parts if part.strip()).strip()
    if text:
        speaker_lines.append(f"[{current_speaker or 'SPEAKER_UNKNOWN'}] {text}")
    current_speaker = None
    current_parts = []

for segment in segments:
    text = str(segment.get("text", "")).strip()
    if not text:
        continue

    speaker = segment.get("speaker")
    if not speaker:
        words = segment.get("words") or []
        for word in words:
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

speakers_path.write_text("\n".join(speaker_lines) + "\n", encoding="utf-8")
plain_path.write_text("\n".join(plain_lines) + "\n", encoding="utf-8")
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
    printf 'Los tres audios quedaron guardados en: %s\n' "$RUN_DIR" >&2
    exit 1
fi

command -v notify-send >/dev/null 2>&1 &&
    notify-send "Reunión procesada" "Resultados guardados en $RUN_DIR" || true

trap - EXIT
printf '\nProceso completado.\nDirectorio: %s\n' "$RUN_DIR"

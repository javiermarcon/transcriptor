#!/usr/bin/env bash

set -u
set -o pipefail

DIR_DESTINO="$HOME/proyectos/meetings/textos_reuniones"
FECHA="$(date '+%Y-%m-%d_%H-%M-%S')"

AUDIO="$DIR_DESTINO/Reunion_$FECHA.wav"
TEXTO="$DIR_DESTINO/Reunion_Large_$FECHA.txt"

SINK="$(pactl get-default-sink)"
MIC="$(pactl get-default-source)"

mkdir -p "$DIR_DESTINO"

echo "=============================================================="
echo "GRABANDO REUNIÓN"
echo "=============================================================="
echo "Salida:     $SINK"
echo "Micrófono:  $MIC"
echo "Audio:      $AUDIO"
echo
echo "Presioná Ctrl+C cuando termine la reunión."
echo "=============================================================="

ffmpeg \
  -hide_banner \
  -loglevel warning \
  -f pulse -i "${SINK}.monitor" \
  -f pulse -i "$MIC" \
  -filter_complex \
  "[0:a]aresample=16000,volume=0.70[sistema]; \
   [1:a]aresample=16000,volume=2.0[micro]; \
   [sistema][micro]amix=inputs=2:duration=longest:normalize=0, \
   alimiter=limit=0.95[a]" \
  -map "[a]" \
  -ac 1 \
  -ar 16000 \
  -c:a pcm_s16le \
  "$AUDIO"

GRABACION_EXIT=$?

echo
echo "Grabación finalizada."

if [[ ! -s "$AUDIO" ]]; then
    echo "ERROR: no se generó un audio válido."
    notify-send -u critical \
      "Error de grabación" \
      "No se generó un archivo de audio válido."
    exit 1
fi

# Ctrl+C hace que ffmpeg pueda terminar con 130.
# El WAV igualmente queda correctamente cerrado.
if [[ "$GRABACION_EXIT" -ne 0 && "$GRABACION_EXIT" -ne 130 ]]; then
    echo "Advertencia: ffmpeg terminó con código $GRABACION_EXIT."
    echo "Se conservará el audio y se intentará transcribir."
fi

echo "=============================================================="
echo "TRANSCIBIENDO CON WHISPER LARGE V3"
echo "=============================================================="
echo "Este proceso puede tardar bastante en tu i7-3770K."
echo "El audio se conservará hasta confirmar que el TXT existe."
echo "=============================================================="

if whisper-ctranslate2 "$AUDIO" \
    --model large-v3 \
    --language es \
    --task transcribe \
    --compute_type int8 \
    --threads 4 \
    --beam_size 5 \
    --vad_filter True \
    --initial_prompt \
      "Conversación en español argentino." \
    --output_dir "$DIR_DESTINO" \
    --output_format txt
then
    GENERADO="${AUDIO%.wav}.txt"

    if [[ -s "$GENERADO" ]]; then
        mv -- "$GENERADO" "$TEXTO"

        echo
        echo "Transcripción completada:"
        echo "$TEXTO"
        echo
        echo "Audio original conservado en:"
        echo "$AUDIO"

        notify-send \
          "Transcripción completada" \
          "Guardada en: $TEXTO"
    else
        echo
        echo "ERROR: Whisper terminó, pero no apareció:"
        echo "$GENERADO"
        echo
        echo "El audio se conserva en:"
        echo "$AUDIO"

        notify-send -u critical \
          "No se encontró la transcripción" \
          "El audio quedó guardado en $AUDIO"

        exit 1
    fi
else
    echo
    echo "ERROR: falló Whisper."
    echo "El audio se conserva en:"
    echo "$AUDIO"

    notify-send -u critical \
      "Falló la transcripción" \
      "El audio quedó guardado en $AUDIO"

    exit 1
fi

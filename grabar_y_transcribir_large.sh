#!/bin/bash
DIR_DESTINO="$HOME/proyectos/meetings/textos_reuniones"
FECHA=$(date +"%Y-%m-%d_%H-%m")
AUDIO_TMP="/tmp/reunion_$FECHA.wav"

mkdir -p "$DIR_DESTINO"

echo "================================================================="
echo "🔴 GRABANDO REUNIÓN (Modo ligero para no saturar tu i7)"
echo "================================================================="
echo "El audio se está guardando localmente sin consumir apenas CPU."
echo "Cuando la reunión TERMINE, presiona [CTRL + C] en esta terminal."
echo "================================================================="

# Captura el audio del sistema consumiendo menos del 1% de tu CPU
parec --device=@DEFAULT_SINK@ --monitor | ffmpeg -i - -acodec pcm_s16le -ar 16000 -ac 1 "$AUDIO_TMP" -y -loglevel quiet

echo -e "\n================================================================="
echo "⏳ REUNIÓN FINALIZADA. CARGANDO MODELO WHISPER LARGE V3..."
echo "================================================================="
echo "Procesando en CPU local utilizando 4 núcleos físicos."
echo "Esto puede tardar unos minutos dependiendo de la duración."
echo "Por favor, espera..."
echo "================================================================="

# Ejecución diferida con el modelo de máxima calidad (Large v3)
# Usamos '--compute_type int8' para que tus 32GB de RAM procesen el modelo Large de forma ultra-eficiente en CPU Intel
whisper-ctranslate2 "$AUDIO_TMP" \
  --model large-v3 \
  --language es \
  --output_dir "$DIR_DESTINO" \
  --output_format txt \
  --compute_type int8 \
  --threads 4

# Renombrar el archivo generado para que quede limpio
if [ -f "$DIR_DESTINO/reunion_$FECHA.txt" ]; then
    mv "$DIR_DESTINO/reunion_$FECHA.txt" "$DIR_DESTINO/Reunion_Large_$FECHA.txt"
    echo -e "\n✅ [ÉXITO] Transcripción completada con calidad máxima."
    echo "Archivo guardado en: $DIR_DESTINO/Reunion_Large_$FECHA.txt"

    # Enviar notificación emergente al escritorio de Ubuntu 24.04
    notify-send -u normal -i accessories-text-editor "Transcripción Completada" "La reunión ha sido procesada con Whisper Large V3.\nGuardado como: $ARCH_FINAL"
else
    echo -e "\n⚠️ Nota: Revisa el directorio de destino, el archivo podría tener un nombre ligeramente diferente."
    notify-send -u critical -i dialog-warning "Error en Transcripción" "El proceso terminó pero no se encontró el archivo de texto esperado."
fi

# Limpieza del archivo de audio temporal
rm "$AUDIO_TMP"

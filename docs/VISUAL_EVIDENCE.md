# Evidencia visual (fase 1) — guía paso a paso

Relaciona frases con referencias espaciales («fijate acá», «este botón», …)
con fotogramas de `reunion.mp4`. **No** identifica el botón o componente de UI.

## 0. Qué hay en una carpeta de reunión

Ruta por defecto (`BASE_DIR`):

`~/proyectos/meetings/textos_reuniones/<perfil>/Reunion_YYYY-MM-DD_HH-MM-SS/`

Archivos relevantes:

| Archivo | Rol |
|---|---|
| `reunion.mp4` | Video H.264 **+ audio AAC de la mezcla** (mismo FFmpeg) |
| `reunion_mezclada.wav` | Audio que usa WhisperX (reloj de los timestamps) |
| `reunion_mezclada.json` | Segmentos WhisperX (`start`/`end`/`speaker`) |
| `transcripcion_atribuida.json` | Preferido si existe (incluye nombres) |
| `evidencia_visual/` | Salida de esta fase (se crea al extraer) |

**Importante:** el MP4 casi siempre trae audio embebido. La extracción de
fotogramas usa solo el stream de video (`-map 0:v:0 -an`). El audio del MP4
sirve para inspección manual (reproducir y contrastar con el JPG).

## 1. Prerrequisitos

```bash
cd ~/proyectos/meetings/transcriptor
source .venv/bin/activate
# Cargar env del host/CLI (recomendado):
set -a
source ~/.config/meetings-transcriptor.env
set +a

command -v ffmpeg && command -v ffprobe
```

La reunión debe tener al menos:

- `reunion.mp4` no vacío
- `transcripcion_atribuida.json` **o** `reunion_mezclada.json`
- (opcional pero útil) `reunion_mezclada.wav` para medir desfase

## 2. Configuración (opcional)

En `~/.config/meetings-transcriptor.env` o en la shell:

```bash
export VISUAL_EVIDENCE_CONTEXT_BEFORE_S=1.5   # segundos antes del inicio de la frase
export VISUAL_EVIDENCE_CONTEXT_AFTER_S=2.5    # segundos después del fin
export VISUAL_EVIDENCE_FRAME_INTERVAL_S=1.0   # muestreo dentro de la ventana
export VISUAL_EVIDENCE_MAX_FRAMES_PER_CANDIDATE=4
export VISUAL_EVIDENCE_JPEG_QUALITY=3         # -q:v de FFmpeg
# Patrones extra (id:regex separados por coma):
# export VISUAL_EVIDENCE_EXTRA_PATTERNS='custom:\bmirá\s+esto\b'
```

Patrones base: `src/meetings_transcriber/spatial_cues.py`
(`DEFAULT_SPATIAL_CUE_PATTERNS`).

## 3. Extraer evidencia

```bash
MEETING=~/proyectos/meetings/textos_reuniones/shipii/Reunion_YYYY-MM-DD_HH-MM-SS

meetings-transcriber \
  --profile shipii \
  --meeting "$MEETING" \
  --extract-visual-evidence
```

Salida esperada en consola: cantidad de candidatos, ruta del índice, y si hay
dato, el desfase `video-audio` medido con ffprobe.

Se crea:

```text
$MEETING/evidencia_visual/
  index.json
  frames/ve-0000_t….jpg
```

**No** modifica `reunion.mp4`, WAVs ni transcripciones.

## 4. Medir sincronización (recomendado antes de confiar)

WhisperX marca tiempo sobre `reunion_mezclada.wav`. El MP4 se graba en paralelo;
en una sesión real de este entorno se midió Δ ≈ 0.65 s entre duraciones.

```bash
ffprobe -v error -show_entries format=duration -of default=nw=1 "$MEETING/reunion.mp4"
ffprobe -v error -show_entries format=duration -of default=nw=1 "$MEETING/reunion_mezclada.wav"

# Streams dentro del MP4 (video vs audio embebido):
ffprobe -v error -show_entries stream=codec_type,duration \
  -of default=nw=1 "$MEETING/reunion.mp4"
```

El `index.json` incluye bloque `sync` con:

- `video_minus_audio_s` (contenedor MP4 vs WAV mezclado)
- `mp4_video_stream_s` / `mp4_audio_stream_s` / `mp4_video_minus_audio_stream_s`
- `mp4_contains_mixed_audio: true`
- texto de cómo medir y la advertencia de que **no** se identifica el UI

## 5. Inspección manual de un candidato

1. Abrí `$MEETING/evidencia_visual/index.json`.
2. Elegí un ítem en `candidates` (ej. `ve-0000`).
3. Anotá `start`/`end` y `selection_reasons`.
4. Reproducí el **MP4** (tiene audio) alrededor de ese tiempo, o el WAV mezclado.
5. Abrí los JPG listados en `frames[]`.
6. Decidí si la imagen ayuda a entender la referencia espacial.

## 6. Marcar revisión

```bash
meetings-transcriber --profile shipii --meeting "$MEETING" \
  --review-visual-evidence ve-0000 useful \
  --review-note "se ve el diálogo de permisos"

# Otros estados: insufficient | incorrect | pending
```

La re-extracción **conserva** revisiones previas del mismo `id`.

## 7. Esquema del índice (resumen)

```json
{
  "schema_version": 1,
  "session_id": "…",
  "video": "reunion.mp4",
  "sync": { "mp4_contains_mixed_audio": true, "video_minus_audio_s": 0.65 },
  "candidates": [
    {
      "id": "ve-0000",
      "text": "Fijate acá.",
      "speaker_id": "SPEAKER_00",
      "attributed_name": null,
      "start": 12.4,
      "end": 14.1,
      "window_start": 10.9,
      "window_end": 16.6,
      "selection_reasons": ["pattern:fijate:Fijate", "pattern:deixis_aca:acá"],
      "frames": [
        { "path": "evidencia_visual/frames/ve-0000_t….jpg", "timestamp_s": 12.5, "status": "ok" }
      ],
      "review": { "status": "pending", "updated_at": null, "note": null },
      "errors": []
    }
  ]
}
```

`frames[].status`: `ok` | `reused` (mismo instante ya extraído) | `error`.

## 8. Pruebas automatizadas

```bash
cd ~/proyectos/meetings/transcriptor
source .venv/bin/activate
pre-commit run --all-files
# o foco:
pytest tests/test_visual_evidence.py tests/test_spatial_cues.py -q \
  --cov=meetings_transcriber.visual_evidence \
  --cov=meetings_transcriber.spatial_cues \
  --cov-report=term-missing
```

Incluyen: sin video, fuera de rango, deduplicación, fallo FFmpeg, revisión,
legacy sin atribución, env inválido, y un caso con **FFmpeg real** que genera
un MP4 con audio AAC y extrae un JPG.

## 9. Límites de esta fase

- Sin modelo multimodal / OCR / detección de botones.
- Un JPG cerca de «acá» **no** prueba qué elemento se señaló.
- Los timestamps no son perfectos; usá el bloque `sync` y revisión humana.

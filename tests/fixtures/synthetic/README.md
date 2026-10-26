# Fixtures sintéticos (NO son grabaciones reales)

Estos archivos **no** provienen de Google Meet, FFmpeg ni WhisperX reales.
Sirven solo para pruebas reproducibles de contratos y atribución.

- `meet_events_sequence.jsonl` — secuencia `record_meet_event` alineada al esquema de la extensión.
- `whisperx_segments.json` — JSON mínimo estilo WhisperX (`segments` + `speaker`).
- `legacy_meeting/` — carpeta de reunión antigua: solo WAV sintéticos + JSON WhisperX, **sin** `meet_events.jsonl` ni `session.json`.

# Validación: extensión Firefox + host hasta atribución

Informe de auditoría y guía manual. Generado tras inspeccionar el código
real y ejecutar las suites (sin reunión real con otra persona).

## Estado de Git (al auditar)

| Repo | Rama | Nota |
|---|---|---|
| `transcriptor` | `main` | 1 commit local adelante de `origin` (`feat: atribución…`) |
| `transcriptor-firefox` | `main` | al día con `origin` (v0.3.4) |

## Fase 1 — Qué existe y qué se ejecutó

### Transcriptor (`/home/javier/proyectos/meetings/transcriptor`)

**Comandos:**

```bash
cd /home/javier/proyectos/meetings/transcriptor
source .venv/bin/activate
pre-commit run --all-files   # ruff + mypy + pytest
```

**Resultado real:** ruff Passed, mypy Passed, pytest Passed.

**Suite (aprox. 180 tests):** CLI, audio/FFmpeg (mocks), perfiles, WhisperX
command building, postprocess, Native Messaging (protocolo, framing, host,
controller, install), Wayland/X11 window capture (mocks), **atribución**,
**meet_events**, contrato sintético con la extensión.

**No ejecuta de verdad:** FFmpeg grabando escritorio, WhisperX GPU, Meet, Firefox.

### Extensión (`/home/javier/proyectos/meetings/transcriptor-firefox`)

**Comandos:**

```bash
cd /home/javier/proyectos/meetings/transcriptor-firefox
npm run check   # format + lint + validate-manifest + test:coverage (umbral 99%)
```

**Resultado real:** 82+ tests pass (más el contrato sintético nuevo), cobertura
shared/scripts ≥ 99%.

**Cubre con mocks:** protocolo v1, native-client (timeout, disconnect, host
ausente, session_id), background start/stop, popup sin “Grabando” falso,
diffs Meet sobre **fixtures HTML sintéticos** (`tests/fixtures/meet-roster-*.html`).

**No prueba:** DOM vivo de Meet, host nativo real, FFmpeg, WhisperX.

### Compatibilidad de contratos

| Contrato | Extensión | Host | Compatible |
|---|---|---|---|
| Host name | `com.meetings.transcriptor` | igual | sí |
| Acciones v1 | get/list/start/stop/`record_meet_event` | mismas | sí |
| Meet event fields | `meet-event-schema.js` / `MEET_EVENTS.md` | `meet_events.validate_meet_event_payload` | sí (cubierto por fixtures sintéticos) |
| Atribución | envía eventos; no atribuye | `transcripcion_atribuida.json` | sí |

### Rutas de salida reales (descubiertas en código/config)

Default `BASE_DIR` = `~/proyectos/meetings/textos_reuniones`
(`src/meetings_transcriber/config.py`; override con `BASE_DIR` en
`~/.config/meetings-transcriptor.env`).

Por reunión:

```text
$BASE_DIR/<perfil>/Reunion_YYYY-MM-DD_HH-MM-SS/
  microfono.wav
  sistema.wav
  reunion_mezclada.wav
  reunion.mp4          # si RECORD_VIDEO
  reunion_mezclada.json
  transcripcion.txt
  transcripcion_speakers.txt
  transcripcion_atribuida.json   # capa de nombres
  session.json                   # si grabó vía Native Messaging
  meet_events.jsonl              # si la extensión envió eventos
```

El host NM carga `~/.config/meetings-transcriptor.env` al arrancar
(`native_host.main` → `load_env_file`). Para atribución local:

```bash
export LOCAL_PARTICIPANT_NAME=Javier
```

## Limitaciones de alineación temporal (Meet ↔ WhisperX)

- Los eventos traen `timestamp_epoch_ms` (reloj del navegador).
- El host guarda `recording_started_at_epoch_ms` en `session.json`.
- Tiempo relativo audio ≈ `(event_ms - started_ms) / 1000`.
- Se aplica incertidumbre ~±1.5 s (polling Meet ~2 s + alineación ASR).
- Un solo `active_speaker_changed` no basta; hace falta evidencia agregada.
- `participant_joined` **nunca** atribuye por sí solo.
- La atribución es por `SPEAKER_*` (mapa), no re-diariza.
- Si el mismo `display_name` aparece con **distintos** `participant_key`
  (p. ej. clave de lista vs clave de “hablando”), el host lo trata como
  nombre ambiguo y **no atribuye**. Los fixtures sintéticos usan la misma
  key estable por persona a propósito.

## Fase 3 — Guía manual (un solo usuario)

### 1. Cargar la extensión temporalmente

1. `about:debugging#/runtime/this-firefox`
2. **Cargar complemento temporal…** →
   `/home/javier/proyectos/meetings/transcriptor-firefox/manifest.json`
3. ID esperado: `meetings-transcriptor@example.org`

### 2. Host Native Messaging

```bash
cd /home/javier/proyectos/meetings/transcriptor
./scripts/native-messaging.sh verify
# si falla:
./scripts/native-messaging.sh install
./scripts/native-messaging.sh verify
```

Confirmá en `~/.config/meetings-transcriptor.env`: `HF_TOKEN`, perfil,
`LOCAL_PARTICIPANT_NAME=Javier` (opcional pero útil). Recargá la extensión
o reiniciá Firefox tras cambiar el env (el host lee el env al conectar).

### 3. Reunión instantánea con un solo participante

1. Abrí [https://meet.google.com/](https://meet.google.com/) → **Nueva reunión**
   → **Iniciar una reunión instantánea** (solo vos).
2. Abrí el popup de la extensión.
3. Esperado: host **listo**, pestaña Meet detectada, selector de perfil.
4. **Iniciar grabación**. Esperado: estado Grabando + `session_id` (si no hay
   `session_id`, la UI no debe quedar en Grabando).
5. Hablá 20–30 s; opcional: abrí el panel de participantes; activá
   **Modo diagnóstico** en el popup.
6. **Detener**. Si preguntan transcribir: sí para generar transcripts.

### 4. Archivos a inspeccionar

Encontrá la carpeta más reciente:

```bash
ls -lt ~/proyectos/meetings/textos_reuniones/* /Reunion_* 2>/dev/null | head
# o el perfil que elegiste, p. ej. shipii:
ls -lt ~/proyectos/meetings/textos_reuniones/shipii/ | head
```

Comprobaciones:

| Archivo | Esperado |
|---|---|
| `reunion.mp4` | Se reproduce (video + audio mezclado) |
| `reunion_mezclada.wav` / `microfono.wav` / `sistema.wav` | Audibles; mic ≠ silencio si hablaste |
| `session.json` | `session_id`, `recording_started_at_epoch_ms` |
| `meet_events.jsonl` | Al menos `observation_started` / joins / quizás `active_speaker_*` |
| `transcripcion_speakers.txt` | Líneas `[SPEAKER_XX] …` |
| `transcripcion_atribuida.json` | Mismos `speaker_id`; `attributed_name` null o tu nombre local si hubo evidencia mic |

Con **un solo participante**, lo más realista es atribución por mic →
`LOCAL_PARTICIPANT_NAME`, no “Nacho”.

### 5. Segunda cuenta (mismo usuario, dos navegadores/perfiles)

1. Entrá a la misma reunión con otra cuenta Google (otro perfil Firefox o
   ventana privada).
2. Grabá de nuevo desde el popup en la pestaña donde está el host/extensión.
3. Esperado: más `participant_joined` / `active_speaker_changed` en
   `meet_events.jsonl`.
4. Tras transcribir, revisá si algún `SPEAKER_*` remoto recibió nombre
   **solo** vía `meet_active_speaker` (no por estar en el roster).

### 6. Fallback sin extensión (CLI / FFmpeg)

```bash
cd /home/javier/proyectos/meetings/transcriptor
source .venv/bin/activate
# opcional: source ~/.config/meetings-transcriptor.env
meetings-transcriber --profile shipii
# Ctrl+C para detener; aceptar transcribir si pregunta
```

O con monitor explícito en NM: `NATIVE_VIDEO_SOURCE=monitor` (documentado en
README; no es fallback silencioso).

No habrá `meet_events.jsonl` ni `session.json` en flujo CLI puro; la
atribución Meet no aplica; mic local sí si configuraste el nombre.

## Separación de validación

### 1. Validado mediante pruebas automatizadas

- Protocolo NM v1 (ambos lados) y framing del host.
- Start/stop, duplicado, sin sesión, disconnect, errores sin “Grabando” falso.
- Persistencia `record_meet_event` + `session.json` (host, con FFmpeg mockeado).
- Diffs Meet / schema / observation lifecycle (fixtures HTML sintéticos).
- Atribución: mic, Meet, conflictos, desfases, nombres ambiguos, roster≠habla,
  legacy sin eventos, conservación de `SPEAKER_*`.
- Contrato de payloads sintéticos extensión ↔ host.

### 2. Validado manualmente

- *(Pendiente en esta sesión de agente: no se cargó Firefox ni se abrió Meet.)*
- Usá la guía de arriba; marcá cada ítem al completarlos vos.

### 3. Pendiente de probar con una reunión real

- Selectores DOM reales de Meet (cambian sin aviso).
- Latencia real navegador ↔ `session.json` ↔ segmentos WhisperX.
- Observación con panel de participantes cerrado/abierto.
- Caída del host a mitad de grabación en Firefox real.
- Portal Wayland / captura de ventana en tu sesión gráfica concreta.

### 4. Pendiente de validar con voces distintas

- Que `SPEAKER_00`/`SPEAKER_01` correspondan a dos personas reales distintas.
- Que Meet marque el hablante visual correcto al hablar cada uno.
- Conflicto eco auriculares (voz local en `sistema.wav`) vs mic.
- Atribución remota fiable (Nacho u otros) sin confiar solo en el roster.

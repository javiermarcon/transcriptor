# README - Transcriptor de reuniones

Este README resume la configuración del proyecto.

## Estructura

```text
~/proyectos/meetings/
├── meetily/
├── textos_reuniones/
└── transcriptor/
    ├── .git/
    ├── .venv-ctranslate2/
    ├── .venv-whisperx/
    ├── grabar_y_transcribir_large.sh
    ├── grabar_transcribir_diarizar.sh
    └── README.md
```

Los scripts viven en `transcriptor` y las grabaciones en `textos_reuniones`.

## Instalación

Instalar FFmpeg, Python y crear dos entornos virtuales separados:

- `.venv-ctranslate2` para `whisper-ctranslate2`.
- `.venv-whisperx` para `whisperx`.

Crear un token en https://huggingface.co/settings/tokens (permiso Read o Fine-grained con acceso a repositorios gated), aceptar las condiciones del modelo https://huggingface.co/pyannote/speaker-diarization-community-1 y guardar:

```bash
mkdir -p ~/.config
nano ~/.config/meetings-transcriptor.env
```

```bash
export HF_TOKEN='hf_...'
export WHISPERX_BIN="$HOME/proyectos/meetings/transcriptor/.venv-whisperx/bin/whisperx"
export WHISPER_CTRANSLATE2_BIN="$HOME/proyectos/meetings/transcriptor/.venv-ctranslate2/bin/whisper-ctranslate2"
```

Luego:

```bash
source ~/.config/meetings-transcriptor.env
~/proyectos/meetings/transcriptor/grabar_transcribir_diarizar.sh
```

El script avanzado genera:

- sistema.wav
- microfono.wav
- reunion_mezclada.wav
- transcripcion.txt
- transcripcion_speakers.txt
- reunion_mezclada.json

WhisperX separa hablantes como SPEAKER_00, SPEAKER_01, etc., pero no identifica nombres reales.

Se recomienda excluir `../textos_reuniones/`, `.venv*/`, `*.wav`, `*.json` y `.env` del repositorio.

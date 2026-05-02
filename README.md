# SECS/GEM Simulator

Python **3.10+** desktop simulator (SEMI E5 / E30 / E37) with **Tkinter** GUI.

- **Usage / architecture**: see [MANUAL.md](MANUAL.md).
- **Tests**: `python3 -m pytest tests/ -q`

## Hugging Face Space (Docker)

1. Create a Space: **New Space** → SDK **Docker** → template **Blank** → hardware **Free**.
2. Push this repository (or upload files) so the Space root contains `Dockerfile`, `main.py`, `core/`, `handlers/`, `gui/`, `config/`, `scripts/`, etc.
3. Commit and wait until the Space shows **Running**.
4. Open the Space URL; the canvas shows **noVNC**. Click **Connect** / interact with the desktop — you should see the simulator window.

Optional Space variable: **`HF_MODEL`** = `6600WB` or `6500WB` (default `6600WB`). Skips the model picker via `main.py --model`.

**Note:** HSMS TCP from outside the Space is not the primary use case on free Spaces (HTTP is proxied on **7860**). The GUI and in-process Quick actions work as in the manual.

Local Docker check:

```bash
docker build -t secs-sim .
docker run --rm -p 7860:7860 secs-sim
```

Then open `http://localhost:7860`.

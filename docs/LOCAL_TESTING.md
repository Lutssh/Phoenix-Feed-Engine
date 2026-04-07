# Local Testing & Algorithm Execution Guide

This guide explains how to run the distributed feed algorithm and neural ingestion pipeline locally on your machine without Docker.

## 1. Prerequisites

Before running the system, ensure you have the following installed on your Linux system:

*   **Redis Server:** `sudo apt install redis-server`
*   **FFmpeg:** `sudo apt install ffmpeg` (Required for audio processing)
*   **Rust Toolchain:** Install via [rustup.rs](https://rustup.rs/) (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`)
*   **Python 3.10+:** `sudo apt install python3 python3-venv python3-pip`

## 2. Project Structure

Ensure your files are organized as follows:

```text
feed_algorithm/               <-- ROOT DIRECTORY
├── run_local.sh              <-- Master startup script
├── ingest_video.py           <-- Tool to ingest videos/images
├── ingest_text.py            <-- Tool to ingest text posts
├── test_description_quality.py <-- VERIFICATION TOOL (Run this first)
├── neural_ingestion/         <-- Python source code
├── rust_feed_engine/         <-- Rust source code
└── samples/                  <-- (Create this) Folder for your test media
```

## 3. Starting the System

We have a master script that sets up the environment, downloads the Vector DB (Qdrant), and starts all background workers.

1.  Open a terminal in the project root.
2.  Make the script executable (only needed once):
    ```bash
    chmod +x run_local.sh
    ```
3.  Run the system:
    ```bash
    ./run_local.sh
    ```

**What happens next?**
*   It creates a Python virtual environment (`venv`) and installs dependencies.
*   It downloads `qdrant` (Vector DB) if missing.
*   It starts **Redis**, **Qdrant**, and the **Celery Workers** in the background.
*   Finally, it compiles and starts the **Rust Feed Engine** in the foreground.

**Keep this terminal open.** It displays the logs for the main feed engine.

## 4. Running Tests & Ingestion

Open a **SECOND terminal** window and navigate to the project root.

### A. Setup Environment
You must activate the virtual environment created by the start script:

```bash
source venv/bin/activate
```

### B. Verify AI "Understanding" (Recommended First Step)
To see if the algorithm accurately describes your media (Video-LLaVA + YOLO + Whisper):

1.  Place a test image or video in a `samples` folder (e.g., `samples/cat.jpg`).
2.  Run the quality test:
    ```bash
    python test_description_quality.py samples/cat.jpg
    ```
    *   *Note: The first run takes 30-60s to load the AI models into memory.*
    *   **Output:** It will print the Visual Description, Detected Objects, and Audio Transcript.

### C. Ingest Content (Production Simulation)
To add content to the database without the verbose quality report:

**For Video/Images:**
```bash
# Syntax: python ingest_video.py <file_path> --caption "<optional_caption>"
python ingest_video.py samples/my_video.mp4 --caption "A funny video about cats"
```

**For Text Posts:**
```bash
# Syntax: python ingest_text.py "<text_content>" --post_id <unique_id>
python ingest_text.py "Just deployed my new algorithm!" --post_id 101
```

### D. Automated Pipeline Tests
To verify that data flows correctly from Python -> Redis -> Qdrant -> Rust:

```bash
# Test the full video pipeline (creates a dummy video)
python test_neural_pipeline.py

# Test the text pipeline
python test_text_pipeline.py
```

## 5. Stopping the System

1.  Go to the **First Terminal** (running the Rust engine).
2.  Press `Ctrl + C` to stop the Rust engine.
3.  To stop the background processes (Redis, Qdrant, Celery), the `run_local.sh` script suggests a command at startup, usually:
    ```bash
    kill <QDRANT_PID> <CELERY_PID>
    ```
    *(You can find these PIDs in the startup logs, or just `pkill -f qdrant` and `pkill -f celery` if you are on a dev machine).*

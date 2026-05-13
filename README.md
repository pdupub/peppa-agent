# Peppa

Peppa is a local AI agent runtime with a developer debug console.

## Development

Create local configuration:

```bash
cp config.example.toml config.toml
```

Install Python dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Install and build the debug console:

```bash
cd web
npm install
npm run build
```

Start Peppa:

```bash
peppa serve
```

Then open `http://127.0.0.1:8000`.

Reset local agent state when needed:

```bash
peppa reset-agent
```
AI Agent from Matrix
